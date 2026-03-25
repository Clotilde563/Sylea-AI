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
    etude_scientifique: str = ""  # Étude scientifique réelle liée au dilemme


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
        device_context: str = "",
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
{device_context}

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
        device_context: str = "",
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
            f'"option_{l.lower()}": {{"pros": ["5 mots max", "5 mots max"], "cons": ["5 mots max"], "impact_jours": 0.0, "resume": "5 mots max"}}'
            for l in lettres
        )


        # Contexte temporel pour l'IA
        if impact_temporel_jours is not None and impact_temporel_jours > 0:
            cadre_jours = impact_temporel_jours
            if cadre_jours <= 1:
                cadre_str = "1 jour (24 heures)"
                unite_impact = "heures (ex: +2.5 = 2h30 gagnees, -1.0 = 1h perdue)"
            elif cadre_jours <= 7:
                cadre_str = f"{cadre_jours} jours"
                unite_impact = "heures (ex: +8.0 = 8h gagnees, -3.5 = 3h30 perdues)"
            elif cadre_jours <= 30:
                cadre_str = f"~1 mois ({cadre_jours} jours)"
                unite_impact = "jours (ex: +5.0 = 5 jours gagnes, -2.0 = 2 jours perdus)"
            elif cadre_jours <= 365:
                cadre_str = f"~{cadre_jours // 30} mois ({cadre_jours} jours)"
                unite_impact = "jours (ex: +30.0 = 1 mois gagne, -15.0 = 15 jours perdus)"
            else:
                cadre_str = f"TOUTE LA DUREE DE L'OBJECTIF ({temps_estime_str}, soit {_tj} jours)"
                unite_impact = "jours (ex: +90.0 = 3 mois gagnes, -30.0 = 1 mois perdu)"
        else:
            cadre_jours = _tj
            cadre_str = f"TOUTE LA DUREE DE L'OBJECTIF ({temps_estime_str}, soit {_tj} jours)"
            unite_impact = "jours (ex: +90.0 = 3 mois gagnes, -30.0 = 1 mois perdu)"

        prompt = f"""Tu es un robot probabiliste froid et factuel. Tu analyses un dilemme de vie.
ZERO emotion, ZERO encouragement. Tu raisonnes en TEMPS, pas en pourcentage.

PROFIL R\u00c9SUM\u00c9 :
{profil_resume}

OBJECTIF ULTIME : {objectif_desc}
PROBABILIT\u00c9 ACTUELLE : {prob_totale:.2f}%
TEMPS ESTIME RESTANT : {temps_estime_str} ({_tj} jours)

CADRE TEMPOREL DE CE CHOIX : {cadre_str}

{device_context}

QUESTION : {question}

{options_text}

METHODE DE CALCUL (OBLIGATOIRE) :
1. PENSE EN TEMPS D'ABORD : combien de temps (heures ou jours) cette option fait-elle
   REELLEMENT gagner ou perdre sur l'objectif, DANS LA LIMITE du cadre temporel ({cadre_str}) ?
2. Le champ "impact_jours" doit contenir ce temps en {unite_impact}.
3. L'impact ne peut JAMAIS depasser le cadre temporel ({cadre_jours} jours max en valeur absolue).
4. REGLE CRITIQUE : Chaque option DOIT avoir un impact DIFFERENT et NON NUL.
   Meme si l'impact est minime, il existe toujours une difference entre deux choix.
   Si les deux options sont mauvaises, les deux impacts peuvent etre NEGATIFS.
   Si les deux options sont bonnes, les deux impacts peuvent etre POSITIFS mais differents.
   JAMAIS 0 pour les deux options. JAMAIS le meme impact pour deux options differentes.
5. Exemples concrets pour un cadre de 1 jour :
   - Soiree avec un ami motivant = +0.5h (energie positive le lendemain)
   - Soiree avec un ami demotivant = -1.5h (energie drainee, perte de focus le lendemain)
   - Dormir 8h au lieu de coder = +2.0h (productivite le lendemain)
   - Aller courir 1h = +0.5h (clarte mentale)
6. Exemples concrets pour un cadre de 1 mois :
   - Apprendre l'anglais vs l'espagnol = l'anglais fait gagner ~5-10 jours, l'espagnol ~1-3 jours
7. Sois REALISTE et FACTUEL. Pas d'impact par encouragement.

ETUDE SCIENTIFIQUE :
- Cite UNE etude scientifique REELLE et verifiable en rapport avec le dilemme pose.
- Inclus : auteurs, annee, revue/institution, et lien avec le dilemme.
- Varie l'etude selon le contexte. Sources : Nature, Science, The Lancet, PNAS, etc.

REGLES DE FORMAT STRICTES :
- pros/cons : tableau de mots-cl\u00e9s de 3 \u00e0 6 mots MAXIMUM chacun. JAMAIS de phrase compl\u00e8te.
- resume : 3 \u00e0 6 mots MAXIMUM
- verdict : 1 seule phrase de 15 mots MAXIMUM

R\u00e9ponds UNIQUEMENT avec ce JSON :
{{
  {json_options},
  "verdict": "2-3 phrases naturelles. NE PAS mentionner de pourcentage. Explique pourquoi cette option est meilleure.",
  "etude_scientifique": "Selon l etude de [Auteurs] ([Annee], [Revue]) sur [sujet], [conclusion cle].",
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
        device_context: str = "",
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
{device_context}

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
        device_context: str = "",
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
            f'"option_{l.lower()}": {{"pros": ["5 mots max", "5 mots max"], "cons": ["5 mots max"], "impact_jours": 0.0, "resume": "5 mots max"}}'
            for l in lettres
        )


        # Contexte temporel pour l'IA
        if impact_temporel_jours is not None and impact_temporel_jours > 0:
            cadre_jours = impact_temporel_jours
            if cadre_jours <= 1:
                cadre_str = "1 jour (24 heures)"
                unite_impact = "heures (ex: +2.5 = 2h30 gagnees, -1.0 = 1h perdue)"
            elif cadre_jours <= 7:
                cadre_str = f"{cadre_jours} jours"
                unite_impact = "heures (ex: +8.0 = 8h gagnees, -3.5 = 3h30 perdues)"
            elif cadre_jours <= 30:
                cadre_str = f"~1 mois ({cadre_jours} jours)"
                unite_impact = "jours (ex: +5.0 = 5 jours gagnes, -2.0 = 2 jours perdus)"
            elif cadre_jours <= 365:
                cadre_str = f"~{cadre_jours // 30} mois ({cadre_jours} jours)"
                unite_impact = "jours (ex: +30.0 = 1 mois gagne, -15.0 = 15 jours perdus)"
            else:
                cadre_str = f"TOUTE LA DUREE DE L'OBJECTIF ({temps_estime_str}, soit {_tj} jours)"
                unite_impact = "jours (ex: +90.0 = 3 mois gagnes, -30.0 = 1 mois perdu)"
        else:
            cadre_jours = _tj
            cadre_str = f"TOUTE LA DUREE DE L'OBJECTIF ({temps_estime_str}, soit {_tj} jours)"
            unite_impact = "jours (ex: +90.0 = 3 mois gagnes, -30.0 = 1 mois perdu)"

        prompt = f"""Tu es un robot probabiliste froid et factuel. Tu analyses un dilemme de vie.
ZERO emotion, ZERO encouragement. Tu raisonnes en TEMPS, pas en pourcentage.

PROFIL RESUME :
{profil_resume}
{device_context}

OBJECTIF ULTIME : {objectif_desc}
PROBABILITE ACTUELLE : {prob_totale:.2f}%
TEMPS ESTIME RESTANT : {temps_estime_str} ({_tj} jours)

CADRE TEMPOREL DE CE CHOIX : {cadre_str}

QUESTION : {question}

{options_text}

METHODE DE CALCUL (OBLIGATOIRE) :
1. PENSE EN TEMPS D'ABORD : combien de temps (heures ou jours) cette option fait-elle
   REELLEMENT gagner ou perdre sur l'objectif, DANS LA LIMITE du cadre temporel ({cadre_str}) ?
2. Le champ "impact_jours" doit contenir ce temps en {unite_impact}.
3. L'impact ne peut JAMAIS depasser le cadre temporel ({cadre_jours} jours max en valeur absolue).
4. Exemples concrets pour un cadre de 1 jour :
   - Dormir 8h au lieu de coder = +2.0 (heures de productivite gagnees)
   - Aller courir 1h = +0.5 (heures de clarte mentale gagnees)
5. Exemples concrets pour un cadre de 1 mois :
   - Apprendre l'anglais vs l'espagnol = l'anglais fait gagner ~5-10 jours, l'espagnol ~1-3 jours
6. Sois REALISTE et FACTUEL. Pas d'impact par encouragement.

ETUDE SCIENTIFIQUE :
- Cite UNE etude scientifique REELLE et verifiable en rapport avec le dilemme pose.
- Inclus : auteurs, annee, revue/institution, et lien avec le dilemme.
- Varie l'etude selon le contexte. Sources : Nature, Science, The Lancet, PNAS, etc.

REGLES DE FORMAT STRICTES :
- pros/cons : tableau de mots-cles de 3 a 6 mots MAXIMUM chacun. JAMAIS de phrase complete.
- resume : 3 a 6 mots MAXIMUM
- verdict : 1 seule phrase de 15 mots MAXIMUM

Reponds UNIQUEMENT avec ce JSON :
{{
  {json_options},
  "verdict": "2-3 phrases naturelles. NE PAS mentionner de pourcentage. Explique pourquoi cette option est meilleure.",
  "etude_scientifique": "Selon l etude de [Auteurs] ([Annee], [Revue]) sur [sujet], [conclusion cle].",
  "option_recommandee": "{lettres[0]}"
}}"""

        data = self._appeler_claude(prompt)

        def _clean_verdict(v: str) -> str:
            """Nettoyer le verdict: supprimer %, limiter longueur."""
            import re as _re
            v = " ".join(v.split()[:50])
            # Supprimer les pourcentages
            v = _re.sub(r'\d+[.,]?\d*\s*%', '', v)
            # Nettoyer les artefacts
            v = v.replace('À  sur', 'Sur').replace('A  sur', 'Sur')
            v = v.replace('Avec et ', 'Sur un horizon de ').replace('Avec  et ', 'Sur un horizon de ')
            v = v.replace('À et ', 'Sur ').replace('A et ', 'Sur ')
            v = v.replace('À sur', 'Sur').replace('A sur ', 'Sur ')
            # Nettoyer les doubles espaces
            v = _re.sub(r'\s+', ' ', v).strip()
            # Si commence par "de" ou "sur" en minuscule, capitaliser
            if v and v[0].islower():
                v = v[0].upper() + v[1:]
            return v

        def _truncate(text: str, max_words: int = 6) -> str:
            """Tronquer un texte a max_words mots."""
            words = text.split()
            if len(words) <= max_words:
                return text
            return " ".join(words[:max_words])

        def _parse_option(raw: dict) -> AnalyseOption:
            # L'IA retourne impact_jours (en jours ou heures selon le cadre)
            # On convertit en % via la formule inverse : delta_jours → delta_%
            impact_jours_raw = float(raw.get("impact_jours", raw.get("impact_probabilite", 0.0)))

            # Pour cadres courts (≤7j), l'IA retourne des heures → convertir en jours
            if impact_temporel_jours is not None and impact_temporel_jours <= 7:
                impact_jours_val = impact_jours_raw / 24.0  # heures → jours
            else:
                impact_jours_val = impact_jours_raw  # déjà en jours

            # Convertir jours → % via la formule : prob_apres = f(temps_avant - delta)
            # temps_avant = _tj jours, temps_apres = _tj - impact_jours
            temps_apres = max(1, _tj - impact_jours_val)
            # Formule inverse de dureeFromProb : prob = 100 / (1 + (temps/900)^(1/0.675))
            prob_apres = 100.0 / (1.0 + (temps_apres / 900.0) ** (1.0 / 0.675))
            impact_pct = prob_apres - prob_totale

            return AnalyseOption(
                pros=[_truncate(p) for p in raw.get("pros", [])],
                cons=[_truncate(c) for c in raw.get("cons", [])],
                impact_probabilite=round(impact_pct, 4),
                resume=_truncate(raw.get("resume", ""), 8),
            )

        parsed_options = []
        for l in lettres:
            key = f"option_{l.lower()}"
            raw = data.get(key, {})
            parsed_options.append(_parse_option(raw))

        return AnalyseDilemme(
            options=parsed_options,
            verdict=_clean_verdict(data.get('verdict', '')),
            option_recommandee=data.get("option_recommandee", lettres[0]),
            etude_scientifique=data.get("etude_scientifique", ""),
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
