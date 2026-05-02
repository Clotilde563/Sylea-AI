"""
Router FastAPI pour le Credential Vault — gestion des cles API tierces.

Endpoints :
  GET    /api/credentials/providers       → catalogue complet (public : sans `test`)
  GET    /api/credentials                  → liste des credentials du user (masquees)
  POST   /api/credentials/detect           → detecte provider a partir d'un input
  POST   /api/credentials/quick-save       → save + test en un seul appel
  POST   /api/credentials                  → save manuel (form complet)
  DELETE /api/credentials/{slug}/{field}   → supprime une credential
  POST   /api/credentials/{slug}/test      → re-test la credential existante

Complementaire a `api.routers.integrations` (OAuth Google/GitHub).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.credentials import (
    delete_credential,
    get_credential,
    has_credential,
    list_credentials,
    mask_credential_value,
    save_credential,
)
from api.dependencies import get_db, get_optional_user
from api.providers_registry import (
    all_providers,
    detect_provider_from_key,
    get_provider,
    search_providers,
)
from sylea.core.storage.database import DatabaseManager

logger = logging.getLogger("sylea.credentials.router")

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class DetectIn(BaseModel):
    input: str


class QuickSaveIn(BaseModel):
    input: str
    provider_slug: str | None = None
    field_key: str | None = None


class SaveCredentialIn(BaseModel):
    provider_slug: str
    values: dict[str, str]
    metadata: dict[str, Any] | None = None


class TestIn(BaseModel):
    provider_slug: str
    values: dict[str, str] | None = None  # si None, test les credentials deja sauvees


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_user(user_id: str | None) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")
    return user_id


async def _run_test_endpoint(
    provider: dict, values: dict[str, str],
) -> tuple[bool, str]:
    """Execute le test endpoint d'un provider avec les values fournis.

    Retourne (success, message).
    """
    test_cfg = provider.get("test")
    if not test_cfg:
        # Certains providers (Supabase) n'ont pas de test endpoint : on considere OK
        # tant que les champs requis sont presents et matchent leur regex.
        return True, "Aucun endpoint de test pour ce provider — validation syntaxique seulement"

    method = str(test_cfg.get("method", "GET")).upper()
    url = test_cfg.get("url", "")
    auth_mode = test_cfg.get("auth", "bearer")
    auth_field = test_cfg.get("auth_field", "api_key")
    auth_header_name = test_cfg.get("auth_header_name")
    auth_header_format = test_cfg.get("auth_header_format")
    extra_headers = dict(test_cfg.get("extra_headers", {}) or {})
    body = test_cfg.get("body")
    success_statuses = test_cfg.get("success_status", [200])

    token = values.get(auth_field, "")
    if not token:
        return False, f"Champ '{auth_field}' manquant pour le test"

    headers: dict[str, str] = dict(extra_headers)
    if auth_mode == "bearer":
        headers["Authorization"] = f"Bearer {token}"
    elif auth_mode == "header":
        fmt = auth_header_format or "{value}"
        headers[auth_header_name or "Authorization"] = fmt.format(value=token)
    elif auth_mode == "url_template":
        # Token est dans l'URL (ex: Telegram)
        url = url.replace(f"{{{auth_field}}}", token)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            if method == "POST":
                resp = await client.post(url, headers=headers, json=body)
            else:
                resp = await client.get(url, headers=headers)

            if resp.status_code in success_statuses:
                return True, f"OK ({resp.status_code})"
            return False, f"Echec ({resp.status_code})"
    except httpx.TimeoutException:
        return False, "Timeout lors du test (service lent ou injoignable)"
    except httpx.ConnectError:
        return False, "Connexion impossible au service distant"
    except Exception as e:
        return False, f"Erreur test : {type(e).__name__}"


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/credentials/providers  → catalogue public
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers():
    """Retourne le catalogue des providers supportes (sans les endpoints de test)."""
    return {"providers": all_providers(public=True)}


# ─────────────────────────────────────────────────────────────────────────────
# Support "infini" : credentials requises par les skills ClawHub installes
# ─────────────────────────────────────────────────────────────────────────────

def _env_name_to_provider_slug(env_name: str) -> str | None:
    """Heuristique : match un env name (ex: NOTION_INTEGRATION_TOKEN) vers un
    provider du catalogue en regardant les alias et les noms.

    Retourne None si aucun match — dans ce cas on stocke sous le namespace
    generic `clawhub_skill_<slug>` avec le nom env brut.
    """
    env_lower = env_name.lower()
    # Extrait le premier token (ex: "NOTION_INTEGRATION_TOKEN" -> "notion")
    first = env_lower.split("_")[0]
    # Match direct
    p = get_provider(first)
    if p is not None:
        return first
    # Match via aliases
    for provider in all_providers(public=False):
        if first in provider.get("aliases", []):
            return provider["slug"]
        if first in provider["display_name"].lower():
            return provider["slug"]
    return None


@router.get("/missing-for-skills")
async def missing_for_installed_skills(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Scanne les skills ClawHub installes pour l'user et retourne les
    credentials manquantes que l'utilisateur doit fournir.

    Format reponse :
    {
      "skills": [
        {
          "slug": "stripe-refunds",
          "name": "Stripe Refunds",
          "emoji": "💳",
          "required_env": ["STRIPE_API_KEY"],
          "missing": [
            {
              "env_name": "STRIPE_API_KEY",
              "matched_provider": "stripe",        // ou null si inconnu
              "field_key": "api_key",              // si matched_provider
              "has_credential": false
            }
          ]
        },
        ...
      ],
      "total_missing_count": 5
    }
    """
    uid = _require_user(user_id)
    try:
        from api.agent3_skills.clawhub_loader import load_all_skills
        from api.credentials import has_credential as _has_cred
    except Exception as e:
        logger.warning(f"missing_for_skills imports failed: {e}")
        return {"skills": [], "total_missing_count": 0}

    skills_metas = load_all_skills(auth_user_id=uid)
    out_skills = []
    total_missing = 0

    for meta in skills_metas:
        if not meta.required_env:
            continue
        missing_items = []
        for env_name in meta.required_env:
            matched_slug = _env_name_to_provider_slug(env_name)
            if matched_slug:
                # Credential standardisee via catalogue : check si le user a rempli
                # un des fields du provider (on ne sait pas lequel, on prend le 1er
                # requis).
                p = get_provider(matched_slug) or {}
                first_required_field = next(
                    (f["key"] for f in p.get("fields", []) if f.get("required")),
                    None,
                )
                has = False
                if first_required_field:
                    has = _has_cred(db, uid, matched_slug, first_required_field)
                missing_items.append({
                    "env_name": env_name,
                    "matched_provider": matched_slug,
                    "field_key": first_required_field,
                    "has_credential": has,
                })
                if not has:
                    total_missing += 1
            else:
                # Credential custom / inconnue : namespace generic clawhub_skill_<slug>
                custom_slug = f"clawhub_skill_{meta.slug}"
                has = _has_cred(db, uid, custom_slug, env_name)
                missing_items.append({
                    "env_name": env_name,
                    "matched_provider": None,  # pas dans le catalogue
                    "field_key": env_name,
                    "has_credential": has,
                    "custom_provider_slug": custom_slug,
                })
                if not has:
                    total_missing += 1
        out_skills.append({
            "slug": meta.slug,
            "name": meta.name,
            "emoji": meta.emoji or "🧩",
            "required_env": list(meta.required_env),
            "missing": missing_items,
        })

    return {"skills": out_skills, "total_missing_count": total_missing}


class SaveCustomIn(BaseModel):
    skill_slug: str
    env_name: str
    value: str


@router.post("/custom-skill-env")
async def save_custom_skill_env(
    body: SaveCustomIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Save une credential custom pour une env var specifique d'un skill ClawHub
    qui n'est pas dans le catalogue curé.

    Namespace : provider_slug = `clawhub_skill_<skill_slug>`, field_key = `<env_name>`.
    """
    uid = _require_user(user_id)
    if not body.skill_slug or not body.env_name or not body.value:
        raise HTTPException(status_code=400, detail="skill_slug, env_name, value requis")
    # Sanity : evite path traversal dans le slug
    import re
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,120}", body.skill_slug):
        raise HTTPException(status_code=400, detail="skill_slug invalide")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", body.env_name):
        raise HTTPException(
            status_code=400,
            detail="env_name invalide (doit etre MAJUSCULES + underscore, ex: MY_API_KEY)",
        )

    provider_slug = f"clawhub_skill_{body.skill_slug}"
    save_credential(
        db, uid, provider_slug, body.env_name, body.value.strip(),
        metadata={"source": "clawhub_custom", "skill_slug": body.skill_slug},
    )
    return {
        "success": True,
        "provider_slug": provider_slug,
        "field_key": body.env_name,
        "preview": mask_credential_value(body.value),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/credentials  → liste masquee des credentials du user
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def list_my_credentials(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    uid = _require_user(user_id)
    creds = list_credentials(db, uid)
    return {"credentials": creds, "count": len(creds)}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/credentials/detect  → detecte depuis un input generique
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/detect")
async def detect(
    body: DetectIn,
    user_id: str | None = Depends(get_optional_user),
):
    _require_user(user_id)
    raw = (body.input or "").strip()
    if not raw:
        return {"type": "empty", "matches": [], "suggestions": []}

    # 1) Pattern match — priorite : si ca ressemble a une cle API, c'en est une
    pattern_matches = detect_provider_from_key(raw)
    if pattern_matches:
        return {
            "type": "api_key_detected",
            "matches": pattern_matches,
            "suggestions": [],
        }

    # 2) Fuzzy match sur le nom (l'input ressemble probablement a un nom d'app)
    suggestions = search_providers(raw, limit=8)
    provider_details = []
    for slug, score in suggestions:
        p = get_provider(slug)
        if p is None:
            continue
        provider_details.append({
            "slug": p["slug"],
            "display_name": p["display_name"],
            "description": p["description"],
            "category": p["category"],
            "logo_emoji": p.get("logo_emoji", "🔑"),
            "score": round(score, 2),
        })

    if provider_details:
        return {
            "type": "provider_suggestions",
            "matches": [],
            "suggestions": provider_details,
        }

    # 3) Aucun match : retourne les plus populaires
    top = all_providers(public=True)[:5]
    return {
        "type": "no_match",
        "matches": [],
        "suggestions": [
            {
                "slug": p["slug"],
                "display_name": p["display_name"],
                "description": p["description"],
                "category": p["category"],
                "logo_emoji": p.get("logo_emoji", "🔑"),
                "score": 0.0,
            } for p in top
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/credentials/quick-save  → detect + save + test en 1 appel
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/quick-save")
async def quick_save(
    body: QuickSaveIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    uid = _require_user(user_id)
    raw = (body.input or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Input vide")

    # Resolution du provider + field
    provider_slug = body.provider_slug
    field_key = body.field_key
    detected_metadata: dict[str, Any] = {}

    if not provider_slug or not field_key:
        matches = detect_provider_from_key(raw)
        if not matches:
            raise HTTPException(
                status_code=400,
                detail="Impossible de detecter le provider. Utilise POST /api/credentials avec un provider_slug explicite.",
            )
        if len(matches) > 1:
            # Ambiguite : plusieurs patterns matchent
            return {
                "success": False,
                "ambiguous": True,
                "matches": matches,
                "message": "Plusieurs providers matchent. Choisis-en un via l'UI.",
            }
        m = matches[0]
        provider_slug = m["provider_slug"]
        field_key = m["field_key"]
        detected_metadata = m.get("metadata", {})

    provider = get_provider(provider_slug)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_slug}' inconnu")

    # Test endpoint (cle validee avant save)
    test_ok, test_msg = await _run_test_endpoint(provider, {field_key: raw})

    # Save (meme si le test echoue — on laisse le user decider de l'enlever)
    # Mais on NE save PAS si le test a explicitement retourne 401 (cle invalide)
    if test_msg.startswith("Echec (401") or test_msg.startswith("Echec (403"):
        return {
            "success": False,
            "validated": False,
            "test_message": test_msg,
            "message": "Cle invalide (authentification refusee par le provider). Non sauvegardee.",
        }

    save_credential(
        db, uid, provider_slug, field_key, raw,
        metadata=detected_metadata or None,
        test_ok=test_ok,
    )

    # Auto-sync vers OpenClaw Gateway si le provider a un mapping
    openclaw_synced = False
    try:
        from api.openclaw_config_sync import (
            sync_user_credentials_to_openclaw, _SYNC_MAP,
        )
        if provider_slug in _SYNC_MAP:
            sync_result = sync_user_credentials_to_openclaw(db, uid)
            openclaw_synced = sync_result.get("ok") and any(
                c.get("provider") == provider_slug
                for c in sync_result.get("changes", [])
            )
    except Exception as _sync_err:
        # Best-effort, ne pas bloquer si sync echoue
        pass

    # Skills reactivables ?
    skills = provider.get("used_by_skills", [])

    return {
        "success": True,
        "validated": test_ok,
        "provider_slug": provider_slug,
        "field_key": field_key,
        "preview": mask_credential_value(raw),
        "test_message": test_msg,
        "skills_activated": skills,
        "metadata": detected_metadata,
        "openclaw_synced": openclaw_synced,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/credentials  → save manuel (form complet multi-champs)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("")
async def save_manual(
    body: SaveCredentialIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    uid = _require_user(user_id)
    provider = get_provider(body.provider_slug)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{body.provider_slug}' inconnu")

    # Valide chaque champ
    saved_fields = []
    for field_def in provider.get("fields", []):
        key = field_def["key"]
        val = body.values.get(key, "").strip()
        if not val:
            if field_def.get("required", False):
                raise HTTPException(
                    status_code=400,
                    detail=f"Champ requis manquant : {key}",
                )
            continue
        # Valide pattern si fourni
        pattern = field_def.get("pattern")
        if pattern:
            import re
            if not re.match(pattern, val):
                raise HTTPException(
                    status_code=400,
                    detail=f"Format invalide pour {key}. {field_def.get('pattern_hint', '')}",
                )
        saved_fields.append(key)

    # Test si possible
    test_ok, test_msg = await _run_test_endpoint(provider, body.values)

    # Save tous les champs fournis
    for key in saved_fields:
        val = body.values[key].strip()
        save_credential(
            db, uid, body.provider_slug, key, val,
            metadata=body.metadata,
            test_ok=test_ok,
        )

    return {
        "success": True,
        "validated": test_ok,
        "test_message": test_msg,
        "saved_fields": saved_fields,
        "skills_activated": provider.get("used_by_skills", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/credentials/{slug}/{field}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{provider_slug}/{field_key}")
async def delete_one(
    provider_slug: str,
    field_key: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    uid = _require_user(user_id)
    removed = delete_credential(db, uid, provider_slug, field_key)
    return {"success": removed, "deleted": removed}


@router.delete("/{provider_slug}")
async def delete_provider(
    provider_slug: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Supprime toutes les credentials d'un provider pour le user."""
    uid = _require_user(user_id)
    provider = get_provider(provider_slug)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider inconnu")
    count = 0
    for f in provider.get("fields", []):
        if delete_credential(db, uid, provider_slug, f["key"]):
            count += 1
    return {"success": count > 0, "deleted_count": count}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/credentials/{slug}/test  → re-test avec les valeurs en base
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{provider_slug}/test")
async def test_existing(
    provider_slug: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    uid = _require_user(user_id)
    provider = get_provider(provider_slug)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider inconnu")

    values: dict[str, str] = {}
    for f in provider.get("fields", []):
        val = get_credential(db, uid, provider_slug, f["key"], context="test")
        if val:
            values[f["key"]] = val
    if not values:
        raise HTTPException(status_code=404, detail="Aucune credential enregistree")

    ok, msg = await _run_test_endpoint(provider, values)
    return {"success": ok, "message": msg}
