"""
Tests du nettoyage de verdict applique apres l'analyse Claude.

Le nettoyage gere les artefacts de l'historique :
  - Suppression naive de "X%" laissait "et  de probabilite" -> fix
  - Phrase bancale "Pour Lucas a 18 ans avec 11 mois et  de probabilite" ->
    devient "Pour Lucas a 18 ans avec 11 mois"
"""

from __future__ import annotations
import pytest

# Le _clean_verdict est une fonction locale a analyser_dilemme. On la
# re-implemente identique ici pour les tests (alternative : refactoring
# pour l'exposer comme helper module-level, mais ca touche analyse_dilemme).
import re as _re


def _clean_verdict(v: str, ref_temps_estime: str = "") -> str:
    v = " ".join(v.split()[:55])
    v = _re.sub(
        r'\s+(?:et|avec)\s+\d+[.,]?\d*\s*%\s*(?:de\s+probabilite|probabilite)\b',
        '',
        v,
        flags=_re.IGNORECASE,
    )
    v = _re.sub(
        r'\b\d+[.,]?\d*\s*%\s+de\s+probabilite\b',
        '',
        v,
        flags=_re.IGNORECASE,
    )
    v = _re.sub(r'\s*\d+[.,]?\d*\s*%\s*', ' ', v)
    v = _re.sub(r'\s+(?:et|avec|de)\s+de\s+probabilite\b', '', v, flags=_re.IGNORECASE)
    v = _re.sub(r'\s+(?:et|avec)\s+de\s+(?=,|\.|$)', '', v, flags=_re.IGNORECASE)
    if ref_temps_estime and ref_temps_estime.lower() not in v.lower():
        v = _re.sub(
            r'(?<!ans\s)\b(?:que\s+)?\d+\s*mois\s+(?:restants?|devant\s+(?:lui|moi|nous)|qui\s+restent?)\b',
            ref_temps_estime + ' restants',
            v,
            flags=_re.IGNORECASE,
        )
        v = _re.sub(
            r'(?:avec|que)\s+\d+\s*mois\s+(?=pour\s)',
            'avec ' + ref_temps_estime + ' ',
            v,
            flags=_re.IGNORECASE,
        )
    v = _re.sub(r'\s+([,.;:])', r'\1', v)
    v = _re.sub(r'\s+', ' ', v).strip()
    words = v.split()
    if len(words) > 50:
        v = " ".join(words[:50])
    if v and v[0].islower():
        v = v[0].upper() + v[1:]
    return v


# ─── Tests cas reproduits depuis production ─────────────────────────────────

def test_removes_et_X_percent_de_probabilite():
    """Cas reel observe (verdict Lucas, mai 2026) : Claude a ecrit
    'avec 11 mois restants et 45.57% de probabilite' -> apres cleanup
    naif on avait 'avec 11 mois restants et de probabilite' (bancal)."""
    v = "Pour Lucas a 18 ans avec 11 mois restants et 45.57% de probabilite, 30 min de code quotidien."
    out = _clean_verdict(v)
    assert "% " not in out
    assert "et  de" not in out
    assert "et de probabilite" not in out
    assert "11 mois restants" in out  # le reste de la phrase est preserve


def test_removes_avec_X_percent_de_probabilite():
    v = "Avec 35% de probabilite et 1 an d'engagement, l'option A apporte plus."
    out = _clean_verdict(v)
    assert "%" not in out
    assert "Avec  de probabilite" not in out
    assert "1 an d'engagement" in out


def test_removes_X_percent_de_probabilite_at_start():
    v = "45% de probabilite, c'est encore atteignable si tu codes."
    out = _clean_verdict(v)
    assert "%" not in out
    assert out.startswith("C") or "c'est encore atteignable" in out


def test_removes_isolated_percentage():
    v = "Tu es a 47%, c'est correct pour ton age."
    out = _clean_verdict(v)
    assert "%" not in out
    assert "c'est correct pour ton age" in out


def test_keeps_text_without_percentage_intact():
    v = "Coder 30 min par jour change tout sur 6 mois. Netflix endort."
    out = _clean_verdict(v)
    assert out == v.strip()  # rien a nettoyer


def test_truncates_to_50_words():
    v = " ".join(["mot"] * 100)
    out = _clean_verdict(v)
    assert len(out.split()) <= 50


def test_capitalizes_first_letter_when_lowercase():
    v = "de toute facon, code 30 min par jour."
    out = _clean_verdict(v)
    assert out[0].isupper()


def test_handles_empty_string():
    assert _clean_verdict("") == ""


def test_compacts_multiple_spaces():
    v = "Mot   avec   plusieurs   espaces."
    out = _clean_verdict(v)
    assert "   " not in out
    assert "  " not in out


def test_fixes_space_before_punctuation():
    v = "Coder 30 min ,  c'est bien."
    out = _clean_verdict(v)
    assert " ," not in out
    assert ", c'est" in out or ",c'est" in out


def test_real_lucas_verdict_full():
    """Le verdict de Lucas reproduit en entier, du test E2E."""
    v = ("Pour Lucas a 18 ans avec 2 ans 9 mois restants et 45.57% de probabilite, "
         "30 min de code quotidien sur un mois c'est 15 heures de pratique reelle "
         "- c'est ce qui fait la difference entre un portfolio qui stagne et un qui avance. "
         "Netflix ne recupere pas : ca anesthesie.")
    out = _clean_verdict(v)
    assert "%" not in out
    assert "et de probabilite" not in out
    assert "et  de" not in out
    assert "2 ans 9 mois restants" in out
    assert "15 heures de pratique" in out
    assert "Netflix ne recupere pas" in out


# ─── Tests anti-hallucination duree ────────────────────────────────────────

def test_corrige_hallucination_N_mois_restants():
    """Claude invente '11 mois restants' alors que le vrai temps est '2 ans 9 mois'.
    Le cleanup doit reecrire avec la vraie valeur."""
    v = "Pour Lucas a 18 ans avec 11 mois restants, code 30 min par jour."
    out = _clean_verdict(v, ref_temps_estime="2 ans 9 mois")
    assert "11 mois" not in out
    assert "2 ans 9 mois restants" in out


def test_corrige_hallucination_N_mois_devant_lui():
    v = "Lucas n'a que 8 mois devant lui pour atteindre 3000 euros par mois."
    out = _clean_verdict(v, ref_temps_estime="2 ans 9 mois")
    assert "8 mois devant lui" not in out
    # La formulation "que N mois" suivie de "pour" est remplacee par "avec X"
    assert "Lucas" in out
    assert "2 ans 9 mois" in out


def test_corrige_hallucination_avec_N_mois_pour():
    v = "Avec 5 mois pour boucler le portfolio, code 30 min par jour."
    out = _clean_verdict(v, ref_temps_estime="2 ans 9 mois")
    assert "5 mois pour" not in out
    assert "2 ans 9 mois" in out


def test_no_correction_quand_pas_de_ref():
    """Sans ref_temps_estime, on ne touche pas aux mentions de mois
    (par defaut, retrocompat)."""
    v = "Avec 11 mois pour finir."
    out = _clean_verdict(v)  # pas de ref
    assert "11 mois" in out


def test_correction_preserve_le_reste_du_verdict():
    v = ("Lucas a 18 ans avec 11 mois restants. Code 30 min par jour, "
         "c'est 15 heures par mois. Netflix anesthesie.")
    out = _clean_verdict(v, ref_temps_estime="2 ans 9 mois")
    assert "11 mois" not in out
    assert "2 ans 9 mois restants" in out
    assert "15 heures par mois" in out  # ce "mois" la est legit, pas touche
    assert "Netflix anesthesie" in out


def test_no_artifact_absorberaitde():
    """Bug reel observe : 'elle absorberait 80% de son temps' -> 'absorberaitde'
    (regex gobait trop d'espaces). Verifier que l'espace est preserve."""
    v = "elle absorberait 80% de son temps."
    out = _clean_verdict(v)
    assert "absorberaitde" not in out
    assert "absorberait" in out
    assert "de son temps" in out


def test_idempotent_si_ref_deja_present():
    """Si Claude ecrit deja 'avec 2 ans 11 mois restants', on ne re-corrige PAS
    pour eviter 'avec 2 ans 2 ans 11 mois'."""
    v = "Lucas est a 18 ans avec 2 ans 11 mois restants, l'option A reste meilleure."
    out = _clean_verdict(v, ref_temps_estime="2 ans 11 mois")
    assert "2 ans 2 ans" not in out
    assert "2 ans 11 mois restants" in out
    # Et le reste est preserve
    assert "l'option A reste meilleure" in out


def test_idempotent_protege_format_X_ans_Y_mois():
    """'avec 2 ans 11 mois restants' ne doit PAS etre transforme en
    'avec 2 ans X restants' meme si ref n'est pas EXACTEMENT 2 ans 11 mois.
    Le pattern (?<!ans\\s) empeche ca."""
    v = "Lucas avec 2 ans 6 mois restants."
    out = _clean_verdict(v, ref_temps_estime="3 ans 1 mois")
    # On ne touche pas a "6 mois restants" car precede de "ans "
    assert "2 ans 6 mois restants" in out


def test_corrige_seulement_mois_isole():
    """'avec 8 mois restants' (sans 'ans' devant) DOIT etre corrige."""
    v = "Lucas avec 8 mois restants pour son objectif."
    out = _clean_verdict(v, ref_temps_estime="3 ans 2 mois")
    assert "8 mois restants" not in out
    assert "3 ans 2 mois restants" in out
