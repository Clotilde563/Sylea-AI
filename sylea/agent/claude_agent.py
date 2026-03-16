"""
Agent IA principal de Syléa.AI ("Le Double").

Encapsule les appels à l'API Claude d'Anthropic pour :
1. Générer une analyse qualitative de la probabilité initiale
2. Analyser un dilemme décisionnel (pros/cons + impact sur la probabilité)
"""

import json
import re
from dataclasses import dataclass
from typing import List, Optional

import anthropic

from sylea.config.settings import get_api_key, CLAUDE_MODEL
from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import OptionDilemme


# ── Prompts système ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Tu es SYLÉA, un assistant de vie IA bienveillant, direct et précis.
Tu parles toujours en français. Tu utilises un ton professionnel mais chaleureux.
Tu ne répètes jamais la question de l'utilisateur. Tu vas droit au but.
Tes réponses sont structurées et factuelles. Tu n'inventes pas de données.
Tu réponds UNIQUEMENT en JSON valide lorsque demandé — sans markdown, sans texte avant ou après."""


# ── Dataclasses de résultat ──────────────────────────────────────────────────

@dataclass
class AnalyseProbabilite:
    """Résultat de l'analyse qualitative de la probabilité initiale."""
    probabilite: float
    resume: str
    points_forts: List[str]
    points_faibles: List[str]
    facteurs_cles: List[str]
    conseil_prioritaire: str


@dataclass
class AnalyseOption:
    """Analyse d'une option dans un dilemme."""
    pros: List[str]
    cons: List[str]
    impact_probabilite: float   # delta en points de %
    resume: str


@dataclass
class AnalyseDilemme:
    """Résultat complet de l'analyse d'un dilemme."""
    options: list  # List[AnalyseOption]
    verdict: str
    option_recommandee: str   # "A", "B", "C"...


# ── Agent principal ──────────────────────────────────────────────────────────

class AgentSylea:
    """
    Interface avec Claude pour les analyses de Syléa.AI.

    Utilise l'API Messages d'Anthropic et parse les réponses JSON.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=get_api_key())

    # ── Analyse de probabilité ────────────────────────────────────────────────

    def analyser_probabilite(
        self,
        profil: ProfilUtilisateur,
        probabilite_calculee: float,
    ) -> AnalyseProbabilite:
        """
        Génère une analyse qualitative de la probabilité calculée par le moteur.

        La probabilité numérique est TOUJOURS celle du moteur local (calibrée
        statistiquement par catégorie d'objectif). Claude enrichit l'analyse
        qualitative en utilisant le profil complet + le contexte Q&A personnalisé.

        Args:
            profil             : Profil complet de l'utilisateur
            probabilite_calculee: Probabilité déterministe calibrée (en %)

        Returns:
            AnalyseProbabilite avec résumé, forces, faiblesses, conseil
        """
        profil_resume = self._resumer_profil(profil)

        # Inclure l'objectif complet (avec le contexte Q&A s'il existe)
        objectif_desc = profil.objectif.description if profil.objectif else "Non défini"
        # Indication si du contexte personnalisé est disponible
        a_contexte_qa = "--- Contexte personnalisé ---" in objectif_desc

        prompt = f"""Analyse le profil suivant pour son objectif de vie et fournis une analyse qualitative approfondie.

PROFIL UTILISATEUR :
{profil_resume}

OBJECTIF DE VIE COMPLET :
{objectif_desc}
{"(Note : ce profil inclut des réponses personnalisées après \"--- Contexte personnalisé ---\". Utilise-les pour affiner ton analyse.)" if a_contexte_qa else ""}

PROBABILITÉ DE RÉUSSITE CALCULÉE : {probabilite_calculee:.2f}%
(Cette probabilité est calibrée statistiquement selon la difficulté réelle de l'objectif et le profil de l'utilisateur.)

Ta mission : expliquer qualitativement pourquoi cette probabilité est réaliste,
identifier les atouts concrets et les obstacles réels du profil par rapport à CET objectif spécifique,
et donner un conseil prioritaire actionnable basé sur les informations fournies.

Réponds UNIQUEMENT avec ce JSON (pas de markdown, pas de texte avant/après) :
{{
  "resume": "2-3 phrases concises expliquant cette probabilité au regard du profil et de l'objectif",
  "points_forts": ["atout concret 1", "atout concret 2", "atout concret 3"],
  "points_faibles": ["obstacle concret 1", "obstacle concret 2"],
  "facteurs_cles": ["facteur décisif 1", "facteur décisif 2"],
  "conseil_prioritaire": "Une action concrète et spécifique à entreprendre cette semaine"
}}"""

        data = self._appeler_claude(prompt)
        return AnalyseProbabilite(
            probabilite=probabilite_calculee,   # Toujours la valeur du moteur local
            resume=data.get("resume", ""),
            points_forts=data.get("points_forts", []),
            points_faibles=data.get("points_faibles", []),
            facteurs_cles=data.get("facteurs_cles", []),
            conseil_prioritaire=data.get("conseil_prioritaire", ""),
        )

    # ── Analyse de dilemme ───────────────────────────────────────────────────

    def analyser_dilemme(
        self,
        profil: ProfilUtilisateur,
        question: str,
        options: list,
        impact_temporel_jours: int | None = None,
    ) -> AnalyseDilemme:
        """
        Analyse un dilemme entre N options et calcule l'impact sur la probabilité.

        Args:
            profil    : Profil complet de l'utilisateur
            question  : La question posée par l'utilisateur
            options   : Liste des descriptions d'options (2 à 5)

        Returns:
            AnalyseDilemme avec pros/cons et impact pour chaque option
        """
        profil_resume = self._resumer_profil(profil)
        objectif_desc = (
            profil.objectif.description if profil.objectif else "Non défini"
        )
        prob_calculee = getattr(profil.objectif, 'probabilite_calculee', 0) if profil.objectif else 0
        prob_totale = profil.probabilite_actuelle + prob_calculee
        prob_totale = max(0.01, min(99.99, prob_totale))
        # Calculer le temps estime
        _tj = min(73000, max(1, round(900 * ((100 - prob_totale) / prob_totale) ** 0.675)))
        _ta, _rm = _tj // 365, (_tj % 365) // 30
        temps_estime_str = f"{_ta} ans {_rm} mois" if _ta > 0 else f"{_rm} mois"

        # Construire la liste d'options dynamiquement
        lettres = [chr(65 + i) for i in range(len(options))]
        options_text = "\n".join(f"OPTION {l} : {desc}" for l, desc in zip(lettres, options))

        # Construire le JSON attendu
        json_options = ",\n  ".join(
            f'"option_{l.lower()}": {{"pros": ["5 mots max", "5 mots max"], "cons": ["5 mots max"], "impact_probabilite": 0.0, "resume": "5 mots max"}}'
            for l in lettres
        )


        # Calibrer l'echelle d'impact selon l'impact temporel
        if impact_temporel_jours is not None and impact_temporel_jours > 0:
            if impact_temporel_jours <= 1:
                echelle_impact = (
                    f"Impact temporel: 1 jour. Impacts: +/-0.001 a +/-0.01%"
                )
            elif impact_temporel_jours <= 7:
                echelle_impact = (
                    f"Impact temporel: 1 semaine. Impacts: +/-0.005 a +/-0.05%"
                )
            elif impact_temporel_jours <= 30:
                echelle_impact = (
                    f"Impact temporel: 1 mois. Impacts: +/-0.01 a +/-0.1%"
                )
            elif impact_temporel_jours <= 365:
                echelle_impact = (
                    f"Impact temporel: 1 an. Impacts: +/-0.05 a +/-1.0%"
                )
            else:
                echelle_impact = (
                    f"Impact temporel: {impact_temporel_jours} jours (long terme). Impacts: +/-0.1 a +/-3.0%"
                )
        else:
            echelle_impact = (
                f"L'objectif est estime a {temps_estime_str}. "
                f"Decisions courtes: +/-0.001 a +/-0.02%, "
                f"decisions strategiques: +/-0.1 a +/-2%"
            )

        prompt = f"""Analyse ce dilemme de vie pour aider l'utilisateur \u00e0 d\u00e9cider.

PROFIL R\u00c9SUM\u00c9 :
{profil_resume}

OBJECTIF ULTIME : {objectif_desc}
PROBABILIT\u00c9 ACTUELLE D'ATTEINDRE L'OBJECTIF : {prob_totale:.2f}%
TEMPS ESTIME POUR L'OBJECTIF : {temps_estime_str}

QUESTION : {question}

{options_text}

REGLES DE FORMAT STRICTES :
- pros/cons : tableau de mots-cl\u00e9s de 3 \u00e0 6 mots MAXIMUM chacun. JAMAIS de phrase compl\u00e8te.
  BON : "Portfolio visible pour clients"
  MAUVAIS : "Un portfolio solide est le levier n\u00b01 pour d\u00e9crocher les premiers clients freelance"
- resume : 3 \u00e0 6 mots MAXIMUM
- verdict : 1 seule phrase de 15 mots MAXIMUM incluant la probabilit\u00e9 et le temps

R\u00e9ponds UNIQUEMENT avec ce JSON :
{{
  {json_options},
  "verdict": "15 mots max. Inclure {prob_totale:.1f}% et {temps_estime_str}.",
  "option_recommandee": "{lettres[0]}"
}}"""

# ── Agent principal ──────────────────────────────────────────────────────────

class AgentSylea:
    """
    Interface avec Claude pour les analyses de Syléa.AI.

    Utilise l'API Messages d'Anthropic et parse les réponses JSON.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=get_api_key())

    # ── Analyse de probabilité ────────────────────────────────────────────────

    def analyser_probabilite(
        self,
        profil: ProfilUtilisateur,
        probabilite_calculee: float,
    ) -> AnalyseProbabilite:
        """
        Génère une analyse qualitative de la probabilité calculée par le moteur.

        La probabilité numérique est TOUJOURS celle du moteur local (calibrée
        statistiquement par catégorie d'objectif). Claude enrichit l'analyse
        qualitative en utilisant le profil complet + le contexte Q&A personnalisé.

        Args:
            profil             : Profil complet de l'utilisateur
            probabilite_calculee: Probabilité déterministe calibrée (en %)

        Returns:
            AnalyseProbabilite avec résumé, forces, faiblesses, conseil
        """
        profil_resume = self._resumer_profil(profil)

        # Inclure l'objectif complet (avec le contexte Q&A s'il existe)
        objectif_desc = profil.objectif.description if profil.objectif else "Non défini"
        # Indication si du contexte personnalisé est disponible
        a_contexte_qa = "--- Contexte personnalisé ---" in objectif_desc

        prompt = f"""Analyse le profil suivant pour son objectif de vie et fournis une analyse qualitative approfondie.

PROFIL UTILISATEUR :
{profil_resume}

OBJECTIF DE VIE COMPLET :
{objectif_desc}
{"(Note : ce profil inclut des réponses personnalisées après \"--- Contexte personnalisé ---\". Utilise-les pour affiner ton analyse.)" if a_contexte_qa else ""}

PROBABILITÉ DE RÉUSSITE CALCULÉE : {probabilite_calculee:.2f}%
(Cette probabilité est calibrée statistiquement selon la difficulté réelle de l'objectif et le profil de l'utilisateur.)

Ta mission : expliquer qualitativement pourquoi cette probabilité est réaliste,
identifier les atouts concrets et les obstacles réels du profil par rapport à CET objectif spécifique,
et donner un conseil prioritaire actionnable basé sur les informations fournies.

Réponds UNIQUEMENT avec ce JSON (pas de markdown, pas de texte avant/après) :
{{
  "resume": "2-3 phrases concises expliquant cette probabilité au regard du profil et de l'objectif",
  "points_forts": ["atout concret 1", "atout concret 2", "atout concret 3"],
  "points_faibles": ["obstacle concret 1", "obstacle concret 2"],
  "facteurs_cles": ["facteur décisif 1", "facteur décisif 2"],
  "conseil_prioritaire": "Une action concrète et spécifique à entreprendre cette semaine"
}}"""

        data = self._appeler_claude(prompt)
        return AnalyseProbabilite(
            probabilite=probabilite_calculee,   # Toujours la valeur du moteur local
            resume=data.get("resume", ""),
            points_forts=data.get("points_forts", []),
            points_faibles=data.get("points_faibles", []),
            facteurs_cles=data.get("facteurs_cles", []),
            conseil_prioritaire=data.get("conseil_prioritaire", ""),
        )

    # ── Analyse de dilemme ───────────────────────────────────────────────────

    def analyser_dilemme(
        self,
        profil: ProfilUtilisateur,
        question: str,
        options: list,
        impact_temporel_jours: int | None = None,
    ) -> AnalyseDilemme:
        """
        Analyse un dilemme entre N options et calcule l'impact sur la probabilité.

        Args:
            profil    : Profil complet de l'utilisateur
            question  : La question posée par l'utilisateur
            options   : Liste des descriptions d'options (2 à 5)

        Returns:
            AnalyseDilemme avec pros/cons et impact pour chaque option
        """
        profil_resume = self._resumer_profil(profil)
        objectif_desc = (
            profil.objectif.description if profil.objectif else "Non défini"
        )
        prob_calculee = getattr(profil.objectif, 'probabilite_calculee', 0) if profil.objectif else 0
        prob_totale = profil.probabilite_actuelle + prob_calculee
        prob_totale = max(0.01, min(99.99, prob_totale))
        # Calculer le temps estime
        _tj = min(73000, max(1, round(900 * ((100 - prob_totale) / prob_totale) ** 0.675)))
        _ta, _rm = _tj // 365, (_tj % 365) // 30
        temps_estime_str = f"{_ta} ans {_rm} mois" if _ta > 0 else f"{_rm} mois"

        # Construire la liste d'options dynamiquement
        lettres = [chr(65 + i) for i in range(len(options))]
        options_text = "\n".join(f"OPTION {l} : {desc}" for l, desc in zip(lettres, options))

        # Construire le JSON attendu
        json_options = ",\n  ".join(
            f'"option_{l.lower()}": {{"pros": ["5 mots max", "5 mots max"], "cons": ["5 mots max"], "impact_probabilite": 0.0, "resume": "5 mots max"}}'
            for l in lettres
        )


        # Calibrer l'echelle d'impact selon l'impact temporel
        if impact_temporel_jours is not None and impact_temporel_jours > 0:
            if impact_temporel_jours <= 1:
                echelle_impact = (
                    f"Impact temporel: 1 jour. Impacts: +/-0.001 a +/-0.01%"
                )
            elif impact_temporel_jours <= 7:
                echelle_impact = (
                    f"Impact temporel: 1 semaine. Impacts: +/-0.005 a +/-0.05%"
                )
            elif impact_temporel_jours <= 30:
                echelle_impact = (
                    f"Impact temporel: 1 mois. Impacts: +/-0.01 a +/-0.1%"
                )
            elif impact_temporel_jours <= 365:
                echelle_impact = (
                    f"Impact temporel: 1 an. Impacts: +/-0.05 a +/-1.0%"
                )
            else:
                echelle_impact = (
                    f"Impact temporel: {impact_temporel_jours} jours (long terme). Impacts: +/-0.1 a +/-3.0%"
                )
        else:
            echelle_impact = (
                f"L'objectif est estime a {temps_estime_str}. "
                f"Decisions courtes: +/-0.001 a +/-0.02%, "
                f"decisions strategiques: +/-0.1 a +/-2%"
            )

        prompt = f"""Analyse ce dilemme de vie pour aider l'utilisateur \u00e0 d\u00e9cider.

PROFIL R\u00c9SUM\u00c9 :
{profil_resume}

OBJECTIF ULTIME : {objectif_desc}
PROBABILIT\u00c9 ACTUELLE D'ATTEINDRE L'OBJECTIF : {prob_totale:.2f}%
TEMPS ESTIME POUR L'OBJECTIF : {temps_estime_str}

QUESTION : {question}

{options_text}

REGLE ABSOLUE DE FORMAT :
- Chaque 'pros' et 'cons' = MAXIMUM 5 mots. Exemples : 'Portfolio visible pour clients', 'Comp\u00e9tence mobile demand\u00e9e'
- 'resume' = MAXIMUM 5 mots. Exemple : 'Priorit\u00e9 portfolio cette semaine'
- 'verdict' = 1 phrase courte MAXIMUM
- INTERDIT d'\u00e9crire des phrases compl\u00e8tes ou des explications d\u00e9taill\u00e9es

Pour chaque option :
1. Avantages (mots-cl\u00e9s de 3-5 mots)
2. Inconv\u00e9nients (mots-cl\u00e9s de 3-5 mots)
3. Impact probabilit\u00e9 (delta en %)
   {echelle_impact}

R\u00e9ponds UNIQUEMENT avec ce JSON (pas de markdown, pas de texte avant/apr\u00e8s) :
{{
  {json_options},
  "verdict": "MAX 15 mots. Inclure {prob_totale:.1f}% et {temps_estime_str}. Ex: Avec 38.4% et 3 ans, Option B prioritaire pour premiers clients.",
  "option_recommandee": "{lettres[0]}"
}}"""

        data = self._appeler_claude(prompt)

        def _truncate(text: str, max_words: int = 6) -> str:
            """Tronquer un texte a max_words mots."""
            words = text.split()
            if len(words) <= max_words:
                return text
            return " ".join(words[:max_words])

        def _parse_option(raw: dict) -> AnalyseOption:
            return AnalyseOption(
                pros=[_truncate(p) for p in raw.get("pros", [])],
                cons=[_truncate(c) for c in raw.get("cons", [])],
                impact_probabilite=float(raw.get("impact_probabilite", 0.0)),
                resume=_truncate(raw.get("resume", ""), 8),
            )

        parsed_options = []
        for l in lettres:
            key = f"option_{l.lower()}"
            raw = data.get(key, {})
            parsed_options.append(_parse_option(raw))

        return AnalyseDilemme(
            options=parsed_options,
            verdict=" ".join(data.get("verdict", "").split()[:25]),
            option_recommandee=data.get("option_recommandee", lettres[0]),
        )

    # ── Helpers internes ─────────────────────────────────────────────────────

    def _resumer_profil(self, profil: ProfilUtilisateur) -> str:
        """Génère un résumé textuel du profil pour les prompts."""
        lignes = [
            f"• Nom : {profil.nom}, {profil.age} ans, {profil.ville}",
            f"• Profession : {profil.profession} | Situation : {profil.situation_familiale}",
            f"• Revenu annuel : {profil.revenu_annuel:,.0f} € | Patrimoine : {profil.patrimoine_estime:,.0f} €",
            f"• Charges mensuelles : {profil.charges_mensuelles:,.0f} €",
            f"• Temps : {profil.heures_travail}h travail, {profil.heures_sommeil}h sommeil/jour",
            f"• Santé {profil.niveau_sante}/10 | Énergie {profil.niveau_energie}/10 | "
            f"Stress {profil.niveau_stress}/10 | Bonheur {profil.niveau_bonheur}/10",
        ]
        if profil.competences:
            lignes.append(f"• Compétences : {', '.join(profil.competences)}")
        if profil.diplomes:
            lignes.append(f"• Diplômes : {', '.join(profil.diplomes)}")
        # -- Temps estime et probabilite totale --
        if profil.objectif:
            _pc = getattr(profil.objectif, 'probabilite_calculee', 0) or 0
            _pt = max(0.01, min(99.99, _pc + profil.probabilite_actuelle))
            _tj = min(73000, max(1, round(900 * ((100 - _pt) / _pt) ** 0.675)))
            _ta, _rm = _tj // 365, (_tj % 365) // 30
            _ts = f"{_ta} ans {_rm} mois" if _ta > 0 else f"{_rm} mois"
            lignes.append(f"Temps estime pour atteindre l'objectif : {_ts}")
            lignes.append(f"Probabilite totale de reussite : {_pt:.1f}%")
        return "\n".join(lignes)

    def _appeler_claude(self, prompt: str) -> dict:
        """
        Appelle l'API Claude et parse la réponse JSON.

        Raises:
            ValueError: si la réponse n'est pas du JSON valide
            anthropic.APIError: si l'appel API échoue
        """
        message = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text.strip()

        # Extraire le JSON même si Claude ajoute du texte autour
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            raise ValueError(f"Réponse Claude non parsable : {content[:200]}")

        raw_json = json_match.group()
        # Nettoyer les trailing commas (erreur frequente de Claude)
        raw_json = re.sub(r',\s*}', '}', raw_json)
        raw_json = re.sub(r',\s*]', ']', raw_json)
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide dans la réponse Claude : {e}") from e
