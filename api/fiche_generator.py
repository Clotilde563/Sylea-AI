"""
Generation de fiche de cours (Sprint 3 Ecoute active — etudiants univ/prepa).

Prend un transcript brut produit par faster-whisper et genere une fiche
structuree en markdown (avec LaTeX pour les maths/physique).

Architecture :
  1. Auto-detection de la matiere (heuristique mots-cles + override user)
  2. Selection du template approprie selon (matiere, formation)
  3. Appel Claude API avec prompt specialise -> markdown structuree
  4. Fallback heuristique si pas de cle API (extraction brute paragraphes)

6 matieres + auto :
  maths     : titres / definitions / theoremes / demonstrations / exemples
  physique  : phenomene / loi (LaTeX) / experience / formules / applications
  philo     : these / arguments / objections / references / synthese
  ses       : concept / mecanismes / acteurs / chiffres / debat
  anglais   : key vocabulary / grammar points / quotes / cultural notes
  histoire  : chronologie / acteurs / causes / consequences / sources
  autre     : structure generique adaptive (LLM choisit)
"""

from __future__ import annotations

import os
import re
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
#  Auto-detection matiere
# ════════════════════════════════════════════════════════════════════════════

# Indices linguistiques par matiere (ponderes). On scanne le transcript
# tronque (1ers 3000 chars suffisent — le prof annonce le plan en intro).
# Matche en lowercase, avec word boundaries pour eviter les faux positifs
# (ex: "loi" matche "loi" mais pas "emploi").
_KEYWORDS = {
    "maths": [
        ("theoreme", 3), ("démonstration", 3), ("demonstration", 3),
        ("corollaire", 3), ("lemme", 3), ("hypothese", 1), ("hypothèse", 1),
        ("equation", 2), ("équation", 2), ("integrale", 2), ("intégrale", 2),
        ("derivee", 2), ("dérivée", 2), ("derivable", 2), ("dérivable", 2),
        ("matrice", 2), ("vecteur", 2), ("espace vectoriel", 3),
        ("application linéaire", 3), ("limite", 1), ("continue", 1),
        ("fonction", 1), ("ensemble", 1), ("borne", 1),
    ],
    "physique": [
        ("force", 2), ("energie", 2), ("énergie", 2), ("vitesse", 1),
        ("acceleration", 2), ("accélération", 2), ("masse", 1),
        ("electrique", 2), ("électrique", 2), ("magnetique", 2), ("magnétique", 2),
        ("circuit", 2), ("courant", 2), ("tension", 2), ("resistance", 1),
        ("résistance", 1), ("onde", 2), ("frequence", 2), ("fréquence", 2),
        ("optique", 2), ("thermodynamique", 3), ("loi de", 2),
        ("newton", 2), ("joule", 2), ("ohm", 2),
    ],
    "philo": [
        ("these", 2), ("thèse", 2), ("antithèse", 3), ("antithese", 3),
        ("synthese", 2), ("synthèse", 2), ("dialectique", 3),
        ("conscience", 2), ("liberte", 2), ("liberté", 2),
        ("verite", 2), ("vérité", 2), ("morale", 2), ("ethique", 2), ("éthique", 2),
        ("kant", 2), ("hegel", 2), ("nietzsche", 2), ("descartes", 2),
        ("aristote", 2), ("platon", 2), ("sartre", 2), ("rousseau", 2),
        ("argument", 1), ("paradoxe", 2), ("metaphysique", 3), ("métaphysique", 3),
    ],
    "ses": [
        ("economie", 2), ("économie", 2), ("marche", 1), ("marché", 1),
        ("offre", 1), ("demande", 1), ("inflation", 2), ("chomage", 2), ("chômage", 2),
        ("pib", 2), ("croissance", 2), ("salariat", 2), ("classe sociale", 3),
        ("durkheim", 2), ("weber", 2), ("bourdieu", 2), ("marx", 2),
        ("socialisation", 3), ("mobilite sociale", 3), ("mobilité sociale", 3),
        ("integration", 2), ("intégration", 2), ("politique publique", 3),
    ],
    "anglais": [
        ("the", 0.3), ("english", 1), ("vocabulary", 2), ("grammar", 2),
        ("phrasal verb", 3), ("present perfect", 3), ("past tense", 2),
        ("idiom", 2), ("collocation", 2),
        ("shakespeare", 2), ("victorian", 2), ("brexit", 2),
        # Note : si le transcript est en anglais, _detect_matiere fonctionnera
        # surtout via la langue detectee Whisper plutot que ces mots-cles.
    ],
    "histoire": [
        ("guerre", 2), ("revolution", 2), ("révolution", 2), ("siecle", 1), ("siècle", 1),
        ("monarchie", 2), ("republique", 2), ("république", 2),
        ("napoleon", 2), ("napoléon", 2), ("louis", 1), ("traite de", 2), ("traité de", 2),
        ("empire", 2), ("nazi", 2), ("seconde guerre mondiale", 4),
        ("premiere guerre mondiale", 4), ("première guerre mondiale", 4),
        ("decolonisation", 3), ("décolonisation", 3),
        ("guerre froide", 3), ("regime", 1), ("régime", 1),
    ],
}


def detect_matiere(transcript: str, language: Optional[str] = None) -> str:
    """Renvoie l'id de matiere detecte parmi les 6, ou 'autre' si rien
    de net. Override par language='en' -> anglais direct (cours d'anglais
    transcrits en anglais sont obvious)."""
    if language and language.lower().startswith("en"):
        return "anglais"

    text_lc = transcript.lower()[:3000]
    if not text_lc.strip():
        return "autre"

    scores: dict[str, float] = {m: 0.0 for m in _KEYWORDS}
    for matiere, kw_list in _KEYWORDS.items():
        for kw, weight in kw_list:
            # word boundary match pour eviter "the" dans "theme"
            pattern = r"\b" + re.escape(kw) + r"\b"
            count = len(re.findall(pattern, text_lc))
            scores[matiere] += count * weight

    best, best_score = max(scores.items(), key=lambda kv: kv[1])
    # Seuil : il faut au moins 3 points pour eviter les faux positifs sur
    # des transcripts courts ou off-topic.
    if best_score < 3.0:
        return "autre"
    return best


# ════════════════════════════════════════════════════════════════════════════
#  Templates (system prompts) par matiere
# ════════════════════════════════════════════════════════════════════════════

# Tronc commun pour toutes les matieres
_BASE_INSTRUCTIONS = """Tu es un assistant pedagogique expert qui transforme un transcript de cours
universitaire/prepa en une fiche structuree de qualite.

REGLES STRICTES :
- Reponds UNIQUEMENT en markdown. Pas de prefixe ni d'explication meta.
- N'INVENTE rien : si le transcript ne couvre pas un point, omets-le.
- Conserve les formules mathematiques en LaTeX delimite par $...$ (inline)
  ou $$...$$ (display). Convertis les expressions parlees ("racine de x")
  en LaTeX propre ("$\\sqrt{x}$").
- Cite les noms propres et dates exactement comme dans le transcript.
- Sois CONCIS : une fiche prepa fait 1-2 pages, pas 10. Garde l'essentiel.
- Si le prof a fait une digression, ignore-la.
- Si une partie du transcript est inaudible/incomprehensible, ne tente pas
  de la reformuler.

FORMAT GENERAL :
- Titre H1 du cours
- Sections H2 selon la structure de la matiere
- Bullets pour les listes
- **Gras** pour les termes-cle
- Blockquote pour les citations
"""

# Templates par matiere (ajoute apres _BASE_INSTRUCTIONS)
_MATIERE_TEMPLATES: dict[str, str] = {
    "maths": """STRUCTURE MATHEMATIQUES :

# {{titre}}

## Cadre / Hypotheses
Les conditions sous lesquelles le cours se place.

## Definitions
- **terme** : definition formelle.

## Theoremes / Propositions
> **Theoreme N** (Nom si fourni) — Enonce.

## Demonstrations
Pour chaque preuve abordee, donne les ETAPES en bullet list (pas la prose
complete) avec les arguments-cle. Les calculs intermediaires en LaTeX.

## Exemples
Cas concrets traites en cours.

## A retenir
3-5 points cles non negociables pour les colles/DS.
""",

    "physique": """STRUCTURE PHYSIQUE-CHIMIE :

# {{titre}}

## Phenomene etudie
Description qualitative.

## Lois et formules
- **Loi de X** : enonce + formule LaTeX. Unites SI explicites.
$$F = m \\cdot a$$

## Hypotheses du modele
Les approximations / cadre de validite.

## Demonstrations / Derivations
Etapes formelles.

## Experiences / Applications
Cas concrets, ordres de grandeur.

## A retenir
Formules a connaitre par cœur + pieges classiques.
""",

    "philo": """STRUCTURE PHILOSOPHIE :

# {{titre}}

## Probleme pose
La question centrale, formulee en une phrase.

## Thèse
Position defendue + argument principal.

## Arguments
1. **Argument 1** — formulation + reference (auteur/oeuvre si cite).
2. **Argument 2** — ...

## Objections / Antithèse
Contre-arguments evoques.

## Synthese / Depassement
Si le prof a propose une voie de depassement.

## References
- Auteur, Œuvre, citation cle (en blockquote).

## A retenir
Definition des concepts-cle + thèse en 1 phrase.
""",

    "ses": """STRUCTURE SCIENCES ECONOMIQUES ET SOCIALES :

# {{titre}}

## Concept / Probleme
Definition + enjeu.

## Mecanismes
Comment ca fonctionne (causes -> effets).

## Acteurs
Qui est implique (entreprises, Etat, menages, etc.).

## Donnees / Chiffres
Statistiques ou ordres de grandeur cites.

## Auteurs / Theories
- **Auteur** : these principale.

## Debats / Limites
Critiques ou points de tension.

## A retenir
Concepts-cle + 1-2 chiffres significatifs.
""",

    "anglais": """STRUCTURE ANGLAIS / LV :

# {{titre}}

## Topic / Theme
Sujet du cours.

## Key vocabulary
- **word** : translation + collocation/example.

## Grammar points
- Rule + example.

## Quotes / Excerpts
> Cited passage (in original language).

## Cultural / Historical context
Background information mentionned.

## To remember
3-5 essential points.
""",

    "histoire": """STRUCTURE HISTOIRE-GEO :

# {{titre}}

## Cadre chronologique
Periode + dates-cles.

## Acteurs
- **Personnage / Pays / Organisation** : role.

## Causes
1. Cause 1.
2. Cause 2.

## Deroulement
Sequence des evenements (chronologique, bullet list).

## Consequences
Court terme / long terme.

## Sources / Historiographie
Si discutees en cours.

## A retenir
Dates + acteurs cles + 1 idee directrice.
""",

    "autre": """STRUCTURE GENERIQUE :

# {{titre}}

## Introduction / Probleme
Sujet du cours.

## Notions-cle
- **terme** : definition.

## Developpement
Bullets ou paragraphes selon la nature du contenu.

## Exemples / Illustrations
Si pertinent.

## A retenir
3-5 points essentiels.
""",
}


def _build_system_prompt(matiere: str, formation: Optional[str]) -> str:
    template = _MATIERE_TEMPLATES.get(matiere, _MATIERE_TEMPLATES["autre"])
    base = _BASE_INSTRUCTIONS + "\n\n" + template
    if formation:
        base += f"\n\nFORMATION : {formation}. Adapte le niveau de detail au programme officiel."
    return base


# ════════════════════════════════════════════════════════════════════════════
#  Generation
# ════════════════════════════════════════════════════════════════════════════

def generate_fiche(
    transcript: str,
    matiere: Optional[str] = None,
    titre: Optional[str] = None,
    formation: Optional[str] = None,
    language: Optional[str] = None,
    *,
    _client_factory=None,  # injection pour tests
) -> dict:
    """Genere une fiche markdown a partir du transcript.

    Args:
        transcript     : texte brut concatene de tous les chunks transcrits.
        matiere        : id parmi les 6 (maths/physique/philo/ses/anglais/
                         histoire) ou None pour auto-detect.
        titre          : titre du cours (fournis par l'user pre-flight).
        formation      : MPSI / ECG / etc.
        language       : "fr" / "en" — guide la detection.
        _client_factory: callable optionnel pour injecter un mock anthropic
                         client dans les tests.

    Returns:
        {
            "matiere": str,            # detecte ou fourni
            "matiere_auto_detected": bool,
            "fiche_markdown": str,
            "fallback_used": bool,     # True si LLM indispo (pas de cle API)
        }
    """
    # 1. Resoud la matiere
    matiere_auto = False
    if not matiere or matiere == "autre":
        detected = detect_matiere(transcript, language)
        if detected != "autre":
            matiere = detected
            matiere_auto = True
        elif not matiere:
            matiere = "autre"

    # 2. Build prompt
    titre = titre or "Cours"
    system_prompt = _build_system_prompt(matiere, formation)
    user_message = (
        f"Voici le transcript brut du cours (titre fourni : {titre!r}). "
        f"Genere la fiche structuree en markdown selon le format demande.\n\n"
        f"--- TRANSCRIPT ---\n{transcript}\n--- FIN TRANSCRIPT ---"
    )

    # 3. Appel LLM
    fiche_md, fallback_used = _call_llm(system_prompt, user_message, titre, _client_factory)

    return {
        "matiere": matiere,
        "matiere_auto_detected": matiere_auto,
        "fiche_markdown": fiche_md,
        "fallback_used": fallback_used,
    }


def _call_llm(
    system_prompt: str,
    user_message: str,
    titre: str,
    client_factory=None,
) -> tuple[str, bool]:
    """Appelle Claude (sync, model haiku par default car la fiche est un
    one-shot court). Retourne (markdown, fallback_used)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and client_factory is None:
        return _fallback_fiche(user_message, titre), True

    try:
        if client_factory is not None:
            client = client_factory()
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("FICHE_MODEL", "claude-haiku-4-5")
        msg = client.messages.create(
            model=model,
            max_tokens=2500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        # SDK v0.34+ : msg.content est une liste de blocks (TextBlock)
        parts = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        markdown = "".join(parts).strip()
        if not markdown:
            return _fallback_fiche(user_message, titre), True
        return markdown, False
    except Exception:
        return _fallback_fiche(user_message, titre), True


def generate_anki_cards(
    transcript: str,
    matiere: str,
    titre: str | None = None,
    formation: str | None = None,
    *,
    _client_factory=None,  # injection pour tests
) -> dict:
    """Genere une liste de cartes Anki Q/R a partir du transcript brut.

    Approche LLM : on demande directement a Claude de produire des paires
    {q, a} pertinentes pour la revision (definitions, dates, formules,
    causes/consequences, etc.) — bien plus pertinent que l'extraction
    heuristique sur la fiche markdown qui peut produire des paires
    antinomiques.

    Returns {cards: [{q, a}], used_llm: bool, error: str | None}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and _client_factory is None:
        return {"cards": [], "used_llm": False, "error": "no_api_key"}

    matiere_hint = {
        "maths":    "definitions, theoremes (enonce + condition), formules, contre-exemples",
        "physique": "lois (formule LaTeX + unites SI), ordres de grandeur, definitions, conditions",
        "philo":    "definitions des concepts, theses des auteurs (auteur -> these), citations attribuees, distinctions cle",
        "ses":      "definitions, mecanismes (cause -> effet), auteurs/theories, chiffres marquants",
        "anglais":  "vocabulary (word -> meaning), grammar rules, key quotes, idioms",
        "histoire": "dates + evenements, acteurs (personnage -> role), causes, consequences",
        "autre":    "definitions, faits cles, dates, noms propres, enchainements logiques",
    }.get(matiere, "definitions, faits cles, dates, noms propres")

    system_prompt = f"""Tu es un assistant pedagogique qui prepare des FLASHCARDS ANKI
pour un etudiant de prepa/universite a partir d'un transcript de cours.

PRIORITE ABSOLUE : QUALITE > QUANTITE.
Mieux vaut 5 cartes excellentes que 30 cartes mediocres.

VOLUME : entre 5 et 50 cartes selon le contenu reel du transcript.
Adapte au contenu :
  - Transcript pauvre (digressions, repetitions, peu de notions) : 5-10
  - Transcript dense (cours magistral structure)                 : 15-30
  - Transcript tres dense / long > 1h sur sujet technique       : 30-50
NE remplis JAMAIS pour atteindre un quota — si le contenu n'est pas la,
ne fabrique pas.

CHASSE AUX CARTES (par matiere {matiere}) : {matiere_hint}.

Pour chaque concept REELLEMENT couvert dans le transcript :
  1. Definition formelle a memoriser ?              -> 1 carte
  2. Formule, loi, date, nom propre ?               -> 1 carte
  3. Cause/consequence, mecanisme explique ?        -> 1 carte
  4. Distinction explicite entre 2 notions ?        -> 1 carte par notion
  5. Exemple cle / contre-exemple instructif ?      -> 1 carte
  6. Etape d'un raisonnement / demonstration ?      -> 1 carte par etape

CRITERES QUALITE (chaque carte doit cocher tout) :
  [✓] Question PRECISE et FERMEE (UNE bonne reponse, pas ouverte).
  [✓] Reponse CONCISE (1-3 phrases), substantielle (pas un seul mot).
  [✓] INDEPENDANTE et revisable seule (pas de "comme vu plus haut").
  [✓] Information NON-triviale et NON-tautologique
      (pas de "Qu'est-ce qu'une definition ?" ou "X = X").
  [✓] Information PRESENTE litteralement dans le transcript
      (n'invente pas, ne devine pas).

CONSERVATION :
- LaTeX en $...$ pour les formules / equations.
- Citations en italiques avec auteur entre parentheses si applicable.
- Termes techniques exactement comme prononces dans le cours.

FORMAT DE SORTIE STRICT :
Tu reponds UNIQUEMENT avec un objet JSON valide, sans texte avant/apres :
{{"cards": [{{"q": "...", "a": "..."}}, ...]}}
"""

    user_message = (
        f"Voici le transcript brut d'un cours{' de ' + matiere if matiere != 'autre' else ''}"
        f"{' (formation: ' + formation + ')' if formation else ''}"
        f"{', titre: ' + repr(titre) if titre else ''}.\n"
        f"Genere les flashcards Anki au format JSON.\n\n"
        f"--- TRANSCRIPT ---\n{transcript}\n--- FIN TRANSCRIPT ---"
    )

    try:
        if _client_factory is not None:
            client = _client_factory()
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("FICHE_MODEL", "claude-haiku-4-5")
        msg = client.messages.create(
            model=model,
            max_tokens=2500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        parts = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        raw = "".join(parts).strip()
        # Strip markdown code fence si Claude le wrappe
        raw = re.sub(r"^```(?:json)?\s*\n", "", raw)
        raw = re.sub(r"\n```\s*$", "", raw)
        import json
        parsed = json.loads(raw)
        cards = parsed.get("cards", [])
        # Sanitise
        clean: list[dict] = []
        for c in cards:
            q = (c.get("q") or "").strip()
            a = (c.get("a") or "").strip()
            if q and a and len(q) <= 200 and len(a) <= 800:
                clean.append({"q": q, "a": a})
        # Cap a 50 cartes (max accepte par le prompt). Garde le minimum
        # implicite a 5 — si le LLM en retourne moins, on accepte tel quel
        # (cours pauvre en contenu).
        return {"cards": clean[:50], "used_llm": True, "error": None}
    except Exception as e:
        return {"cards": [], "used_llm": False, "error": f"llm_failed: {e}"}


def _fallback_fiche(user_message: str, titre: str) -> str:
    """Fallback deterministe sans LLM : extrait juste les premiers paragraphes
    du transcript et formate avec une structure minimale. Permet de garder
    l'app fonctionnelle meme sans cle API (mode degrade)."""
    # Extrait le transcript (entre les marqueurs)
    m = re.search(r"--- TRANSCRIPT ---\n(.*?)\n--- FIN TRANSCRIPT ---", user_message, re.S)
    transcript = m.group(1).strip() if m else user_message

    # Decoupe en paragraphes naïfs (par phrases regroupees)
    sentences = re.split(r"(?<=[.!?])\s+", transcript)
    # Groupe par 3-4 phrases pour faire des "paragraphes"
    paragraphs = []
    buf = []
    for s in sentences:
        buf.append(s.strip())
        if len(buf) >= 3:
            paragraphs.append(" ".join(buf))
            buf = []
    if buf:
        paragraphs.append(" ".join(buf))

    out = [f"# {titre}", ""]
    out.append("> ⚠ Fiche generee en mode degrade (LLM indisponible). "
               "Le contenu ci-dessous est l'extraction brute du transcript. "
               "Active la cle API pour avoir une vraie fiche structuree.")
    out.append("")
    out.append("## Transcript brut (par paragraphes)")
    out.append("")
    for i, p in enumerate(paragraphs[:50], 1):
        if not p:
            continue
        out.append(f"**§{i}.** {p}")
        out.append("")
    return "\n".join(out)
