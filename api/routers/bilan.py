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
from api.dependencies import get_profil_repo, get_optional_user

router = APIRouter(prefix="/api/bilan", tags=["bilan"])


@router.get("/aujourd-hui", response_model=BilanCheckOut)
async def check_bilan_aujourdhui(
    user_id: str | None = Depends(get_optional_user),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
):
    """Verifie si un bilan existe pour aujourd'hui.

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    today = date.today().isoformat()
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT * FROM bilans_quotidiens WHERE user_id = :uid AND date = :date"),
            {"uid": profil.id, "date": today},
        )
        row = result.mappings().first()

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
    user_id: str | None = Depends(get_optional_user),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
):
    """Cree le bilan du jour et met a jour les scores du profil.

    Migration PG : SELECT-then-UPDATE/INSERT via SQLAlchemy text() —
    portable SQLite + PostgreSQL (remplace `INSERT OR REPLACE`).
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    today = date.today().isoformat()
    now = datetime.now().isoformat()
    bilan_id = str(uuid.uuid4())

    # Inserer ou remplacer le bilan du jour (SELECT puis UPDATE/INSERT pour PG-compat)
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            existing = await session.execute(
                text(
                    "SELECT id FROM bilans_quotidiens "
                    "WHERE user_id = :uid AND date = :date"
                ),
                {"uid": profil.id, "date": today},
            )
            existing_row = existing.first()

            if existing_row is not None:
                # UPDATE — on garde l'id existant
                bilan_id = existing_row[0]
                await session.execute(
                    text(
                        "UPDATE bilans_quotidiens SET "
                        " niveau_sante = :ns, niveau_stress = :nstr, "
                        " niveau_energie = :ne, niveau_bonheur = :nb, "
                        " heures_travail = :ht, heures_sommeil = :hs, "
                        " heures_loisirs = :hl, heures_transport = :htr, "
                        " heures_objectif = :ho, description = :desc, "
                        " cree_le = :now "
                        "WHERE id = :id"
                    ),
                    {
                        "ns": data.niveau_sante,
                        "nstr": data.niveau_stress,
                        "ne": data.niveau_energie,
                        "nb": data.niveau_bonheur,
                        "ht": data.heures_travail,
                        "hs": data.heures_sommeil,
                        "hl": data.heures_loisirs,
                        "htr": data.heures_transport,
                        "ho": data.heures_objectif,
                        "desc": data.description,
                        "now": now,
                        "id": bilan_id,
                    },
                )
            else:
                # INSERT
                await session.execute(
                    text(
                        "INSERT INTO bilans_quotidiens "
                        "(id, user_id, date, niveau_sante, niveau_stress, "
                        " niveau_energie, niveau_bonheur, heures_travail, "
                        " heures_sommeil, heures_loisirs, heures_transport, "
                        " heures_objectif, description, cree_le) "
                        "VALUES (:id, :uid, :date, :ns, :nstr, :ne, :nb, "
                        " :ht, :hs, :hl, :htr, :ho, :desc, :now)"
                    ),
                    {
                        "id": bilan_id,
                        "uid": profil.id,
                        "date": today,
                        "ns": data.niveau_sante,
                        "nstr": data.niveau_stress,
                        "ne": data.niveau_energie,
                        "nb": data.niveau_bonheur,
                        "ht": data.heures_travail,
                        "hs": data.heures_sommeil,
                        "hl": data.heures_loisirs,
                        "htr": data.heures_transport,
                        "ho": data.heures_objectif,
                        "desc": data.description,
                        "now": now,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

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
    profil_repo.sauvegarder(profil, auth_user_id=user_id)

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
    user_id: str | None = Depends(get_optional_user),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
):
    """Liste des bilans recents.

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT * FROM bilans_quotidiens WHERE user_id = :uid ORDER BY date DESC LIMIT :limite"),
            {"uid": profil.id, "limite": limite},
        )
        rows = result.mappings().all()

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
