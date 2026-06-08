"""
Tests structurels de l'invariant Dashboard.

Invariant : sum(te × prog) / sum(te) × temps_initial == temps_gagne_jours

Les progressions des sous-objectifs sont la SOURCE DE VERITE. Le champ
`temps_gagne_jours` du profil est juste un cache derive. A chaque save du
profil, ProfilRepository.sauvegarder() re-derive temps_gagne pour garantir
l'invariant SANS jamais toucher aux progressions.

Pas de bouton "Recalculer", pas de banner — l'invariant est garanti par
construction.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.storage.repositories import ProfilRepository
from tests.conftest import make_shared_db, dispose_shared_db


def _create_profil_with_sos(db, *, temps_initial: float, sos: list[tuple[float, float]]):
    """Cree un profil + n sous-objectifs avec (te, prog) chacun.

    Retourne le profil_id pour pouvoir le re-charger.
    """
    profil_id = uuid.uuid4().hex
    db.conn.execute(
        "INSERT INTO profil_utilisateur (id, nom, age, profession, ville, "
        "situation_familiale, revenu_annuel, patrimoine_estime, charges_mensuelles, "
        "temps_initial_jours, temps_gagne_jours, probabilite_actuelle, "
        "cree_le, mis_a_jour_le, objectif_description, objectif_categorie, "
        "objectif_deadline, objectif_probabilite_base, objectif_probabilite_calculee, "
        "objectif_modifie_le) VALUES (?, 'T', 30, 'P', 'P', 'C', 0, 0, 0, "
        "?, 0, 0, datetime('now'), datetime('now'), 'O', 'carrière', NULL, 0, 0, "
        "datetime('now'))",
        (profil_id, temps_initial),
    )
    for idx, (te, prog) in enumerate(sos):
        db.conn.execute(
            "INSERT INTO sous_objectifs (id, user_id, titre, ordre, "
            "temps_estime, progression, cree_le) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (uuid.uuid4().hex, profil_id, f"SO{idx}", idx, te, prog),
        )
    db.conn.commit()
    return profil_id


def _load_profil(db, profil_id: str) -> ProfilUtilisateur:
    row = db.conn.execute(
        "SELECT * FROM profil_utilisateur WHERE id = ?", (profil_id,)
    ).fetchone()
    return ProfilUtilisateur.from_dict(dict(row))


def _compute_derived_temps_gagne(db, profil_id: str, temps_initial: float) -> float:
    rows = db.conn.execute(
        "SELECT temps_estime, progression FROM sous_objectifs WHERE user_id = ?",
        (profil_id,),
    ).fetchall()
    sum_te = sum(float(r["temps_estime"] or 0) for r in rows)
    weighted = sum(
        float(r["temps_estime"] or 0) * float(r["progression"] or 0) / 100.0
        for r in rows
    )
    return weighted * temps_initial / sum_te if sum_te > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_save_aligns_temps_gagne_from_progressions(tmp_path, monkeypatch):
    """Si on save un profil avec temps_gagne incoherent avec les progressions
    des SOs, le save DOIT re-aligner temps_gagne sur les progressions
    automatiquement (sans toucher aux progressions)."""
    db = make_shared_db(tmp_path, monkeypatch)
    try:
        # SOs : te=180/150/120/90, prog=0%/44.13%/100%/9.20% -> derived = 704.18
        profil_id = _create_profil_with_sos(
            db, temps_initial=1956.0,
            sos=[(180.0, 0.0), (150.0, 44.1346), (120.0, 100.0), (90.0, 9.1962)],
        )
        derived = _compute_derived_temps_gagne(db, profil_id, 1956.0)
        assert 700 < derived < 710  # ~ 704.18

        # On simule l'etat polluant : temps_gagne = 917.2 (drift 213j)
        db.conn.execute(
            "UPDATE profil_utilisateur SET temps_gagne_jours = 917.2 WHERE id = ?",
            (profil_id,),
        )
        db.conn.commit()

        # Save via ProfilRepository.sauvegarder() doit auto-aligner
        repo = ProfilRepository(db)
        profil = _load_profil(db, profil_id)
        assert abs(profil.temps_gagne_jours - 917.2) < 0.01  # avant alignement
        repo.sauvegarder(profil)

        # Apres save : temps_gagne aligne sur progressions
        profil_after = _load_profil(db, profil_id)
        assert abs(profil_after.temps_gagne_jours - derived) < 1.0, (
            f"Expected ~{derived:.2f}, got {profil_after.temps_gagne_jours:.2f}"
        )

        # Verif : progressions SOs NON modifiees
        sos = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
            (profil_id,),
        ).fetchall()
        progs = [round(float(r["progression"]), 2) for r in sos]
        assert progs == [0.0, 44.13, 100.0, 9.2]
    finally:
        dispose_shared_db(db)


def test_save_noop_when_invariant_already_holds(tmp_path, monkeypatch):
    """Si temps_gagne est deja coherent avec les progressions, le save ne
    le modifie pas (tolerance 0.5j)."""
    db = make_shared_db(tmp_path, monkeypatch)
    try:
        profil_id = _create_profil_with_sos(
            db, temps_initial=1000.0,
            sos=[(100.0, 50.0), (100.0, 50.0)],  # derived = 500
        )
        # On place temps_gagne pile sur la valeur derivee
        db.conn.execute(
            "UPDATE profil_utilisateur SET temps_gagne_jours = 500.0 WHERE id = ?",
            (profil_id,),
        )
        db.conn.commit()

        repo = ProfilRepository(db)
        profil = _load_profil(db, profil_id)
        repo.sauvegarder(profil)

        profil_after = _load_profil(db, profil_id)
        # Inchange (tolerance arrondis)
        assert abs(profil_after.temps_gagne_jours - 500.0) < 0.5
    finally:
        dispose_shared_db(db)


def test_save_with_no_sos_does_not_crash(tmp_path, monkeypatch):
    """Si pas encore de SOs (profil tout neuf), le save ne crash pas et ne
    modifie pas temps_gagne (no-op)."""
    db = make_shared_db(tmp_path, monkeypatch)
    try:
        profil_id = _create_profil_with_sos(
            db, temps_initial=1000.0, sos=[],  # aucun SO
        )
        db.conn.execute(
            "UPDATE profil_utilisateur SET temps_gagne_jours = 250.0 WHERE id = ?",
            (profil_id,),
        )
        db.conn.commit()

        repo = ProfilRepository(db)
        profil = _load_profil(db, profil_id)
        repo.sauvegarder(profil)

        profil_after = _load_profil(db, profil_id)
        assert abs(profil_after.temps_gagne_jours - 250.0) < 0.01
    finally:
        dispose_shared_db(db)


def test_invariant_holds_after_save(tmp_path, monkeypatch):
    """Apres save, sum(SO_jours_restant) == objectif_restant EXACTEMENT
    (modulo arrondis < 1j). C'est la garantie structurelle demandee."""
    db = make_shared_db(tmp_path, monkeypatch)
    try:
        profil_id = _create_profil_with_sos(
            db, temps_initial=2000.0,
            sos=[(200.0, 25.0), (200.0, 60.0), (100.0, 100.0), (300.0, 10.0)],
        )
        db.conn.execute(
            "UPDATE profil_utilisateur SET temps_gagne_jours = 1500.0 WHERE id = ?",
            (profil_id,),
        )
        db.conn.commit()

        repo = ProfilRepository(db)
        profil = _load_profil(db, profil_id)
        repo.sauvegarder(profil)
        profil_after = _load_profil(db, profil_id)

        # Calcul invariant : sum(te_prop × (1 - prog/100)) == objectif_restant
        rows = db.conn.execute(
            "SELECT temps_estime, progression FROM sous_objectifs WHERE user_id = ?",
            (profil_id,),
        ).fetchall()
        sum_te = sum(float(r["temps_estime"] or 0) for r in rows)
        so_jours_restant_total = sum(
            (float(r["temps_estime"] or 0) / sum_te) * profil_after.temps_initial_jours
            * (1 - float(r["progression"] or 0) / 100.0)
            for r in rows
        )
        objectif_restant = profil_after.temps_initial_jours - profil_after.temps_gagne_jours

        assert abs(so_jours_restant_total - objectif_restant) < 1.0, (
            f"INVARIANT BROKEN : sum(SO_restant)={so_jours_restant_total:.2f}, "
            f"objectif_restant={objectif_restant:.2f}, drift={so_jours_restant_total - objectif_restant:+.2f}"
        )
    finally:
        dispose_shared_db(db)


def test_save_clamps_temps_gagne_to_temps_initial(tmp_path, monkeypatch):
    """Si les progressions sommees depassent temps_initial (cas impossible
    en pratique mais defensif), temps_gagne est clampe a temps_initial."""
    db = make_shared_db(tmp_path, monkeypatch)
    try:
        profil_id = _create_profil_with_sos(
            db, temps_initial=1000.0,
            sos=[(100.0, 100.0), (100.0, 100.0)],  # derived = 1000
        )
        repo = ProfilRepository(db)
        profil = _load_profil(db, profil_id)
        repo.sauvegarder(profil)
        profil_after = _load_profil(db, profil_id)
        # 1000 exact ou plus = clampe a 1000
        assert profil_after.temps_gagne_jours <= 1000.0
        assert profil_after.temps_gagne_jours >= 999.0
    finally:
        dispose_shared_db(db)
