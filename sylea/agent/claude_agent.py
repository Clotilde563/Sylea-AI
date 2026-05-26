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


# ── Helper : parser JSON robuste ──────────────────────────────────────────────
#
# Claude renvoie parfois du JSON casse :
#   - Wrapping markdown (```json ... ```)
#   - Smart quotes (« » " ") au lieu des straight quotes
#   - Trailing commas dans objets/arrays
#   - Newlines non-echappes dans les string values
#   - Texte explicatif avant/apres le JSON
# Cette fonction tente plusieurs strategies de reparation. Retourne None
# si aucune ne marche (le caller decidera quoi faire : retry, fallback, etc.).

def _try_parse_json_robust(content: str) -> dict | None:
    """Tente de parser le JSON de la reponse Claude avec plusieurs strategies.
    Retourne le dict parse ou None si echec total."""
    if not content or not content.strip():
        return None

    # Strategie 1 : strip markdown code blocks
    cleaned = content.strip()
    # Retire ```json ... ``` ou ``` ... ```
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    cleaned = cleaned.strip()

    # Strategie 2 : normalise les smart quotes (peuvent venir d'un copier-coller
    # ou d'un LLM qui auto-corrige le francais).
    smart_quote_map = {
        '“': '"', '”': '"',  # double smart quotes
        '‘': "'", '’': "'",  # single smart quotes
        '«': '"', '»': '"',  # french guillemets
        '…': '...',  # ellipsis
    }
    for smart, straight in smart_quote_map.items():
        cleaned = cleaned.replace(smart, straight)

    # Strategie 3 : extraire le block JSON (entre { ... }) si du texte
    # entoure encore
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not json_match:
        return None
    raw = json_match.group()

    # Strategie 4 : trailing commas
    raw_no_trail = re.sub(r',\s*}', '}', raw)
    raw_no_trail = re.sub(r',\s*]', ']', raw_no_trail)

    # 1ere tentative : tel quel
    try:
        return json.loads(raw_no_trail)
    except json.JSONDecodeError:
        pass

    # Strategie 5 : echapper les newlines bruts DANS les string values.
    # Erreur frequente de Claude : il met des vrais \n au lieu de \\n.
    # On detecte les strings via regex tres approximative et on echappe.
    try:
        # Approche simple : remplace les \n et \r dans les valeurs string.
        # On parcourt char par char en tracking si on est dans une string.
        escaped = []
        in_string = False
        prev = ''
        for ch in raw_no_trail:
            if ch == '"' and prev != '\\':
                in_string = not in_string
            if in_string and ch == '\n':
                escaped.append('\\n')
            elif in_string and ch == '\r':
                escaped.append('\\r')
            elif in_string and ch == '\t':
                escaped.append('\\t')
            else:
                escaped.append(ch)
            prev = ch
        repaired = ''.join(escaped)
        return json.loads(repaired)
    except (json.JSONDecodeError, Exception):
        pass

    # Strategie 6 : derniere chance — tente d'extraire le plus grand prefixe
    # parsable (pour gerer un JSON tronque). On reduit progressivement la
    # chaine et on rajoute les fermetures `}` manquantes.
    for cut in range(len(raw_no_trail), max(50, len(raw_no_trail) // 2), -50):
        partial = raw_no_trail[:cut]
        # Compte les accolades ouvertes
        opens = partial.count('{') - partial.count('}')
        opens_arr = partial.count('[') - partial.count(']')
        if opens > 0 or opens_arr > 0:
            partial += ']' * opens_arr + '}' * opens
        try:
            return json.loads(partial)
        except json.JSONDecodeError:
            continue

    return None


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
    impact_jours_brut: float = 0.0  # impact en jours brut (avant conversion en %)


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
        full_context: str = "",
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
        # Use full_context if provided, otherwise fall back to _resumer_profil
        profil_resume = full_context if full_context else self._resumer_profil(profil)

        # Inclure l'objectif complet (avec le contexte Q&A s'il existe)
        objectif_desc = profil.objectif.description if profil.objectif else "Non défini"
        # Indication si du contexte personnalisé est disponible
        a_contexte_qa = "--- Contexte personnalisé ---" in objectif_desc

        prompt = f"""Analyse le profil suivant pour son objectif de vie et fournis une analyse qualitative approfondie.

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
        collected_context: str = "",
        full_context: str = "",
    ) -> AnalyseDilemme:
        """
        Analyse un dilemme entre N options et calcule l'impact sur la probabilité.

        Args:
            profil    : Profil complet de l'utilisateur
            question  : La question posée par l'utilisateur
            options   : Liste des descriptions d'options (2 à 5)
            collected_context : Infos collectées par l'agent sur l'utilisateur

        Returns:
            AnalyseDilemme avec pros/cons et impact pour chaque option
        """
        # Use full_context if provided, otherwise fall back to _resumer_profil
        profil_resume = full_context if full_context else self._resumer_profil(profil)
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


        # Contexte temporel pour l'IA.
        # L'unite et les EXEMPLES de calibration sont critiques : ils guident
        # Claude sur l'ordre de grandeur attendu. La regle d'or :
        #   plus le cadre est LONG, plus l'impact peut etre GROS pour les
        #   choix qui sont au coeur de l'objectif de vie.
        # Calibration : pour une decision PARFAITEMENT alignee avec l'objectif
        # et un investissement TOTAL du cadre temporel, l'impact peut atteindre
        # ~30-50% du cadre. Pour une decision totalement HORS-SUJET, l'impact
        # peut etre tres negatif (~50% du cadre). Les decisions tiedes restent
        # dans ~5-15% du cadre.
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
                # Pour 1 mois : un choix tres aligne peut faire gagner 10-15j,
                # un choix tres mauvais peut faire perdre 10-15j.
                unite_impact = "jours (ex: choix tres aligne objectif = +10 a +15j; choix neutre = ±3j; choix hors-sujet majeur = -10 a -15j)"
            elif cadre_jours <= 365:
                cadre_str = f"~{cadre_jours // 30} mois ({cadre_jours} jours)"
                # CALIBRATION CRITIQUE pour 1 an : un engagement d'1 ANNEE entiere
                # sur une activite directement alignee avec l'objectif de vie
                # peut accelerer l'atteinte de l'objectif de ~100 a 200 jours.
                # Une annee perdue sur du hors-sujet = -100 a -300j.
                # Les decisions tiedes (impact secondaire) restent dans ±20-50j.
                unite_impact = (
                    "jours. CALIBRATION :\n"
                    "  - Engagement d'1 AN TOTAL sur une activite au COEUR de l'objectif = +100 a +200j\n"
                    "  - Choix neutre / impact secondaire = ±20 a ±50j\n"
                    "  - Choix HORS-SUJET majeur (perte de temps) = -100 a -200j\n"
                    "  - Choix DESTRUCTEUR (sabotage de l'objectif) = jusqu'a -300j\n"
                    "  Exemple concret : pour un objectif freelance dev, apprendre l'anglais"
                    " (langue tech universelle, marche x4) sur 1 an = +120 a +180j. "
                    "Apprendre l'italien (zero valeur tech freelance) sur 1 an = -80 a -150j."
                )
            else:
                cadre_str = f"TOUTE LA DUREE DE L'OBJECTIF ({temps_estime_str}, soit {_tj} jours)"
                # Long terme = cadre = duree totale objectif. L'impact peut atteindre
                # 30-50% du cadre pour les choix transformationnels.
                unite_impact = (
                    "jours. CALIBRATION LONG TERME :\n"
                    "  - Choix transformationnel aligne objectif = +30 a +50% du cadre\n"
                    "  - Choix tiede = ±5 a ±15% du cadre\n"
                    "  - Choix destructeur = jusqu'a -50% du cadre\n"
                    f"  Pour ce cadre de {_tj}j, ca donne :\n"
                    f"    Aligne fort = +{_tj // 3} a +{_tj // 2}j\n"
                    f"    Hors-sujet = -{_tj // 4} a -{_tj // 2}j"
                )
        else:
            cadre_jours = _tj
            cadre_str = f"TOUTE LA DUREE DE L'OBJECTIF ({temps_estime_str}, soit {_tj} jours)"
            unite_impact = f"jours. Calibration : impact transformationnel = ±{_tj // 3} a ±{_tj // 2}j, choix neutre = ±{_tj // 10}j"

        prompt = f"""Tu es un robot probabiliste froid et factuel. Tu analyses un dilemme de vie.
ZERO emotion, ZERO encouragement. Tu raisonnes en TEMPS, pas en pourcentage.

PROFIL RESUME :
{profil_resume}
{device_context}
{collected_context}

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
4. REGLE CRITIQUE : Chaque option DOIT avoir un impact DIFFERENT et NON NUL.
   Meme si l'impact est minime, il existe toujours une difference entre deux choix.
   Si les deux options sont mauvaises, les deux impacts peuvent etre NEGATIFS.
   Si les deux options sont bonnes, les deux impacts peuvent etre POSITIFS mais differents.
   JAMAIS 0 pour les deux options. JAMAIS le meme impact pour deux options differentes.
5. Exemples concrets pour un cadre de 1 jour :
   - Soiree avec un ami motivant = +0.5h (energie positive le lendemain)
   - Soiree avec un ami demotivant = -1.5h (energie drainee, perte de focus le lendemain)
   - Dormir 8h au lieu de coder = +2.0 (heures de productivite gagnees)
   - Aller courir 1h = +0.5 (heures de clarte mentale gagnees)
6. Exemples concrets pour un cadre de 1 mois :
   - Apprendre l'anglais vs l'espagnol pour freelance dev = anglais +12 a +18j / espagnol +2 a +5j
   - Aller au gym 5x/sem vs rester sedentaire = +5j / -8j (sante & focus)
7. Exemples concrets pour un cadre de 1 AN (CRITIQUE — l'engagement est massif) :
   - Apprendre l'anglais 1 an pour freelance dev (langue tech universelle) = +120 a +180j
   - Apprendre l'italien 1 an pour freelance dev (zero valeur tech) = -80 a -150j (1 an perdu)
   - Faire un MBA 1 an si pertinent metier = +100 a +200j
   - Passer 1 an a regarder Netflix au lieu de bosser objectif = -200 a -350j
   - Aller au gym regulierement 1 an = +40 a +60j (sante & energie boostees)
   IMPORTANT : pour 1 AN, n'aie PAS PEUR des grands chiffres. Un an
   d'engagement total = transformation reelle de la trajectoire de vie.
8. Sois REALISTE et FACTUEL. Pas d'impact par encouragement.
9. CALIBRE l'amplitude en fonction de l'ALIGNEMENT avec l'objectif :
   - Au coeur de l'objectif + bon timing = magnitude haute (haut de la
     fourchette donnee dans `unite_impact`)
   - Tangentiel a l'objectif = magnitude moyenne
   - Hors-sujet = magnitude tres negative

REGLE CRITIQUE POUR LES IMPACTS COURTS (1 jour, 1 semaine) :
- Il DOIT y avoir une DIFFERENCE d'impact entre les options. Jamais 0 pour les deux.
- Pour un cadre de 1 jour (24h), exprime l'impact en HEURES et FRACTIONS D'HEURES.
  Exemple : si une option fait gagner 2h de productivite, impact_jours = 0.083 (2h/24h)
- Pour un cadre de 1 semaine, exprime en jours et fractions.
- L'option recommandee DOIT avoir un meilleur impact que les autres.
- Si les deux options sont mauvaises, les deux impacts sont negatifs mais differents.

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
                impact_jours_brut=round(impact_jours_val, 6),
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
        Appelle l'API Claude et parse la reponse JSON.

        Strategie defensive : si le JSON est mal forme, on tente plusieurs
        reparations (trailing commas, smart quotes, markdown blocks, newlines
        non-echappes dans strings) avant d'abandonner. En dernier recours,
        on retry une fois avec une instruction explicite "JSON UNIQUEMENT".

        Raises:
            ValueError: si la reponse n'est pas du JSON valide apres tous les retries
            anthropic.APIError: si l'appel API echoue
        """
        message = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text.strip()
        parsed = _try_parse_json_robust(content)
        if parsed is not None:
            return parsed

        # Retry une fois avec instruction explicite "JSON ONLY"
        import logging as _lg
        _lg.getLogger("sylea.claude").warning(
            "[claude_agent] JSON invalide a la 1ere tentative, retry avec instruction stricte. "
            "Reponse initiale (200 chars) : %s",
            content[:200],
        )

        retry_prompt = (
            prompt
            + "\n\nIMPORTANT : Reponds UNIQUEMENT en JSON valide. "
            + "Aucun texte avant ni apres. Aucun bloc markdown. "
            + "Toute valeur de string doit echapper les guillemets internes et "
            + "remplacer les retours a la ligne par \\n."
        )
        message2 = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": retry_prompt}],
        )
        content2 = message2.content[0].text.strip()
        parsed2 = _try_parse_json_robust(content2)
        if parsed2 is not None:
            return parsed2

        raise ValueError(
            f"JSON invalide dans la reponse Claude apres retry. "
            f"Debut de la 2e reponse : {content2[:200]}"
        )
