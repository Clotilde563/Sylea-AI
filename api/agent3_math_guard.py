"""
Agent 3 — Math precision guard.

Objectif : empecher les LLMs de faire du calcul mental foireux.

Strategie en 2 couches :

**COUCHE 1 — Detection preventive**
`is_math_question(text)` detecte si la requete user implique des calculs.
Si oui, le system prompt force l'agent a utiliser `PYTHON_EXEC` (sandbox)
plutot que de repondre "de tete".

**COUCHE 2 — Verification post-generation**
`verify_math_in_response(response, client)` detecte les chiffres dans
la reponse, et si >= 2 chiffres issus d'un calcul : propose de les
recalculer via sandbox pour verification.

Le sandbox Python (api/python_sandbox.py) donne des resultats mathematiques
EXACTS (arithmetique IEEE 754) vs Claude qui hallucine des chiffres.

Usage typique dans /chat/native :
    from api.agent3_math_guard import is_math_question, MATH_PROMPT_BLOCK

    if is_math_question(user_msg):
        system_prompt += "\n\n" + MATH_PROMPT_BLOCK
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("sylea.math_guard")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt pour forcer l'usage de PYTHON_EXEC (COUCHE 1)
# ─────────────────────────────────────────────────────────────────────────────

MATH_PROMPT_BLOCK = """
=== MATH PRECISION (critique) ===

Cette question implique des calculs. REGLES ABSOLUES :

1. **NE FAIS PAS de calcul mental**. Les LLMs (toi inclus) font des erreurs
   sur :
   - Multiplications/divisions de nombres >100
   - Pourcentages composees (+X%, -Y%, intérêts composes)
   - Sommes de longues listes
   - Conversions d'unites
   - Statistiques (moyenne, mediane, ecart-type, percentiles)
   - Calcul de dates (jours entre 2 dates, ages precis)
   - Finance (ROI, VAN, TRI, intérêts)

2. **UTILISE TOUJOURS `python_exec`** pour :
   - Toute operation avec >2 chiffres
   - Tout nombre > 1000
   - Toute serie/liste > 5 elements
   - Tout pourcentage compose
   - Toute conversion d'unite non triviale

3. **Format du code Python minimal** :
   ```python
   result = <calcul>
   print(result)
   ```
   Pas besoin d'imports pour de l'arithmetique simple.

4. **Presenter la reponse** : cite la valeur calculee par le sandbox +
   montre brievement le raisonnement, PAS la resolution complete (la
   confiance vient de l'execution deterministe, pas de ton explication).

5. **Mentalite : "precision > vitesse"**. Un appel sandbox coute ~50ms et
   evite une erreur de calcul potentiellement grave (ex: recommandation
   d'investissement basee sur un calcul faux).

Exemple :
User : "Si j'investis 10k€ a 5% sur 20 ans, j'ai combien ?"
Toi : [utilise python_exec : `print(10000 * (1.05 ** 20))`]
     Tu investiras 10 000€ et obtiendras **26 532,98€** apres 20 ans
     (interets composes 5% annuels).
"""


# ─────────────────────────────────────────────────────────────────────────────
# Detection (COUCHE 1)
# ─────────────────────────────────────────────────────────────────────────────

# Operateurs/symboles mathematiques
_MATH_OPERATORS = re.compile(r"[+\-*/=<>^%]|\*\*")

# Keywords mathematiques en francais + anglais
_MATH_KEYWORDS = {
    # FR calculs
    "calcul", "calculer", "calcule", "calculs",
    "combien", "multiplie", "multiplication", "divise", "division",
    "somme", "total", "additionn", "soustraction", "soustrai",
    "pourcentage", "ratio", "proportion",
    "moyenne", "median", "ecart-type", "variance",
    "difference", "augmentation", "reduction", "remise",

    # FR finance / math applique
    "interet", "intéret", "intérêt", "compose", "taux",
    "rentabilit", "roi", "van", "tri", "amortissement",
    "tva", "htva", "ttc", "ht", "commission",

    # FR temps / dates
    # NB : "age" retire car matche "agent", "agence", "agender", etc.
    # On garde "ages" et "mon age" en pattern explicite si besoin.
    "jours entre", "annees entre", "duree",

    # EN
    "calculate", "compute", "how much", "how many", "sum",
    "total", "average", "percentage", "interest", "compound",
    "difference between",

    # Signes monetaires / unites
    "€", "$", "£", "¥", "kg", "km", "m²", "m3", "m/s",
}

# Patterns qui capturent des expressions mathematiques claires
_MATH_PATTERNS = [
    # Operations explicites : "12 + 34", "500 * 0.15"
    r"\b\d+(?:[.,]\d+)?\s*[+\-*/]\s*\d+(?:[.,]\d+)?\b",
    # Pourcentages composes : "10% de X"
    r"\b\d+(?:[.,]\d+)?\s*%\s+(?:de|of)\b",
    # Questions chiffrees : "quelle est la moyenne de 12, 45, 67"
    r"\b(?:moyenne|median|somme|total|ecart)\s+(?:de|des?)\s+\d+",
    # Formules financieres : "5% sur 10 ans"
    r"\b\d+(?:[.,]\d+)?\s*%\s+sur\s+\d+\s+(?:ans?|mois|jours?|annees?)",
    # Conversions : "150 km/h en m/s"
    r"\b\d+\s*[a-zA-Z/²³]+\s+en\s+\w+",
]


def is_math_question(text: str) -> tuple[bool, str]:
    """Detecte si un message implique des calculs.

    Retourne (is_math, reason).
    """
    if not text or not text.strip():
        return False, ""
    t = text.lower()

    # Check keywords forts (matching par MOT ENTIER pour eviter les faux
    # positifs : "ht" qui matche "incremenTE", "tva" qui matche "atTendre", etc.)
    # Si le keyword contient un espace ou un tiret, on le matche litteralement.
    # Sinon on l'entoure de \b...\b pour matching mot.
    for kw in _MATH_KEYWORDS:
        if " " in kw or "-" in kw or len(kw) <= 2 or not kw.isascii() or not kw.isalnum():
            # Multi-mots ou symbole : substring match (ex: "kg", "€", "ecart-type")
            # Pour les chars uniques (€, $) et 2-char (kg, km, ht) on garde substring
            # mais ces derniers sont risques. On ajoute des word boundaries pour les
            # acronymes alphanumeriques courts.
            if kw.isalpha() and len(kw) <= 4:
                if re.search(rf"\b{re.escape(kw)}\b", t):
                    if kw in ("ht", "tva", "ttc"):
                        # Ces acronymes financiers requierent un chiffre dans la phrase
                        if not re.search(r"\d", text):
                            continue
                    return True, f"keyword:{kw}"
                continue
            if kw in t:
                return True, f"keyword:{kw}"
            continue
        # Mots normaux : word boundary
        if re.search(rf"\b{re.escape(kw)}\b", t):
            # Filtre les faux positifs : "combien de fois tu as" (pas math)
            if kw in ("combien", "how much", "how many"):
                if re.search(r"\d", text) or any(k in t for k in ("euros", "dollars", "%", "kg", "km", "heure")):
                    return True, f"keyword:{kw}"
                continue
            return True, f"keyword:{kw}"
        # Aussi tester comme prefix (ex: "calcul" matche "calcule", "calculs")
        # via "kw" dans le texte SI kw est en debut de mot.
        if re.search(rf"\b{re.escape(kw)}", t):
            if kw in ("combien", "how much", "how many"):
                if re.search(r"\d", text) or any(k in t for k in ("euros", "dollars", "%", "kg", "km", "heure")):
                    return True, f"keyword:{kw}"
                continue
            return True, f"keyword:{kw}"

    # Check patterns
    for p in _MATH_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return True, "pattern"

    # Heuristique : plusieurs nombres + operateur ENTRE des nombres (pas dans
    # des mots composes comme "sous-agents", "max-turns", etc.).
    # On exige que l'operateur soit adjacent a au moins un chiffre des deux
    # cotes (pas separe par des lettres) pour eviter les faux positifs.
    numbers_count = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", text))
    if numbers_count >= 2:
        # On veut un operateur lie a un chiffre (pas un dash dans un mot)
        op_near_number = re.search(
            r"\d+(?:[.,]\d+)?\s*[+\-*/=<>^%]\s*\d+(?:[.,]\d+)?"   # 12 + 34
            r"|\d+(?:[.,]\d+)?\s*\*\*\s*\d+(?:[.,]\d+)?"            # 2 ** 8
            r"|\d+\s*%(?:\s|$)",                                       # 15% (alone)
            text,
        )
        if op_near_number:
            return True, "numbers+operator"

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Verification post-generation (COUCHE 2)
# ─────────────────────────────────────────────────────────────────────────────

def extract_numeric_claims(text: str) -> list[dict[str, Any]]:
    """Extrait les chiffres qui pourraient etre issus de calculs.

    Retourne : [{number, position, context, has_currency, has_percent}, ...].
    """
    claims: list[dict] = []

    # Pattern : nombre (possiblement avec decimale / separateurs) dans une phrase
    # Couvre : 42, 2500, 1 234, 1.234,56, 15.3
    for m in re.finditer(r"\b(\d+(?:[ ,]\d{3})*(?:[.,]\d+)?)\b", text):
        num_str = m.group(1)
        position = m.start()

        # Context 40 chars autour
        context = text[max(0, position - 40):min(len(text), position + len(num_str) + 40)]

        # Filtre les annees (2024, 1995)
        try:
            parsed = int(num_str.replace(" ", "").replace(".", "").replace(",", ""))
            if 1900 <= parsed <= 2100 and len(num_str) == 4:
                continue  # probable date
        except ValueError:
            pass

        # Marqueurs de valeur financiere / pourcentage
        has_currency = bool(re.search(r"[€$£¥]\s*" + re.escape(num_str), text[:position + len(num_str) + 5]))
        has_currency = has_currency or bool(
            re.search(re.escape(num_str) + r"\s*[€$£¥]|euros?|dollars?", text[position:position + len(num_str) + 10])
        )
        has_percent = bool(re.search(re.escape(num_str) + r"\s*%", text[position:position + len(num_str) + 3]))

        claims.append({
            "number": num_str,
            "position": position,
            "context": context,
            "has_currency": has_currency,
            "has_percent": has_percent,
        })

    return claims


def looks_like_computed_result(claims: list[dict]) -> bool:
    """Heuristique : est-ce que la reponse presente des chiffres calcules ?"""
    if len(claims) < 2:
        return False
    # Si >= 2 chiffres avec currency OU percent, probablement un calcul
    special = sum(1 for c in claims if c["has_currency"] or c["has_percent"])
    return special >= 2


async def verify_math_via_sandbox(
    expression: str,
    expected: str,
    *,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Execute une expression Python dans le sandbox pour valider un resultat.

    Utilise api/python_sandbox.py. Retourne {valid, computed, expected, error}.
    """
    try:
        from api.python_sandbox import run_python_sandbox
        code = f"print({expression})"
        r = await run_python_sandbox(code, timeout_s=timeout_s)
        stdout = (r.get("stdout") or "").strip()
        if r.get("timed_out") or r.get("error"):
            return {"valid": False, "computed": None, "expected": expected, "error": r.get("error") or "timeout"}
        # Compare (tolerance numerique)
        try:
            computed_f = float(stdout.replace(",", "."))
            expected_f = float(expected.replace(" ", "").replace(",", "."))
            valid = abs(computed_f - expected_f) / max(abs(expected_f), 1.0) < 0.01  # 1% tol
            return {"valid": valid, "computed": stdout, "expected": expected, "error": None}
        except ValueError:
            return {"valid": stdout == expected, "computed": stdout, "expected": expected, "error": None}
    except Exception as e:
        return {"valid": False, "computed": None, "expected": expected, "error": str(e)[:100]}


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline : decision sur quoi injecter dans le system prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_math_guard_block(user_message: str) -> str:
    """Si la question user implique des maths, retourne le prompt block.
    Sinon retourne "".
    """
    is_math, _ = is_math_question(user_message)
    return MATH_PROMPT_BLOCK if is_math else ""


__all__ = [
    "MATH_PROMPT_BLOCK",
    "is_math_question",
    "extract_numeric_claims",
    "looks_like_computed_result",
    "verify_math_via_sandbox",
    "build_math_guard_block",
]
