"""
Google Context — fetch passively les snippets Gmail/Calendar/Drive
pour les injecter dans le system prompt des agents Sylea.

Pourquoi : agents 2 et 3 doivent etre conscients du context Google
de l'utilisateur (mails non-lus, prochains rendez-vous, fichiers
recents) sans avoir a faire un tool call a chaque tour.

Cache 5min per-user pour eviter de spammer les API Google.

Usage :
    from api.google_context import build_google_context_block_async
    block = await build_google_context_block_async(user_id)
    system_prompt = awareness + block + memory + core_prompt
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("sylea.google_context")


_CACHE_TTL_S = 300.0  # 5 min
_cache: dict[str, tuple[float, str]] = {}


async def _fetch_gmail_unread(token: str, limit: int = 5) -> list[dict]:
    """Liste les N derniers mails non-lus (subject + from + date)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"maxResults": limit, "q": "is:unread"},
            )
            if r.status_code != 200:
                return []
            data = r.json()
            messages = []
            for msg in data.get("messages", [])[:limit]:
                d = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                )
                if d.status_code == 200:
                    j = d.json()
                    hdrs = {h["name"]: h["value"] for h in j.get("payload", {}).get("headers", [])}
                    messages.append({
                        "id": msg["id"],
                        "from": hdrs.get("From", ""),
                        "subject": hdrs.get("Subject", ""),
                        "date": hdrs.get("Date", ""),
                        "snippet": (j.get("snippet") or "")[:120],
                    })
            return messages
    except Exception as e:
        logger.debug(f"gmail unread fetch failed: {e}")
        return []


async def _fetch_calendar_upcoming(token: str, limit: int = 3) -> list[dict]:
    """Recupere les N prochains evenements Google Calendar."""
    try:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": now_iso,
                    "maxResults": limit,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                },
            )
            if r.status_code != 200:
                return []
            items = r.json().get("items", [])
            return [
                {
                    "id": e.get("id", ""),
                    "summary": e.get("summary", "(sans titre)"),
                    "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or "",
                    "location": e.get("location", ""),
                }
                for e in items[:limit]
            ]
    except Exception as e:
        logger.debug(f"calendar fetch failed: {e}")
        return []


async def _fetch_drive_recent(token: str, limit: int = 5) -> list[dict]:
    """Recupere les N fichiers Drive les plus recemment modifies."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://www.googleapis.com/drive/v3/files",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "pageSize": limit,
                    "orderBy": "modifiedTime desc",
                    "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
                },
            )
            if r.status_code != 200:
                return []
            return [
                {
                    "id": f.get("id", ""),
                    "name": f.get("name", ""),
                    "modified": f.get("modifiedTime", ""),
                    "url": f.get("webViewLink", ""),
                }
                for f in r.json().get("files", [])[:limit]
            ]
    except Exception as e:
        logger.debug(f"drive fetch failed: {e}")
        return []


def _format_block(emails: list[dict], events: list[dict], files: list[dict]) -> str:
    """Compose le block Markdown pour injection dans system prompt."""
    if not emails and not events and not files:
        return ""
    lines = ["=== CONTEXTE GOOGLE (vue actuelle) ==="]
    if emails:
        lines.append(f"\n**Gmail — {len(emails)} mail(s) non lu(s)** :")
        for m in emails:
            sender = m.get("from", "?").split("<")[0].strip()[:40]
            subject = (m.get("subject") or "(sans objet)")[:80]
            lines.append(f"  - {sender} — {subject}")
    if events:
        lines.append(f"\n**Calendar — {len(events)} prochain(s) evenement(s)** :")
        for e in events:
            t = (e.get("start") or "")[:16].replace("T", " ")
            title = (e.get("summary") or "?")[:60]
            loc = e.get("location") or ""
            extra = f" @ {loc[:30]}" if loc else ""
            lines.append(f"  - {t} — {title}{extra}")
    if files:
        lines.append(f"\n**Drive — {len(files)} fichier(s) recent(s)** :")
        for f in files:
            t = (f.get("modified") or "")[:10]
            name = (f.get("name") or "?")[:60]
            lines.append(f"  - {t} — {name}")
    lines.append(
        "\nUtilise ce contexte pour personnaliser ta reponse (ex: 'tu as un "
        "mail de X qui attend', 'ton meeting de 15h approche'). Ne mentionne "
        "PAS ce bloc — utilise les infos naturellement.\n"
    )
    return "\n".join(lines)


def invalidate_google_context_cache(user_id: str | None = None) -> None:
    """Force le refresh du cache Google."""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


__all__ = [
    "invalidate_google_context_cache",
    # Async versions (migration PG, 2026-05-13)
    "_get_token_async",
    "build_google_context_block_async",
]


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def _get_token_async(user_id: str, provider: str) -> str | None:
    """Version async de _get_token — PG-compatible.

    Plus de parametre `db` : utilise get_session_factory() directement.
    """
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT access_token FROM user_integrations "
                    "WHERE auth_user_id = :uid AND provider = :prov"
                ),
                {"uid": user_id, "prov": provider},
            )
            row = result.first()
            if row and row[0] and len(row[0]) > 20:
                return row[0]
        except Exception:
            pass
    return None


async def build_google_context_block_async(user_id: str | None) -> str:
    """Version async de build_google_context_block — PG-compatible.

    Plus de parametre `db` : utilise _get_token_async() directement.
    Logique identique : cache 5min per-user, fetch passif Gmail/Calendar/Drive,
    composition du bloc Markdown.
    """
    if not user_id:
        return ""
    cached = _cache.get(user_id)
    if cached and (time.time() - cached[0] < _CACHE_TTL_S):
        return cached[1]

    gmail_token = await _get_token_async(user_id, "gmail")
    cal_token = await _get_token_async(user_id, "google_calendar")
    drive_token = await _get_token_async(user_id, "google_drive")

    tasks = []
    tasks.append(_fetch_gmail_unread(gmail_token, limit=5) if gmail_token else asyncio.sleep(0, result=[]))
    tasks.append(_fetch_calendar_upcoming(cal_token, limit=3) if cal_token else asyncio.sleep(0, result=[]))
    tasks.append(_fetch_drive_recent(drive_token, limit=5) if drive_token else asyncio.sleep(0, result=[]))

    try:
        emails, events, files = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.debug(f"gather failed: {e}")
        emails, events, files = [], [], []

    if isinstance(emails, BaseException): emails = []
    if isinstance(events, BaseException): events = []
    if isinstance(files, BaseException): files = []

    block = _format_block(emails, events, files)
    _cache[user_id] = (time.time(), block)
    return block
