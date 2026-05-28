"""
Router FastAPI — Dilemmes en mode TRACKING.

Nouveau systeme de suivi des decisions (cf. api/dilemmes_tracking.py).

Endpoints :
  POST   /api/dilemme/tracking/create        : demarre un tracking
  GET    /api/dilemme/tracking                : liste les trackings (filtrable par status)
  GET    /api/dilemme/tracking/:id            : detail d'un tracking
  POST   /api/dilemme/tracking/:id/respond    : enregistre une reponse de periode
  GET    /api/dilemme/tracking/:id/recap      : calcule le recap pondere
  POST   /api/dilemme/tracking/:id/validate   : applique l'impact final
  POST   /api/dilemme/tracking/:id/cancel     : annule (mode='zero' ou 'partial')
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_db, get_optional_user, get_profil_repo
from api import dilemmes_tracking as dt
from sylea.core.models.user import ProfilUtilisateur
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository

logger = logging.getLogger("sylea.routers.dilemmes_tracking")

router = APIRouter(prefix="/api/dilemme/tracking", tags=["dilemme-tracking"])


# ── Schemas Pydantic ─────────────────────────────────────────────────────────


class TrackingOptionIn(BaseModel):
    """Description d'une option du dilemme telle que stockee dans tracking.

    Reflete AnalyseOptionOut + impact_jours signe par option."""
    lettre: str = ""  # "A", "B", ...
    description: str
    impact_jours: float = 0.0
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    resume: str = ""


class TrackingCreateIn(BaseModel):
    question: str
    options: list[TrackingOptionIn]
    impact_temporel_jours: int = Field(..., gt=0, le=10_000)
    verdict: str = ""
    etude_scientifique: str = ""
    device_tz: str = "UTC"  # ex: "Europe/Paris"


class TrackingRespondIn(BaseModel):
    periode_idx: int = Field(..., ge=0)
    # Index option ("0", "1", ...) ou "none"
    choice: str


class TrackingCancelIn(BaseModel):
    mode: str  # 'zero' ou 'partial'


# ── Helpers ──────────────────────────────────────────────────────────────────


def _require_profil(profil_repo: ProfilRepository, user_id: str | None) -> ProfilUtilisateur:
    """Charge le profil. En mode auth (user_id != None) filtre par auth_user_id,
    sinon prend le premier profil (CLI / single-user). Aligne sur le pattern
    de dilemme.py / evenement.py : 404 si aucun profil, pas 401."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    return profil


def _serialize_tracking(t: dict) -> dict:
    """Serialise une row tracking pour le frontend (snake_case + JSON parses
    deja effectues par _row_to_dict)."""
    return {
        "id": t["id"],
        "question": t["question"],
        "options": t.get("options_json", []),
        "verdict": t.get("verdict") or "",
        "etude_scientifique": t.get("etude_scientifique") or "",
        "impact_temporel_jours": t["impact_temporel_jours"],
        "nb_periodes": t["nb_periodes"],
        "device_tz": t.get("device_tz") or "UTC",
        "choices": t.get("choices_json", []),
        "status": t["status"],
        "impact_final_jours": t.get("impact_final_jours"),
        "impact_final_probabilite": t.get("impact_final_probabilite"),
        "so_impactes": t.get("so_impactes_json", []),
        "cancellation_mode": t.get("cancellation_mode"),
        "next_notif_at": t.get("next_notif_at"),
        "created_at": t.get("created_at"),
        "validated_at": t.get("validated_at"),
        "cancelled_at": t.get("cancelled_at"),
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/create")
async def create_tracking(
    data: TrackingCreateIn,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Demarre un nouveau tracking apres analyse d'un dilemme.

    Le frontend appelle cet endpoint quand l'utilisateur clique sur
    "Confirmer" apres l'analyse. AUCUN impact n'est applique ici — il
    le sera uniquement a la validation finale (apres remplissage des
    periodes via les notifs).
    """
    profil = _require_profil(profil_repo, user_id)

    # S'assure que les tables existent (idempotent — utile en dev / 1er run)
    dt.ensure_tracking_tables(db)

    if len(data.options) < 2:
        raise HTTPException(status_code=400, detail="Au moins 2 options requises.")

    options_serialized = [
        {
            "lettre": o.lettre,
            "description": o.description,
            "impact_jours": float(o.impact_jours),
            "pros": list(o.pros),
            "cons": list(o.cons),
            "resume": o.resume,
        }
        for o in data.options
    ]

    try:
        result = await dt.create_tracking_async(
            user_id=profil.id,
            question=data.question,
            options=options_serialized,
            verdict=data.verdict,
            etude_scientifique=data.etude_scientifique,
            impact_temporel_jours=data.impact_temporel_jours,
            device_tz=data.device_tz or "UTC",
        )
    except Exception as e:
        logger.exception("create_tracking failed")
        raise HTTPException(status_code=500, detail=f"create_failed: {e}") from e

    # Renvoie le full tracking pour eviter un round-trip frontend
    full = await dt.get_tracking_async(result["id"], profil.id)
    return {
        "ok": True,
        "tracking": _serialize_tracking(full) if full else result,
    }


@router.get("")
async def list_trackings(
    status: str | None = None,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Liste tous les trackings de l'utilisateur.

    Query params :
      - status : 'tracking' | 'awaiting_validation' | 'validated' | 'cancelled'
    """
    profil = _require_profil(profil_repo, user_id)
    dt.ensure_tracking_tables(db)

    if status and status not in (
        "tracking", "awaiting_validation", "validated", "cancelled"
    ):
        raise HTTPException(status_code=400, detail="status_invalide")

    try:
        items = await dt.list_tracking_async(profil.id, status=status)
    except Exception as e:
        logger.exception("list_trackings failed")
        raise HTTPException(status_code=500, detail=f"list_failed: {e}") from e

    return {"ok": True, "items": [_serialize_tracking(t) for t in items]}


@router.get("/{tracking_id}")
async def get_tracking(
    tracking_id: str,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Detail d'un tracking. Inclut les choices, le status, etc."""
    profil = _require_profil(profil_repo, user_id)
    dt.ensure_tracking_tables(db)

    tracking = await dt.get_tracking_async(tracking_id, profil.id)
    if not tracking:
        raise HTTPException(status_code=404, detail="tracking_not_found")
    return {"ok": True, "tracking": _serialize_tracking(tracking)}


@router.post("/{tracking_id}/respond")
async def respond_period(
    tracking_id: str,
    data: TrackingRespondIn,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Enregistre une reponse de periode (depuis notif OS, in-app, ou clic
    sur la page Mes dilemmes en cours).

    Idempotent : si la periode est deja repondue, on remplace. Quand toutes
    les periodes sont repondues, le status passe a 'awaiting_validation'
    et le client doit appeler /validate pour appliquer l'impact.
    """
    profil = _require_profil(profil_repo, user_id)
    dt.ensure_tracking_tables(db)

    # Validation du format choice : "0", "1", ..., ou "none"
    choice = (data.choice or "").strip()
    if choice != "none":
        try:
            int(choice)  # doit etre un entier-en-string
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="choice doit etre 'none' ou l'index numerique de l'option (ex: '0', '1', ...)"
            )

    result = await dt.respond_to_period_async(
        tracking_id, profil.id, data.periode_idx, choice
    )
    if not result.get("ok"):
        err = result.get("error", "unknown")
        if err == "tracking_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err == "periode_idx_out_of_range":
            raise HTTPException(status_code=400, detail=err)
        if err == "periode_not_yet_due":
            # 425 Too Early : reponse refusee parce que la periode n'est
            # pas encore arrivee a echeance (anti-bypass scheduler).
            raise HTTPException(
                status_code=425,
                detail={
                    "error": err,
                    "periode_idx": result.get("periode_idx"),
                    "expected_notif_at": result.get("expected_notif_at"),
                },
            )
        if err.startswith("status_invalid"):
            raise HTTPException(status_code=409, detail=err)
        raise HTTPException(status_code=500, detail=err)
    return result


@router.get("/{tracking_id}/recap")
async def get_recap(
    tracking_id: str,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne le recap pondere SANS appliquer l'impact.

    Utilise par le frontend pour afficher l'ecran de validation finale
    (avec breakdown par option + impact total) avant que l'user clique
    sur "Valider".
    """
    profil = _require_profil(profil_repo, user_id)
    dt.ensure_tracking_tables(db)

    tracking = await dt.get_tracking_async(tracking_id, profil.id)
    if not tracking:
        raise HTTPException(status_code=404, detail="tracking_not_found")

    recap = dt.compute_recap(tracking)

    # Snapshot des sous-objectifs pour preview de l'impact
    prob_actuelle_before = float(getattr(profil, "probabilite_actuelle", 0))
    delta_prob_preview = dt._compute_delta_probabilite(
        prob_actuelle_before, float(recap["impact_total_jours"])
    )

    return {
        "ok": True,
        "tracking_id": tracking_id,
        "status": tracking["status"],
        "recap": recap,
        "delta_probabilite_preview": delta_prob_preview,
        "probabilite_actuelle": prob_actuelle_before,
    }


@router.post("/{tracking_id}/validate")
async def validate_tracking(
    tracking_id: str,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Valide le tracking : applique l'impact pondere sur le profil +
    cascade sous-objectifs, et marque status='validated'.

    Etat avant : 'awaiting_validation' (toutes periodes repondues) ou
    'tracking' (validation anticipee — cas rare, ex: auto-valid 7j).
    """
    profil = _require_profil(profil_repo, user_id)
    dt.ensure_tracking_tables(db)

    result = await dt.validate_tracking_async(
        tracking_id, profil.id, profil, profil_repo
    )
    if not result.get("ok"):
        err = result.get("error", "unknown")
        if err == "tracking_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err.startswith("status_invalid"):
            raise HTTPException(status_code=409, detail=err)
        raise HTTPException(status_code=500, detail=err)
    return result


@router.post("/{tracking_id}/cancel")
async def cancel_tracking(
    tracking_id: str,
    data: TrackingCancelIn,
    db: DatabaseManager = Depends(get_db),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Annule un tracking.

    mode='zero'    : aucun impact applique (l'user dit "j'arrete, oublie tout")
    mode='partial' : applique l'impact pondere base sur les choix deja faits
                     (pondere sur nb_periodes total, pas sur nb_responded —
                     plus l'user a repondu, plus l'impact est complet).
    """
    profil = _require_profil(profil_repo, user_id)
    dt.ensure_tracking_tables(db)

    if data.mode not in ("zero", "partial"):
        raise HTTPException(status_code=400, detail="mode_invalide (zero|partial)")

    result = await dt.cancel_tracking_async(
        tracking_id, profil.id, data.mode, profil, profil_repo
    )
    if not result.get("ok"):
        err = result.get("error", "unknown")
        if err == "tracking_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err.startswith("status_invalid"):
            raise HTTPException(status_code=409, detail=err)
        if err == "mode_invalid":
            raise HTTPException(status_code=400, detail=err)
        raise HTTPException(status_code=500, detail=err)
    return result
