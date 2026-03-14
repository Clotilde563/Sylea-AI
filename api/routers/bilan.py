"""
Router FastAPI — Bilan quotidien.

Routes :
  GET  /api/bilan/aujourd-hui  -> verifie si un bilan existe pour aujourd'hui
  POST /api/bilan              -> cree le bilan du jour + met a jour le profil
  GET  /api/bilan/historique   -> liste des bilans recents
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException

from sylea.core.storage.repositories import ProfilRepository
from api.schemas import BilanIn, BilanOut, BilanCheckOut
from api.dependencies import get_profil_repo, get_db

router = APIRouter(prefix="/api/bilan", tags=["bilan"])


@router.get("/aujourd-hui", response_model=BilanCheckOut)
async def check_bilan_aujourdhui(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
):
    """Verifie si un bilan existe pour aujourd'hui."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")

    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    today = date.today().isoformat()
    row = db.conn.execute(
        "SELECT * FROM bilans_quotidiens WHERE user_id = ? AND date = ?",
        (profil.id, today),
    ).fetchone()

    if row:
        return BilanCheckOut(
            exists=True,
            bilan=BilanOut(
                id=row["id"],
                date=row["date"],
                niveau_sante=row["niveau_sante"],
                niveau_stress=row["niveau_stress"],
                niveau_energie=row["niveau_energie"],
                niveau_bonheur=row["niveau_bonheur"],
                heures_travail=row["heures_travail"],
                heures_sommeil=row["heures_sommeil"],
                heures_loisirs=row["heures_loisirs"],
                heures_transport=row["heures_transport"],
                heures_objectif=row["heures_objectif"],
                description=row["description"] or "",
                cree_le=row["cree_le"],
            ),
        )
    return BilanCheckOut(exists=False)


@router.post("", response_model=BilanOut)
async def creer_bilan(
    data: BilanIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
):
    """Cree le bilan du jour et met a jour les scores du profil."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")

    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    today = date.today().isoformat()
    now = datetime.now().isoformat()
    bilan_id = str(uuid.uuid4())

    # Inserer ou remplacer le bilan du jour
    db.conn.execute(
        """INSERT OR REPLACE INTO bilans_quotidiens
           (id, user_id, date, niveau_sante, niveau_stress, niveau_energie, niveau_bonheur,
            heures_travail, heures_sommeil, heures_loisirs, heures_transport, heures_objectif,
            description, cree_le)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            bilan_id, profil.id, today,
            data.niveau_sante, data.niveau_stress, data.niveau_energie, data.niveau_bonheur,
            data.heures_travail, data.heures_sommeil, data.heures_loisirs,
            data.heures_transport, data.heures_objectif,
            data.description, now,
        ),
    )
    db.conn.commit()

    # Mettre a jour le profil avec les nouveaux scores
    profil.niveau_sante = data.niveau_sante
    profil.niveau_stress = data.niveau_stress
    profil.niveau_energie = data.niveau_energie
    profil.niveau_bonheur = data.niveau_bonheur
    profil.heures_travail = data.heures_travail
    profil.heures_sommeil = data.heures_sommeil
    profil.heures_loisirs = data.heures_loisirs
    profil.heures_transport = data.heures_transport
    profil.heures_objectif = data.heures_objectif
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    return BilanOut(
        id=bilan_id,
        date=today,
        niveau_sante=data.niveau_sante,
        niveau_stress=data.niveau_stress,
        niveau_energie=data.niveau_energie,
        niveau_bonheur=data.niveau_bonheur,
        heures_travail=data.heures_travail,
        heures_sommeil=data.heures_sommeil,
        heures_loisirs=data.heures_loisirs,
        heures_transport=data.heures_transport,
        heures_objectif=data.heures_objectif,
        description=data.description,
        cree_le=now,
    )


@router.get("/historique", response_model=list)
async def historique_bilans(
    limite: int = 30,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
):
    """Liste des bilans recents."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")

    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    rows = db.conn.execute(
        "SELECT * FROM bilans_quotidiens WHERE user_id = ? ORDER BY date DESC LIMIT ?",
        (profil.id, limite),
    ).fetchall()

    return [
        BilanOut(
            id=row["id"],
            date=row["date"],
            niveau_sante=row["niveau_sante"],
            niveau_stress=row["niveau_stress"],
            niveau_energie=row["niveau_energie"],
            niveau_bonheur=row["niveau_bonheur"],
            heures_travail=row["heures_travail"],
            heures_sommeil=row["heures_sommeil"],
            heures_loisirs=row["heures_loisirs"],
            heures_transport=row["heures_transport"],
            heures_objectif=row["heures_objectif"],
            description=row["description"] or "",
            cree_le=row["cree_le"],
        )
        for row in rows
    ]
