"""
Agent 3 — Grounding anti-hallucination.

Objectif : reduire drastiquement les hallucinations sur faits.

Strategie en 3 couches :

**COUCHE 1 — Prompting (preventif)**
System prompt enrichi avec regles strictes :
  - "Si incertain, dis 'je ne sais pas' au lieu d'inventer"
  - "Cite tes sources [1], [2] pour TOUT fait factuel"
  - "Utilise des verbes d'incertitude : 'semble', 'selon X', 'il se peut'"

**COUCHE 2 — Detection (post-generation)**
`extract_factual_claims(text)` detecte les affirmations susceptibles d'etre hallucinees :
  - Dates specifiques (annees, "le 15 mars 2024")
  - Chiffres precis (statistiques, montants, pourcentages)
  - Noms propres (personnes, entreprises, produits)
  - Citations directes ("X a dit que...")

**COUCHE 3 — Verification (actif)**
`ground_response(draft, db, user_id, client)` :
  - Passe les claims extraits a Haiku pour rating confiance (0-1)
  - Claims low-confidence sans source citee -> hedged ou flagges
  - Retourne draft modifie + liste de claims non-groundes pour transparence

Usage :
    from api.agent3_grounding import ground_response
    result = await ground_response(draft, client, db=db, user_id=uid)
    # result = {grounded_text, unverified_claims: [...], changed: bool}

Performance : +1 appel Haiku (~$0.001) par reponse longue. Skip si < 200 chars.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("sylea.grounding")


# ─────────────────────────────────────────────────────────────────────────────
# Prompting (COUCHE 1) : bloc a ajouter au system prompt
# ─────────────────────────────────────────────────────────────────────────────

GROUNDING_PROMPT_BLOCK = """
=== ANTI-HALLUCINATION (critique) ===

REGLES ABSOLUES sur les faits :
1. **Si tu n'es pas SUR a 100% d'un fait, DIS-LE**. Exemples :
   - "Je crois que X, mais a verifier" ✓
   - "Selon mes connaissances (potentiellement datees), X" ✓
   - "Je ne suis pas certain" ✓
   - "X vaut 42" SANS source si tu hesites ✗

2. **CITE SYSTEMATIQUEMENT tes sources** pour :
   - Dates precises (annees, dates exactes)
   - Chiffres (statistiques, montants, pourcentages)
   - Citations directes ("X a dit que...")
   - Faits historiques specifiques
   - Specifications techniques (versions, specs produits)

   Format : "[selon Wikipedia, consulte le X]" ou "[source : bloomberg.com/..]"

3. **Si un fait necessite verification recente, UTILISE `search` ou `web_fetch`**
   avant de repondre. Ne te fie pas a tes connaissances internes pour :
   - Prix actuels
   - Personnes en poste / positions actuelles
   - Versions software/hardware
   - Actualites < 6 mois

4. **Prefere les hedges (adoucisseurs)** :
   "semble", "d'apres", "selon", "il se peut que", "approximativement"
   aux affirmations categoriques non-sourcees.

5. **JAMAIS inventer** :
   - URL
   - Reference bibliographique
   - Citation entre guillemets
   - Statistique precise
   - Nom de personne en poste

Si tu te surprends a vouloir inventer → STOP, reformule en "je ne sais pas precisement, veux-tu que je cherche ?"
"""


# ─────────────────────────────────────────────────────────────────────────────
# Detection (COUCHE 2) : extraction des claims factuels
# ─────────────────────────────────────────────────────────────────────────────

# Patterns regex qui capturent des affirmations factuelles susceptibles
# d'etre hallucinees.
_CLAIM_PATTERNS = [
    # Annees specifiques : "en 2024", "depuis 1995"
    (r"\b(?:en|depuis|jusqu'en|vers|avant|apres)\s+(\d{4})\b", "date_year"),
    # Dates completes : "le 15 mars 2024"
    (r"\ble\s+\d{1,2}\s+(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s+\d{4}\b", "date_full"),
    # Grands chiffres : "$42 milliards", "12.5 millions"
    (r"\b\d+(?:[.,]\d+)?\s*(?:milliards?|millions?|milliers?|MB?|GB?|TB?|KB?|billion|million)\b", "large_number"),
    # Pourcentages specifiques (pas de \b apres % car % est non-word)
    (r"\b\d+(?:[.,]\d+)?\s*%", "percentage"),
    # Citations directes avec guillemets
    (r'["«]\s*[A-Z][^"»]{15,200}\s*["»]', "quote"),
    # URL suspectes (peut-etre inventees)
    (r"https?://[^\s\)]{5,100}", "url"),
    # Noms complets + position ("Elon Musk, CEO de Tesla")
    (r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2},\s+(?:CEO|fondateur|president|directeur|CTO|PDG)\b", "exec_name"),
]


def extract_factual_claims(text: str) -> list[dict[str, Any]]:
    """Detecte les affirmations factuelles dans un texte.

    Retourne : [{type, match, position, context_sentence}, ...].
    """
    if not text:
        return []

    # Decoupe en phrases pour contexte
    sentences = re.split(r"(?<=[.!?])\s+", text)

    claims: list[dict] = []
    for pattern, claim_type in _CLAIM_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            pos = m.start()
            # Trouve la phrase contenant ce match
            cumul = 0
            sentence = ""
            for s in sentences:
                if cumul <= pos < cumul + len(s) + 2:
                    sentence = s.strip()
                    break
                cumul += len(s) + 2
            claims.append({
                "type": claim_type,
                "match": m.group(0),
                "position": pos,
                "context_sentence": sentence[:250],
            })

    # Dedup : meme match + contexte
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for c in claims:
        key = (c["match"], c["context_sentence"][:60])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def has_citation_nearby(text: str, position: int, window: int = 80) -> bool:
    """Verifie si un claim est accompagne d'une citation / source."""
    snippet = text[max(0, position - window):position + window]
    # Patterns de citation reconnus
    citation_patterns = [
        r"\[\d+\]",                          # [1], [23]
        r"\[source[^\]]{0,80}\]",            # [source : ...]
        r"\[selon[^\]]{0,80}\]",
        r"\(source[^\)]{0,80}\)",
        r"\b(?:selon|d'apres|source|via)\s+[A-Z][a-zA-Z.]+",  # selon Wikipedia
        r"https?://[^\s\)]{5,}",             # URL directe
    ]
    for p in citation_patterns:
        if re.search(p, snippet, re.IGNORECASE):
            return True
    return False


def has_hedge_nearby(text: str, position: int, window: int = 60) -> bool:
    """Verifie si un claim est entoure de verbes d'incertitude."""
    snippet = text[max(0, position - window):position + window]
    hedges = [
        "semble", "semblerait", "environ", "approximativement", "peut-etre",
        "probable", "vraisemblable", "selon", "d'apres", "il se peut",
        "je crois", "je pense", "possiblement", "je suppose", "a priori",
        "a verifier", "sauf erreur", "si je me souviens bien",
    ]
    lower = snippet.lower()
    return any(h in lower for h in hedges)


# ─────────────────────────────────────────────────────────────────────────────
# Verification (COUCHE 3) : grounding automatique via Haiku
# ─────────────────────────────────────────────────────────────────────────────

_GROUNDING_SYSTEM = """Tu es un verificateur d'affirmations. On te donne une liste de claims
extraits d'une reponse d'agent IA. Pour chaque claim, rate le niveau de risque d'hallucination :

- **LOW** (0) : fait notoire, difficilement faux (ex: "Paris est la capitale de la France")
- **MEDIUM** (1) : fait precis mais plausible, verifiable (ex: "1,3 milliard d'habitants en Chine")
- **HIGH** (2) : tres specifique, sans source citee, risque fort d'halluc (ex: "le 14 mars 2024, X a dit Y", URL sans grounding)

Reponds UNIQUEMENT en JSON strict, format :
{"ratings": [{"idx": N, "risk": "LOW|MEDIUM|HIGH", "reason": "courte explication"}]}

Sois severe : preferer flagger 1 claim trop que d'en laisser passer un faux.
"""


async def rate_claims(
    claims: list[dict],
    client: Any,
    *,
    model: str = "claude-haiku-4-5-20251001",
    timeout_s: float = 10.0,
) -> list[dict]:
    """Appelle Haiku pour rater le risque d'halluc de chaque claim.

    Retourne la meme liste avec champ 'risk' et 'reason' ajoute.
    """
    if not claims:
        return []

    items_text = "\n".join(
        f"[{i}] ({c['type']}) \"{c['match']}\" — contexte: \"{c['context_sentence'][:150]}\""
        for i, c in enumerate(claims)
    )
    user_content = f"Claims a evaluer :\n{items_text}\n\nReponds en JSON."

    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=model,
                max_tokens=600,
                system=[{
                    "type": "text",
                    "text": _GROUNDING_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_content}],
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.debug("rate_claims timeout")
        return claims
    except Exception as e:
        logger.debug(f"rate_claims failed: {e}")
        return claims

    raw = ""
    try:
        for b in resp.content or []:
            if hasattr(b, "text"):
                raw += b.text
    except Exception:
        pass

    import json
    try:
        # Trouve le JSON dans la reponse
        start = raw.find("{")
        if start >= 0:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(raw[start:])
        else:
            return claims
    except Exception:
        return claims

    ratings = data.get("ratings", []) if isinstance(data, dict) else []
    by_idx = {r["idx"]: r for r in ratings if isinstance(r, dict) and "idx" in r}

    # Enrichis les claims avec le rating
    for i, c in enumerate(claims):
        r = by_idx.get(i)
        if r:
            c["risk"] = r.get("risk", "MEDIUM")
            c["reason"] = r.get("reason", "")
        else:
            c["risk"] = "MEDIUM"
    return claims


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline principal : ground_response
# ─────────────────────────────────────────────────────────────────────────────

async def ground_response(
    draft: str,
    client: Any,
    *,
    db: Any = None,
    user_id: str | None = None,
    flag_unverified: bool = True,
    min_chars: int = 200,
) -> dict[str, Any]:
    """Pipeline complet :
      1. Detecte claims factuels dans draft
      2. Filtre ceux SANS citation ni hedge proche
      3. Appelle Haiku pour rater le risque
      4. Si claim HIGH risk et pas sourced : flag ou hedge automatique

    Retourne {
      grounded_text: str,
      claims: [...],
      high_risk_claims: [...],
      changed: bool,
    }
    """
    if not draft or len(draft) < min_chars:
        return {
            "grounded_text": draft,
            "claims": [],
            "high_risk_claims": [],
            "changed": False,
            "reason": "too_short",
        }

    claims = extract_factual_claims(draft)
    if not claims:
        return {
            "grounded_text": draft,
            "claims": [],
            "high_risk_claims": [],
            "changed": False,
            "reason": "no_claims",
        }

    # Filtre : garde seulement les claims SANS citation ni hedge
    unsourced = [
        c for c in claims
        if not has_citation_nearby(draft, c["position"])
        and not has_hedge_nearby(draft, c["position"])
    ]
    if not unsourced:
        return {
            "grounded_text": draft,
            "claims": claims,
            "high_risk_claims": [],
            "changed": False,
            "reason": "all_sourced",
        }

    # Rate les claims non-sourced
    rated = await rate_claims(unsourced, client)
    high_risk = [c for c in rated if c.get("risk") == "HIGH"]

    grounded = draft
    changed = False

    if flag_unverified and high_risk:
        # Ajoute un disclaimer en fin de reponse
        disclaimer_parts = ["\n\n⚠ _Verification suggeree_ :"]
        for c in high_risk[:5]:
            disclaimer_parts.append(f"- \"{c['match']}\" ({c['reason'][:80]})")
        grounded = draft + "\n".join(disclaimer_parts)
        changed = True

    return {
        "grounded_text": grounded,
        "claims": rated,
        "high_risk_claims": high_risk,
        "changed": changed,
        "reason": "grounded" if changed else "no_high_risk",
    }


__all__ = [
    "GROUNDING_PROMPT_BLOCK",
    "extract_factual_claims",
    "has_citation_nearby",
    "has_hedge_nearby",
    "rate_claims",
    "ground_response",
]
