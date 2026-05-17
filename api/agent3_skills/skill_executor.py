"""
ClawHub Skill Executor — Phase 4 Part C.

Dispatcher pour les tool invocations de type `skill_<slug>`.

Quand le LLM invoque `skill_weather(instruction="Quelle meteo a Paris")`,
ce module :
  1. Resout le slug canonique (`weather`) a partir du tool_name
  2. Charge le SKILL.md complet depuis le loader
  3. Retourne au LLM le contenu markdown du SKILL.md + l'instruction formatee,
     en lui demandant d'utiliser les tools natifs disponibles (WEB_FETCH,
     FILE_READ, etc.) pour executer concretement ce que decrit le skill.

Design choice (v1) :
  - On NE lance PAS de subprocess shell depuis ici. Executer `curl` ou
    `bash` a l'aveugle serait dangereux sans sandbox.
  - A la place, on fait du "skill read-back" : le LLM lit le SKILL.md et
    decide lui-meme comment executer (via WEB_FETCH pour curl, etc.).
  - Part E (future) pourrait ajouter un sub-agent avec `exec` tool encadre
    pour les skills qui necessitent vraiment du shell.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from api.agent3_skills.clawhub_loader import (
    get_cache,
    get_skill_body,
    slug_from_tool_name,
    tool_name_for_slug,
    ClawHubSkillMeta,
)

logger = logging.getLogger("sylea.agent3.skill_executor")


_MAX_BODY_CHARS = 6000  # Cap pour le contexte injecte (evite de saturer le LLM)


def _resolve_slug(
    tool_name: str, *, auth_user_id: Optional[str] = None,
) -> Optional[tuple[str, ClawHubSkillMeta]]:
    """Resout `skill_apple_notes` -> ('apple-notes', meta) pour le user donne.

    Comme tool_name_for_slug remplace '-' par '_', la correspondance n'est
    pas toujours injective. On essaie :
      1. Match direct sur chaque meta du cache (comparaison tool_name_for_slug(slug) == tool_name)
      2. Fallback : slug brut apres strip du prefixe
    """
    cache = get_cache()
    metas = cache.get_metas(auth_user_id=auth_user_id)

    # 1) Match exact via tool_name_for_slug
    for m in metas:
        if tool_name_for_slug(m.slug) == tool_name:
            return (m.slug, m)

    # 2) Fallback brut
    raw = slug_from_tool_name(tool_name)
    if raw:
        # Essayer avec les tirets (ex: apple_notes -> apple-notes)
        hyphenated = raw.replace("_", "-")
        for m in metas:
            if m.slug == raw or m.slug == hyphenated:
                return (m.slug, m)

    return None


def _format_body_for_llm(
    meta: ClawHubSkillMeta, body: str, instruction: str,
    credentials_status: list[dict] | None = None,
) -> str:
    """Formate le SKILL.md pour injection dans le tool_result du LLM parent.

    Args:
        credentials_status : liste des credentials requises + leur statut
            [{"env_name": "STRIPE_API_KEY", "has": True|False, "provider": "stripe"}]
    """
    truncated = len(body) > _MAX_BODY_CHARS
    body_shown = body[:_MAX_BODY_CHARS]
    trunc_note = (
        f"\n\n[...SKILL.md tronque a {_MAX_BODY_CHARS} chars sur {len(body)} totaux...]"
        if truncated else ""
    )

    bins_line = ""
    if meta.required_bins:
        bins_line = f"\n- Binaires requis : {', '.join(meta.required_bins)}"
    homepage_line = f"\n- Doc : {meta.homepage}" if meta.homepage else ""

    # Credentials status (skills avec required_env)
    creds_block = ""
    missing_creds: list[str] = []
    if credentials_status:
        creds_lines = []
        for c in credentials_status:
            icon = "✓ dispo" if c["has"] else "✗ MANQUANTE"
            provider_note = f" (provider: {c['provider']})" if c.get("provider") else " (custom)"
            creds_lines.append(f"  - {c['env_name']} — {icon}{provider_note}")
            if not c["has"]:
                missing_creds.append(c["env_name"])
        creds_block = f"\n**Credentials requises :**\n" + "\n".join(creds_lines)

    missing_note = ""
    if missing_creds:
        missing_note = (
            f"\n\n⚠️ Credentials manquantes : {', '.join(missing_creds)}. "
            "Explique a l'utilisateur qu'il doit les configurer dans /credentials "
            "avant que tu puisses utiliser ce skill concretement. Ne pretend PAS "
            "avoir execute l'action si la credential manque — demande-lui de la fournir."
        )

    return (
        f"## Skill : {meta.emoji + ' ' if meta.emoji else ''}{meta.name} (`{meta.slug}`)\n"
        f"\n**Instruction recue :** {instruction}\n"
        f"\n**Description :** {meta.description}"
        f"{bins_line}{homepage_line}{creds_block}\n"
        f"\n---\n\n"
        f"### Contenu du SKILL.md\n\n"
        f"{body_shown}{trunc_note}\n"
        f"\n---\n\n"
        f"**Prochaine etape** : applique les instructions ci-dessus pour accomplir "
        f"la tache. Si le skill utilise `curl`, prefere WEB_FETCH. Si il utilise "
        f"des fichiers, prefere FILE_READ/FILE_CREATE. Si le skill necessite un "
        f"binaire local qui n'est pas dispo (ex: `op`, `obsidian-cli`), explique "
        f"a l'utilisateur comment l'installer. Ne pretend PAS avoir execute ce "
        f"que tu ne peux pas executer."
        f"{missing_note}"
    )


async def _resolve_credentials_status(
    meta: ClawHubSkillMeta, db: Any, auth_user_id: str | None,
) -> list[dict]:
    """Pour chaque env requise par le skill, determine si la credential existe.

    Retourne list[{env_name, has, provider}]. Le provider est soit le slug du
    catalogue curé (ex: "stripe") soit "custom" (namespace clawhub_skill_<slug>).

    Migration PG (2026-05-13) : version async, utilise has_credential_async.
    """
    if not meta.required_env or not auth_user_id or db is None:
        return []
    try:
        from api.credentials import has_credential_async
        from api.providers_registry import get_provider, all_providers
    except Exception:
        return []

    # Heuristique : match le prefixe de la env var au slug du catalogue.
    def _match_provider(env_name: str) -> str | None:
        first = env_name.lower().split("_")[0]
        if get_provider(first) is not None:
            return first
        for p in all_providers(public=False):
            if first in p.get("aliases", []) or first in p["display_name"].lower():
                return p["slug"]
        return None

    out = []
    for env_name in meta.required_env:
        matched = _match_provider(env_name)
        has = False
        if matched:
            # On check sur le premier field requis du provider
            p = get_provider(matched) or {}
            first_field = next(
                (f["key"] for f in p.get("fields", []) if f.get("required")),
                None,
            )
            if first_field:
                try:
                    has = await has_credential_async(auth_user_id, matched, first_field)
                except Exception:
                    has = False
        else:
            # Custom : namespace clawhub_skill_<slug>
            custom_slug = f"clawhub_skill_{meta.slug}"
            try:
                has = await has_credential_async(auth_user_id, custom_slug, env_name)
            except Exception:
                has = False
        out.append({
            "env_name": env_name,
            "has": has,
            "provider": matched,  # None si custom
        })
    return out


_RESERVED_TOOL_INPUT_KEYS = {"auth_user_id", "user_id", "owner_user_id"}


async def dispatch_skill_invocation(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    auth_user_id: Optional[str] = None,
    db: Any = None,
) -> dict[str, Any]:
    """Execute un tool `skill_<slug>` en retournant le SKILL.md + l'instruction.

    Args:
        tool_name: ex. "skill_weather" ou "skill_apple_notes".
        tool_input: {"instruction": str, "parameters": dict?}.
        auth_user_id: isoler la resolution au dossier skills du user (si fourni).
            Seul le CALLER authentifie (dispatcher) peut fournir cet argument.
            Un LLM qui tenterait de pousser "auth_user_id" via tool_input ne
            pourra PAS overrider l'isolation : on ignore les cles reservees.

    Returns:
        {"content": str, "is_error": bool, "raw": dict}
    """
    tool_input = dict(tool_input or {})
    # Defense en profondeur : si le LLM a glisse une cle reservee dans le
    # tool_input, on la retire. L'isolation doit passer EXCLUSIVEMENT par
    # le kwarg `auth_user_id` cote dispatcher.
    for k in _RESERVED_TOOL_INPUT_KEYS:
        tool_input.pop(k, None)
    instruction = str(tool_input.get("instruction", "")).strip()

    resolved = _resolve_slug(tool_name, auth_user_id=auth_user_id)
    if resolved is None:
        return {
            "content": (
                f"Skill introuvable pour tool `{tool_name}`. Le skill a peut-etre "
                "ete desinstalle. Utilise clawhub_search + clawhub_install pour "
                "le reinstaller."
            ),
            "is_error": True,
            "raw": {"tool_name": tool_name},
        }

    slug, meta = resolved

    if not instruction:
        return {
            "content": (
                f"Parametre 'instruction' manquant pour skill `{slug}`. Fournis "
                "une instruction en langage naturel decrivant ce que tu veux faire."
            ),
            "is_error": True,
            "raw": {"slug": slug},
        }

    body = get_skill_body(slug, auth_user_id=auth_user_id)
    if body is None:
        return {
            "content": (
                f"SKILL.md introuvable pour '{slug}' alors que le meta existe. "
                f"Verifie {meta.path}/SKILL.md."
            ),
            "is_error": True,
            "raw": {"slug": slug, "path": str(meta.path)},
        }

    # Status des credentials requises par le skill (si db + user fournis).
    creds_status = await _resolve_credentials_status(meta, db, auth_user_id)

    formatted = _format_body_for_llm(meta, body, instruction, credentials_status=creds_status)
    return {
        "content": formatted,
        "is_error": False,
        "raw": {
            "slug": slug,
            "name": meta.name,
            "is_bundled": meta.is_bundled,
            "path": str(meta.path),
            "required_bins": meta.required_bins,
            "required_env": meta.required_env,
            "credentials_status": creds_status,
            "credentials_missing_count": sum(1 for c in creds_status if not c["has"]),
            "instruction": instruction,
            "parameters": tool_input.get("parameters", {}),
            "truncated": len(body) > _MAX_BODY_CHARS,
            "body_length": len(body),
        },
    }


def is_skill_tool(tool_name: str) -> bool:
    """Retourne True si `tool_name` est un tool `skill_<slug>`."""
    return tool_name.startswith("skill_") and len(tool_name) > len("skill_")


__all__ = [
    "dispatch_skill_invocation",
    "is_skill_tool",
]
