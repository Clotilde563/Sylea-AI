"""
Router /api/marketplace/* — ClawHub skills marketplace dedie.

Wrappe les fonctions async clawhub_* de api.clawhub (CLI subprocess bridge)
et expose des endpoints propres sans conflit de routes (contrairement a
agent3_openclaw.py qui a deux routes GET /skills en collision).

Endpoints :
  GET    /api/marketplace/installed       -> liste locale (.openclaw/skills)
  POST   /api/marketplace/search          -> recherche clawhub.ai registry
  GET    /api/marketplace/skill/{slug}    -> details d'un skill
  POST   /api/marketplace/install/{slug}  -> installe depuis le registry
  DELETE /api/marketplace/skill/{slug}    -> desinstalle
  POST   /api/marketplace/check           -> verifie prerequis / etat
  GET    /api/marketplace/featured        -> vedettes (incluant Sylea lui-meme)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.clawhub import (
    clawhub_check,
    clawhub_install,
    clawhub_list_installed,
    clawhub_search,
    clawhub_skill_info,
    clawhub_uninstall,
)
from api.dependencies import get_optional_user

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


# ── Featured / static ────────────────────────────────────────────────────────


@router.get("/featured")
async def featured_skills(
    user_id: str | None = Depends(get_optional_user),
):
    """Skills mis en vedette. Inclut Sylea lui-meme publie sur ClawHub."""
    return {
        "featured": [
            {
                "slug": "sylea",
                "owner": "clotilde563",
                "name": "Syléa",
                "description": (
                    "Coach de vie & assistant de decision. Analyse tes dilemmes avec "
                    "un framework probabiliste, suit tes objectifs sur 5 dimensions "
                    "psychologiques, et lance des bilans de bien-etre quotidiens."
                ),
                "url": "https://clawhub.ai/clotilde563/sylea",
                "tags": [
                    "coaching", "productivity", "life-planning",
                    "decision-making", "wellbeing", "psychology", "francophone",
                ],
                "highlight": True,
                "homepage": "https://sylea-ai.com",
            },
        ],
    }


# ── Installed / search / install / uninstall ────────────────────────────────


@router.get("/installed")
async def list_installed(
    user_id: str | None = Depends(get_optional_user),
):
    """Liste les skills installees localement (~/.openclaw/skills/)."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    result = await clawhub_list_installed()
    return {
        "success": result.success,
        "skills": result.data if result.data else [],
        "error": result.error,
    }


@router.post("/search")
async def search(
    body: dict,
    user_id: str | None = Depends(get_optional_user),
):
    """Recherche vectorielle sur le registry ClawHub."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    query = (body or {}).get("query", "").strip()
    limit = int((body or {}).get("limit", 20))
    if not query:
        raise HTTPException(status_code=400, detail="Query requise (non vide)")
    result = await clawhub_search(query=query, limit=limit)
    return {
        "success": result.success,
        "query": query,
        "skills": result.data if result.data else [],
        "error": result.error,
    }


@router.get("/skill/{slug}")
async def skill_info(
    slug: str,
    user_id: str | None = Depends(get_optional_user),
):
    """Details d'un skill du registry ClawHub."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    result = await clawhub_skill_info(slug)
    if not result.success:
        raise HTTPException(status_code=404, detail=result.error or "Skill introuvable")
    return {
        "success": True,
        "slug": slug,
        "data": result.data,
    }


@router.post("/install/{slug}")
async def install(
    slug: str,
    user_id: str | None = Depends(get_optional_user),
):
    """Installe un skill depuis ClawHub dans ~/.openclaw/skills/."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    result = await clawhub_install(slug)
    return {
        "success": result.success,
        "slug": slug,
        "data": result.data,
        "error": result.error,
    }


@router.delete("/skill/{slug}")
async def uninstall(
    slug: str,
    user_id: str | None = Depends(get_optional_user),
):
    """Desinstalle un skill local."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    result = await clawhub_uninstall(slug)
    return {
        "success": result.success,
        "slug": slug,
        "data": result.data,
        "error": result.error,
    }


@router.post("/check")
async def check(
    user_id: str | None = Depends(get_optional_user),
):
    """Verifie prerequis / etat CLI clawhub + openclaw."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    result = await clawhub_check()
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
    }


# ── Publish (skill custom) ───────────────────────────────────────────────────


@router.post("/publish")
async def publish(
    body: dict,
    user_id: str | None = Depends(get_optional_user),
):
    """Publie un skill custom sur ClawHub.

    Body :
      slug : str (requis, kebab-case unique)
      name : str (requis, nom affichable)
      description : str (requis, 1-2 phrases)
      skill_content : str (requis, contenu SKILL.md complet)
      version : str (optionnel, ex '0.1.0')
      tags : list[str] (optionnel)
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifie")
    body = body or {}
    slug = (body.get("slug") or "").strip()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    skill_content = body.get("skill_content") or ""
    if not (slug and name and description and skill_content.strip()):
        raise HTTPException(
            status_code=400,
            detail="Champs requis : slug, name, description, skill_content",
        )
    try:
        from api.agent3_skills.clawhub_meta_tools import clawhub_meta_publish
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"clawhub_meta_publish import failed: {e}")
    result = await clawhub_meta_publish(
        slug=slug,
        name=name,
        description=description,
        skill_content=skill_content,
        version=(body.get("version") or "0.1.0"),
        tags=body.get("tags") or [],
    )
    return result
