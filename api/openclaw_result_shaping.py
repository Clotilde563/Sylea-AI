"""
Agent 3 — Shaping des resultats des 38 outils OpenClaw.

Les retours bruts du Gateway OpenClaw (`POST /tools/invoke`) sont des dicts
variables selon le tool. Ce module transforme ces dicts en :
  1. `content_for_llm` : resume textuel court (<2000 chars) injecte comme
     tool_result au LLM. Le LLM doit comprendre en un coup d'oeil.
  2. `action_card` : dict pour l'event SSE `action_done` cote frontend.
     Permet d'afficher une card cliquable (lien, image, telechargement...).

Design : fonction par groupe de tools, table de dispatch. Fallback generique
JSON tronque si le tool n'a pas de shaper dedie.
"""

from __future__ import annotations

import json
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(d: Any, *keys: str, default: Any = None) -> Any:
    """Cherche la premiere cle presente dans `d` parmi `keys`."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _truncate(s: str, max_chars: int = 2000) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + f"… [+{len(s) - max_chars + 20} chars]"


def _fallback_shape(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Shaping par defaut : JSON tronque, pas de card."""
    if result is None:
        return f"Outil '{tool_name}' execute (aucun contenu retourne).", None
    if isinstance(result, dict):
        try:
            dumped = json.dumps(result, ensure_ascii=False, indent=None)
        except (TypeError, ValueError):
            dumped = str(result)
        return _truncate(dumped), None
    return _truncate(str(result)), None


# ─────────────────────────────────────────────────────────────────────────────
# Shapers par groupe
# ─────────────────────────────────────────────────────────────────────────────

def _shape_web_search(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : web_search, firecrawl, perplexity_search, brave_search,
    google_search, tavily_search, exa_search."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    items = _get(result, "results", "items", "data", "hits", default=None) or []
    if not isinstance(items, list):
        return _fallback_shape(tool_name, result)

    summary = _get(result, "summary", "answer", "synthesis", default="")
    lines: list[str] = []
    if summary:
        lines.append(f"Synthese : {str(summary)[:500]}")
    lines.append(f"{len(items)} resultats via {tool_name} :")
    for i, it in enumerate(items[:8]):
        if not isinstance(it, dict):
            continue
        title = str(_get(it, "title", "name", default="(sans titre)"))[:120]
        url = str(_get(it, "url", "link", "href", default=""))
        snippet = str(_get(it, "snippet", "description", "summary", "text", default=""))[:200]
        lines.append(f"- [{title}]({url}) {snippet}")

    content = "\n".join(lines)
    card = {
        "kind": "search_results",
        "tool": tool_name,
        "count": len(items),
        "first_url": str(_get(items[0], "url", "link") or "") if items and isinstance(items[0], dict) else "",
    }
    return _truncate(content, 3000), card


def _shape_web_fetch(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tool : web_fetch (OpenClaw)."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    url = str(_get(result, "url", "final_url", default=""))
    status = _get(result, "status", "status_code", default=None)
    content = str(_get(result, "content", "body", "text", default=""))
    title = str(_get(result, "title", default=""))

    header = f"GET {url} -> {status}" if status else f"GET {url}"
    if title:
        header += f" « {title[:100]} »"
    preview = _truncate(content, 3000)
    card = {
        "kind": "web_fetch",
        "url": url,
        "status": status,
        "size": len(content) if content else 0,
    } if url else None
    return f"{header}\n\n{preview}", card


def _shape_browser(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tool : browser (actions Playwright)."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    url = str(_get(result, "url", "final_url", default=""))
    screenshot = str(_get(result, "screenshot_url", "screenshot", "image_url", default=""))
    extracted = _get(result, "extracted", "data", default=None)
    text = str(_get(result, "text", "content", default=""))

    lines: list[str] = []
    if url:
        lines.append(f"Browser : {url}")
    if screenshot:
        lines.append(f"Capture : {screenshot}")
    if extracted is not None:
        try:
            lines.append(f"Extracted : {json.dumps(extracted, ensure_ascii=False)[:500]}")
        except (TypeError, ValueError):
            pass
    if text:
        lines.append(f"Texte :\n{text[:2000]}")
    content = "\n".join(lines) if lines else str(result)[:2000]
    card = {
        "kind": "browser",
        "url": url or None,
        "screenshot_url": screenshot or None,
    } if (url or screenshot) else None
    return _truncate(content, 3000), card


def _shape_exec(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : exec, bash, process."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    stdout = str(_get(result, "stdout", "output", default=""))
    stderr = str(_get(result, "stderr", "error", default=""))
    exit_code = _get(result, "exit_code", "returncode", "code", default=None)
    command = str(_get(result, "command", "cmd", default=""))

    lines: list[str] = []
    if command:
        lines.append(f"$ {command}")
    if exit_code is not None:
        lines.append(f"Exit code : {exit_code}")
    if stdout:
        lines.append(f"STDOUT :\n{stdout[:2000]}")
    if stderr:
        lines.append(f"STDERR :\n{stderr[:1000]}")
    if not lines:
        return _fallback_shape(tool_name, result)
    content = "\n".join(lines)
    card = {
        "kind": "exec",
        "command": command[:200] or None,
        "exit_code": exit_code,
        "has_stderr": bool(stderr),
    }
    return _truncate(content, 3000), card


def _shape_fs(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : fs_read, fs_write, fs_edit, fs_apply_patch."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    path = str(_get(result, "path", "file", "filename", default=""))
    content_text = str(_get(result, "content", "text", default=""))
    bytes_written = _get(result, "bytes_written", "size", default=None)

    if tool_name == "fs_read":
        header = f"Fichier : {path}" if path else "Lecture fichier"
        body = _truncate(content_text, 3000)
        card = {"kind": "fs_read", "path": path or None, "size": len(content_text)} if path else None
        return f"{header}\n\n{body}" if body else header, card

    # write / edit / apply_patch : operations destructives
    header_parts = [f"Operation {tool_name}"]
    if path:
        header_parts.append(path)
    if bytes_written is not None:
        header_parts.append(f"{bytes_written} octets")
    header = " — ".join(header_parts)
    card = {"kind": "fs_write", "path": path or None, "bytes": bytes_written}
    return header, card


def _shape_image_generate(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tool : image_generate."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    url = str(_get(result, "image_url", "url", default=""))
    b64 = _get(result, "image_base64", "base64", default=None)
    revised_prompt = str(_get(result, "revised_prompt", default=""))
    cost = _get(result, "cost_usd", default=None)

    lines = ["Image generee."]
    if revised_prompt:
        lines.append(f"Prompt retenu : {revised_prompt[:200]}")
    if url:
        lines.append(f"URL : {url}")
    if cost is not None:
        lines.append(f"Cout : ${cost}")
    content = "\n".join(lines)
    card = {
        "kind": "image_generate",
        "image_url": url or None,
        "has_base64": b64 is not None,
        "cost_usd": cost,
    }
    return content, card


def _shape_media_generate(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : music_generate, video_generate, voice_generate."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    url = str(_get(result, "url", "media_url", "audio_url", "video_url", default=""))
    duration = _get(result, "duration_s", "duration", default=None)
    cost = _get(result, "cost_usd", default=None)
    kind = tool_name.replace("_generate", "")

    lines = [f"{kind.capitalize()} genere."]
    if duration is not None:
        lines.append(f"Duree : {duration}s")
    if url:
        lines.append(f"URL : {url}")
    if cost is not None:
        lines.append(f"Cout : ${cost}")
    content = "\n".join(lines)
    card = {
        "kind": tool_name,
        "media_url": url or None,
        "duration_s": duration,
        "cost_usd": cost,
    }
    return content, card


def _shape_image_analysis(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tool : image (analyse vision)."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    description = str(_get(result, "description", "text", "answer", default=""))
    tags = _get(result, "tags", "labels", default=None)
    lines = [f"Analyse image :\n{description[:2000]}"] if description else ["Analyse image effectuee."]
    if isinstance(tags, list) and tags:
        lines.append(f"Tags : {', '.join(str(t) for t in tags[:10])}")
    content = "\n".join(lines)
    return _truncate(content, 3000), {"kind": "image_analysis"}


def _shape_sessions(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : sessions_spawn, sessions_list, sessions_send, sessions_history."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    session_id = str(_get(result, "session_id", "id", default=""))
    status = str(_get(result, "status", default=""))
    sessions = _get(result, "sessions", default=None)
    messages = _get(result, "messages", "history", default=None)

    if tool_name == "sessions_list" and isinstance(sessions, list):
        lines = [f"{len(sessions)} session(s) OpenClaw active(s) :"]
        for s in sessions[:10]:
            if isinstance(s, dict):
                lines.append(f"- {s.get('id', '?')} ({s.get('status', '?')})")
        return "\n".join(lines), {"kind": "sessions_list", "count": len(sessions)}

    if tool_name == "sessions_history" and isinstance(messages, list):
        lines = [f"Historique ({len(messages)} messages) :"]
        for m in messages[-10:]:  # derniers 10
            if isinstance(m, dict):
                role = m.get("role", "?")
                content = str(m.get("content", ""))[:200]
                lines.append(f"[{role}] {content}")
        return _truncate("\n".join(lines), 3000), {"kind": "sessions_history", "count": len(messages)}

    if session_id:
        return (
            f"Session {session_id} : {status or 'ok'}",
            {"kind": "sessions_spawn", "session_id": session_id, "status": status or None},
        )
    return _fallback_shape(tool_name, result)


def _shape_message(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tool : message (multi-canal)."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    channel = str(_get(result, "channel", default=""))
    recipient = str(_get(result, "recipient", "to", default=""))
    ok = bool(_get(result, "ok", "success", "sent", default=True))
    lines = [f"Message {'envoye' if ok else 'echoue'}"]
    if channel:
        lines.append(f"Canal : {channel}")
    if recipient:
        lines.append(f"Destinataire : {recipient}")
    return " — ".join(lines), {
        "kind": "message_sent",
        "channel": channel or None,
        "recipient": recipient or None,
        "ok": ok,
    }


def _shape_safety(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : content_moderation, url_safety_check, pii_scrub."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)

    if tool_name == "content_moderation":
        flagged = bool(_get(result, "flagged", "is_flagged", default=False))
        categories = _get(result, "categories", "flags", default=None)
        lines = [f"Moderation : {'FLAGGED' if flagged else 'OK'}"]
        if flagged and isinstance(categories, (dict, list)):
            lines.append(f"Categories : {json.dumps(categories, ensure_ascii=False)[:300]}")
        return "\n".join(lines), {"kind": "moderation", "flagged": flagged}

    if tool_name == "url_safety_check":
        safe = bool(_get(result, "safe", "is_safe", default=True))
        threats = _get(result, "threats", default=None)
        lines = [f"URL : {'SAFE' if safe else 'DANGER'}"]
        if not safe and threats:
            lines.append(f"Menaces : {json.dumps(threats, ensure_ascii=False)[:300]}")
        return "\n".join(lines), {"kind": "url_safety", "safe": safe}

    if tool_name == "pii_scrub":
        redacted = str(_get(result, "redacted", "text", "cleaned", default=""))
        found = _get(result, "pii_found", "matches", default=None)
        count = len(found) if isinstance(found, list) else 0
        lines = [f"PII scrub : {count} PII detectees"]
        if redacted:
            lines.append(_truncate(redacted, 2000))
        return "\n".join(lines), {"kind": "pii_scrub", "pii_count": count}

    return _fallback_shape(tool_name, result)


def _shape_memory(tool_name: str, result: Any) -> tuple[str, dict | None]:
    """Tools : oc_memory_search, oc_memory_get."""
    if not isinstance(result, dict):
        return _fallback_shape(tool_name, result)
    matches = _get(result, "matches", "results", "items", default=None)
    if isinstance(matches, list):
        lines = [f"{len(matches)} resultat(s) memoire OpenClaw :"]
        for m in matches[:10]:
            if isinstance(m, dict):
                key = m.get("key", "?")
                val = str(m.get("value", ""))[:200]
                lines.append(f"- {key} : {val}")
        return _truncate("\n".join(lines), 3000), {"kind": "memory", "count": len(matches)}
    value = _get(result, "value", default=None)
    if value is not None:
        return f"Memoire : {str(value)[:2000]}", {"kind": "memory"}
    return _fallback_shape(tool_name, result)


# ─────────────────────────────────────────────────────────────────────────────
# Table de dispatch
# ─────────────────────────────────────────────────────────────────────────────

_SHAPERS: dict[str, Any] = {
    # Web / search
    "web_search": _shape_web_search,
    "firecrawl": _shape_web_search,
    "perplexity_search": _shape_web_search,
    "brave_search": _shape_web_search,
    "google_search": _shape_web_search,
    "tavily_search": _shape_web_search,
    "exa_search": _shape_web_search,
    "x_search": _shape_web_search,
    # Web fetch
    "web_fetch": _shape_web_fetch,
    # Browser / UI
    "browser": _shape_browser,
    "canvas": _fallback_shape,  # canvas = rendu visuel, resultat libre
    # Runtime
    "exec": _shape_exec,
    "bash": _shape_exec,
    "process": _shape_exec,
    # Filesystem
    "fs_read": _shape_fs,
    "fs_write": _shape_fs,
    "fs_edit": _shape_fs,
    "fs_apply_patch": _shape_fs,
    # Sessions
    "sessions_spawn": _shape_sessions,
    "sessions_send": _shape_sessions,
    "sessions_list": _shape_sessions,
    "sessions_history": _shape_sessions,
    # Memory
    "oc_memory_search": _shape_memory,
    "oc_memory_get": _shape_memory,
    # Automation
    "oc_cron": _fallback_shape,
    "gateway": _fallback_shape,
    # Messaging
    "message": _shape_message,
    # Media
    "image": _shape_image_analysis,
    "image_generate": _shape_image_generate,
    "music_generate": _shape_media_generate,
    "video_generate": _shape_media_generate,
    "voice_generate": _shape_media_generate,
    # Safety
    "content_moderation": _shape_safety,
    "url_safety_check": _shape_safety,
    "pii_scrub": _shape_safety,
    # Special
    "llm_task": _fallback_shape,
    "lobster": _fallback_shape,
    "subagents": _fallback_shape,
}


def shape_openclaw_result(
    anthropic_tool_name: str, result: Any,
) -> tuple[str, dict | None]:
    """Transforme un retour du Gateway en (content_for_llm, action_card).

    Args:
        anthropic_tool_name : nom Anthropic du tool (ex: 'browser', 'fs_read').
        result : contenu de resp['result'] de `openclaw_invoke_tool`.

    Returns:
        (content, card) ou `content` est le texte pour tool_result LLM,
        `card` est un dict (ou None) pour l'event SSE frontend. Card peut
        contenir : `kind`, `url`, `image_url`, `screenshot_url`, `count`, etc.
    """
    shaper = _SHAPERS.get(anthropic_tool_name, _fallback_shape)
    try:
        content, card = shaper(anthropic_tool_name, result)
    except Exception:
        # Safety net : si un shaper rate, on fallback plutot que crasher.
        content, card = _fallback_shape(anthropic_tool_name, result)
    return content, card


__all__ = ["shape_openclaw_result"]
