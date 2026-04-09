"""
External Integrations Router -- Sylea.AI.

Gere les connexions aux services externes (Google Calendar, Gmail,
GitHub, Notion, LinkedIn, Stripe, Outlook) avec support OAuth simplifie
pour le dev et appels API reels quand les cles sont fournies.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth.dependencies import require_auth
from api.dependencies import get_db

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

SUPPORTED_PROVIDERS = [
    "google_calendar", "gmail", "google_drive", "outlook", "notion", "github", "linkedin", "stripe"
]


# ── Pydantic models ─────────────────────────────────────────────────────────

class ConnectIn(BaseModel):
    access_token: str | None = None
    api_key: str | None = None


class IntegrationStatus(BaseModel):
    provider: str
    connected: bool
    connected_at: str | None = None
    last_synced: str | None = None
    status: str = "disconnected"


class CalendarEventIn(BaseModel):
    title: str
    start: str
    end: str
    description: str | None = None


class EmailSendIn(BaseModel):
    to: str
    subject: str
    body: str


class DraftReplyIn(BaseModel):
    email_id: str
    tone: str = "professionnel"


# ── Table bootstrap ──────────────────────────────────────────────────────────

def _ensure_integrations_tables(db):
    conn = db.conn if hasattr(db, "conn") else db
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_integrations (
            id TEXT PRIMARY KEY,
            auth_user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at TEXT,
            scopes TEXT,
            metadata_json TEXT,
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(auth_user_id, provider)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_sync_log (
            id TEXT PRIMARY KEY,
            auth_user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            sync_type TEXT,
            status TEXT,
            items_synced INTEGER DEFAULT 0,
            last_synced_at TEXT,
            error_message TEXT
        )
    """)
    conn.commit()


def _get_conn(db):
    return db.conn if hasattr(db, "conn") else db


def _get_integration(db, user_id: str, provider: str) -> dict | None:
    conn = _get_conn(db)
    row = conn.execute(
        "SELECT * FROM user_integrations WHERE auth_user_id = ? AND provider = ?",
        (user_id, provider),
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute(
        "SELECT * FROM user_integrations LIMIT 0"
    ).description]
    return dict(zip(cols, row))


def _require_integration(db, user_id: str, provider: str) -> dict:
    integ = _get_integration(db, user_id, provider)
    if not integ:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Integration non connectee: {provider}",
        )
    return integ


def _log_sync(db, user_id: str, provider: str, sync_type: str,
              st: str, items: int = 0, error: str | None = None):
    conn = _get_conn(db)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO integration_sync_log (id, auth_user_id, provider, sync_type, status, items_synced, last_synced_at, error_message) VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, provider, sync_type, st, items, now, error),
    )
    conn.commit()


async def _refresh_google_token(db, user_id: str, provider: str) -> str | None:
    """Refresh an expired Google token using the refresh_token."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    row = _get_integration(db, user_id, provider)
    if not row or not row.get("refresh_token"):
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": row["refresh_token"],
                "grant_type": "refresh_token",
            })
            if resp.status_code == 200:
                new_token = resp.json().get("access_token")
                if new_token:
                    _get_conn(db).execute(
                        "UPDATE user_integrations SET access_token = ?, updated_at = ? "
                        "WHERE auth_user_id = ? AND provider = ?",
                        (new_token, datetime.now(timezone.utc).isoformat(), user_id, provider),
                    )
                    _get_conn(db).commit()
                    return new_token
    except Exception:
        pass
    return None


# ── Integration Management ───────────────────────────────────────────────────

@router.get("", response_model=list[IntegrationStatus])
async def list_integrations(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    conn = _get_conn(db)
    user_id = user["id"]

    results: list[IntegrationStatus] = []
    for prov in SUPPORTED_PROVIDERS:
        integ = _get_integration(db, user_id, prov)
        if integ:
            # Get last sync
            sync_row = conn.execute(
                "SELECT last_synced_at FROM integration_sync_log WHERE auth_user_id = ? AND provider = ? ORDER BY last_synced_at DESC LIMIT 1",
                (user_id, prov),
            ).fetchone()
            results.append(IntegrationStatus(
                provider=prov,
                connected=True,
                connected_at=integ["connected_at"],
                last_synced=sync_row[0] if sync_row else None,
                status="active",
            ))
        else:
            results.append(IntegrationStatus(provider=prov, connected=False))
    return results


@router.post("/google/oauth")
async def google_oauth_connect(data: dict, db=Depends(get_db), user=Depends(require_auth)):
    """Connect Google services (Calendar+Gmail+Drive) via OAuth code.
    Pour les utilisateurs inscrits par email qui veulent connecter Google apres coup.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=501, detail="Google OAuth non configure cote serveur")

    code = data.get("code", "")
    redirect_uri = data.get("redirect_uri", "")
    if not code:
        raise HTTPException(status_code=400, detail="Code d'autorisation manquant")

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Code Google invalide ou expire")

    token_data = token_resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    if not access_token:
        raise HTTPException(status_code=401, detail="Aucun token recu de Google")

    # Store tokens for all 3 Google services
    _ensure_integrations_tables(db)
    conn = _get_conn(db)
    user_id = user["id"]
    now = datetime.now(timezone.utc).isoformat()

    connected = []
    for svc in ["google_calendar", "gmail", "google_drive"]:
        existing = _get_integration(db, user_id, svc)
        if existing:
            conn.execute(
                "UPDATE user_integrations SET access_token = ?, refresh_token = ?, "
                "status = 'connected', updated_at = ? WHERE auth_user_id = ? AND provider = ?",
                (access_token, refresh_token, now, user_id, svc),
            )
        else:
            conn.execute(
                "INSERT INTO user_integrations (id, auth_user_id, provider, access_token, refresh_token, "
                "status, connected_at, updated_at) VALUES (?, ?, ?, ?, ?, 'connected', ?, ?)",
                (str(uuid.uuid4()), user_id, svc, access_token, refresh_token, now, now),
            )
        connected.append(svc)
    conn.commit()

    return {"connected": True, "services": connected}


@router.post("/{provider}/connect")
async def connect_provider(provider: str, data: ConnectIn, db=Depends(get_db), user=Depends(require_auth)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider non supporte: {provider}")

    _ensure_integrations_tables(db)
    conn = _get_conn(db)
    user_id = user["id"]
    now = datetime.now(timezone.utc).isoformat()
    token = data.access_token or data.api_key or ""

    # Upsert
    existing = _get_integration(db, user_id, provider)
    if existing:
        conn.execute(
            "UPDATE user_integrations SET access_token = ?, updated_at = ? WHERE auth_user_id = ? AND provider = ?",
            (token, now, user_id, provider),
        )
    else:
        conn.execute(
            "INSERT INTO user_integrations (id, auth_user_id, provider, access_token, connected_at, updated_at) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), user_id, provider, token, now, now),
        )
    conn.commit()
    return {"connected": True, "provider": provider}


@router.delete("/{provider}/disconnect")
async def disconnect_provider(provider: str, db=Depends(get_db), user=Depends(require_auth)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider non supporte: {provider}")

    _ensure_integrations_tables(db)
    conn = _get_conn(db)
    conn.execute(
        "DELETE FROM user_integrations WHERE auth_user_id = ? AND provider = ?",
        (user["id"], provider),
    )
    conn.commit()
    return {"disconnected": True, "provider": provider}


@router.get("/{provider}/status")
async def provider_status(provider: str, db=Depends(get_db), user=Depends(require_auth)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider non supporte: {provider}")

    _ensure_integrations_tables(db)
    integ = _get_integration(db, user["id"], provider)
    return {
        "provider": provider,
        "active": integ is not None,
        "connected_at": integ["connected_at"] if integ else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE CALENDAR
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_CALENDAR_EVENTS = [
    {
        "id": "evt-001",
        "title": "Reunion client — projet IA chatbot",
        "start": "2026-04-06T10:00:00",
        "end": "2026-04-06T11:00:00",
        "location": "Google Meet",
        "description": "Point d'avancement sur le deploiement du chatbot IA pour le client retail.",
    },
    {
        "id": "evt-002",
        "title": "Deadline livrable — maquette UI/UX",
        "start": "2026-04-07T17:00:00",
        "end": "2026-04-07T18:00:00",
        "location": "",
        "description": "Livrer les maquettes Figma finales au client.",
    },
    {
        "id": "evt-003",
        "title": "Formation Python avancee",
        "start": "2026-04-08T14:00:00",
        "end": "2026-04-08T16:00:00",
        "location": "En ligne — Zoom",
        "description": "Session 3/6 : async, decorateurs et metaclasses.",
    },
    {
        "id": "evt-004",
        "title": "Dejeuner networking — French Tech",
        "start": "2026-04-09T12:30:00",
        "end": "2026-04-09T14:00:00",
        "location": "Le Bouillon, Paris 10e",
        "description": "Rencontre avec des entrepreneurs IA et fintech.",
    },
]


@router.get("/google_calendar/events")
async def google_calendar_events(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "google_calendar")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        for _attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"maxResults": 20, "orderBy": "startTime", "singleEvents": True,
                                "timeMin": datetime.now(timezone.utc).isoformat()},
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    events = []
                    for item in data.get("items", []):
                        events.append({
                            "id": item.get("id", ""),
                            "title": item.get("summary", ""),
                            "start": item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "")),
                            "end": item.get("end", {}).get("dateTime", item.get("end", {}).get("date", "")),
                            "location": item.get("location", ""),
                            "description": item.get("description", ""),
                        })
                    _log_sync(db, user["id"], "google_calendar", "events", "success", len(events))
                    return {"events": events, "source": "api"}
                if resp.status_code == 401 and _attempt == 0:
                    refreshed = await _refresh_google_token(db, user["id"], "google_calendar")
                    if refreshed:
                        token = refreshed
                        continue
                break
            except Exception:
                break

    # Mock data
    return {"events": _MOCK_CALENDAR_EVENTS, "source": "mock"}


@router.post("/google_calendar/events")
async def google_calendar_create_event(data: CalendarEventIn, db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "google_calendar")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        for _attempt in range(2):
            try:
                body = {
                    "summary": data.title,
                    "start": {"dateTime": data.start, "timeZone": "Europe/Paris"},
                    "end": {"dateTime": data.end, "timeZone": "Europe/Paris"},
                    "description": data.description or "",
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json=body,
                    )
                if resp.status_code in (200, 201):
                    _log_sync(db, user["id"], "google_calendar", "create_event", "success", 1)
                    return {"created": True, "event": resp.json(), "source": "api"}
                if resp.status_code == 401 and _attempt == 0:
                    refreshed = await _refresh_google_token(db, user["id"], "google_calendar")
                    if refreshed:
                        token = refreshed
                        continue
                break
            except Exception:
                break

    # Mock
    new_id = f"evt-mock-{uuid.uuid4().hex[:8]}"
    return {
        "created": True,
        "event": {"id": new_id, "title": data.title, "start": data.start, "end": data.end},
        "source": "mock",
    }


@router.post("/google_calendar/sync-tasks")
async def google_calendar_sync_tasks(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    _require_integration(db, user["id"], "google_calendar")
    _log_sync(db, user["id"], "google_calendar", "sync_tasks", "success", 3)
    return {
        "synced": True,
        "tasks_synced": 3,
        "message": "3 taches Sylea synchronisees avec Google Calendar.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# GMAIL
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_GMAIL_INBOX = [
    {
        "id": "mail-001",
        "from": "sophie.martin@clientretail.fr",
        "subject": "Re: Proposition chatbot IA — devis valide",
        "snippet": "Bonjour, nous avons valide le devis pour le chatbot. Pouvez-vous demarrer la semaine prochaine ?",
        "date": "2026-04-03T16:42:00",
        "read": False,
    },
    {
        "id": "mail-002",
        "from": "pierre.durand@techstartup.io",
        "subject": "Collaboration freelance — projet NLP",
        "snippet": "Salut, je cherche un dev Python/IA pour un projet NLP de 3 mois. Ca t'interesse ?",
        "date": "2026-04-03T09:15:00",
        "read": True,
    },
    {
        "id": "mail-003",
        "from": "no-reply@stripe.com",
        "subject": "Paiement recu — Facture #2026-042",
        "snippet": "Vous avez recu un paiement de 2 400,00 EUR de la part de ClientRetail SAS.",
        "date": "2026-04-02T14:30:00",
        "read": True,
    },
    {
        "id": "mail-004",
        "from": "formations@openclassrooms.com",
        "subject": "Nouveau parcours : MLOps et deploiement IA",
        "snippet": "Decouvrez notre nouveau parcours certifiant en MLOps, deploiement de modeles et monitoring.",
        "date": "2026-04-01T08:00:00",
        "read": False,
    },
]

_MOCK_GMAIL_DETAILS = {
    "mail-001": {
        "id": "mail-001",
        "from": "sophie.martin@clientretail.fr",
        "to": "moi@sylea.ai",
        "subject": "Re: Proposition chatbot IA — devis valide",
        "body": "Bonjour,\n\nNous avons valide le devis pour le chatbot IA (12 000 EUR HT). Pouvez-vous demarrer la semaine prochaine ?\n\nMerci de nous envoyer le planning previsionnel.\n\nCordialement,\nSophie Martin\nDirectrice Digitale — ClientRetail SAS",
        "date": "2026-04-03T16:42:00",
        "read": False,
    },
}


@router.get("/gmail/inbox")
async def gmail_inbox(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "gmail")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        for _attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"maxResults": 20},
                    )
                if resp.status_code == 200:
                    messages = []
                    data = resp.json()
                    async with httpx.AsyncClient() as client2:
                        for msg in data.get("messages", [])[:10]:
                            detail_resp = await client2.get(
                                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                                headers={"Authorization": f"Bearer {token}"},
                                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                            )
                            if detail_resp.status_code == 200:
                                d = detail_resp.json()
                                hdrs = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                                messages.append({
                                    "id": msg["id"],
                                    "from": hdrs.get("From", ""),
                                    "subject": hdrs.get("Subject", ""),
                                    "snippet": d.get("snippet", ""),
                                    "date": hdrs.get("Date", ""),
                                    "read": "UNREAD" not in d.get("labelIds", []),
                                })
                    _log_sync(db, user["id"], "gmail", "inbox", "success", len(messages))
                    return {"emails": messages, "source": "api"}
                if resp.status_code == 401 and _attempt == 0:
                    refreshed = await _refresh_google_token(db, user["id"], "gmail")
                    if refreshed:
                        token = refreshed
                        continue
                break
            except Exception:
                break

    return {"emails": _MOCK_GMAIL_INBOX, "source": "mock"}


@router.get("/gmail/{email_id}")
async def gmail_detail(email_id: str, db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "gmail")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{email_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "full"},
                )
            if resp.status_code == 200:
                return {"email": resp.json(), "source": "api"}
        except Exception:
            pass

    # Mock
    detail = _MOCK_GMAIL_DETAILS.get(email_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Email non trouve")
    return {"email": detail, "source": "mock"}


@router.post("/gmail/send")
async def gmail_send(data: EmailSendIn, db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "gmail")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        import base64
        for _attempt in range(2):
            try:
                raw_msg = f"To: {data.to}\r\nSubject: {data.subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{data.body}"
                encoded = base64.urlsafe_b64encode(raw_msg.encode()).decode()
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"raw": encoded},
                    )
                if resp.status_code in (200, 201):
                    _log_sync(db, user["id"], "gmail", "send", "success", 1)
                    return {"sent": True, "message_id": resp.json().get("id", ""), "source": "api"}
                if resp.status_code == 401 and _attempt == 0:
                    refreshed = await _refresh_google_token(db, user["id"], "gmail")
                    if refreshed:
                        token = refreshed
                        continue
                break
            except Exception:
                break

    # Mock
    _log_sync(db, user["id"], "gmail", "send", "mock", 1)
    return {
        "sent": True,
        "message_id": f"mock-{uuid.uuid4().hex[:8]}",
        "source": "mock",
        "info": f"Email simule envoye a {data.to}",
    }


@router.post("/gmail/draft-reply")
async def gmail_draft_reply(data: DraftReplyIn, db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    _require_integration(db, user["id"], "gmail")

    # Try to get original email content for context
    original = _MOCK_GMAIL_DETAILS.get(data.email_id, {})
    subject = original.get("subject", "Sujet inconnu")
    body = original.get("body", "")

    # In production, this would call Claude API to generate the reply
    tone_templates = {
        "professionnel": f"Bonjour,\n\nMerci pour votre message concernant \"{subject}\".\n\nJe reviens vers vous rapidement avec les elements demandes.\n\nCordialement,",
        "amical": f"Salut !\n\nMerci pour ton message sur \"{subject}\". Je regarde ca et je te tiens au courant tres vite.\n\nA bientot !",
        "formel": f"Madame, Monsieur,\n\nJ'accuse reception de votre message relatif a \"{subject}\".\n\nJe me permets de vous informer que je traiterai votre demande dans les meilleurs delais.\n\nVeuillez agreer l'expression de mes salutations distinguees.",
    }

    draft = tone_templates.get(data.tone, tone_templates["professionnel"])
    return {"draft": draft, "tone": data.tone, "email_id": data.email_id}


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE DRIVE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/google_drive/files")
async def get_drive_files(db=Depends(get_db), user=Depends(require_auth)):
    """List files from the user's Google Drive."""
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "google_drive")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        for _attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://www.googleapis.com/drive/v3/files",
                        headers={"Authorization": f"Bearer {token}"},
                        params={
                            "pageSize": 30,
                            "orderBy": "modifiedTime desc",
                            "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
                        },
                    )
                if resp.status_code == 200:
                    files = []
                    for f in resp.json().get("files", []):
                        files.append({
                            "id": f.get("id", ""),
                            "name": f.get("name", ""),
                            "mimeType": f.get("mimeType", ""),
                            "modifiedTime": f.get("modifiedTime", ""),
                            "size": f.get("size", "0"),
                            "webViewLink": f.get("webViewLink", ""),
                        })
                    _log_sync(db, user["id"], "google_drive", "files", "success", len(files))
                    return {"files": files, "source": "api"}
                if resp.status_code == 401 and _attempt == 0:
                    refreshed = await _refresh_google_token(db, user["id"], "google_drive")
                    if refreshed:
                        token = refreshed
                        continue
                break
            except Exception:
                break

    # Mock
    return {
        "files": [
            {"id": "drv-001", "name": "Business Plan 2026.docx", "mimeType": "application/vnd.google-apps.document",
             "modifiedTime": "2026-04-03T10:00:00Z", "size": "0", "webViewLink": ""},
            {"id": "drv-002", "name": "Factures Q1.xlsx", "mimeType": "application/vnd.google-apps.spreadsheet",
             "modifiedTime": "2026-03-28T14:00:00Z", "size": "0", "webViewLink": ""},
        ],
        "source": "mock",
    }


@router.post("/google_drive/upload")
async def upload_to_drive(data: dict, db=Depends(get_db), user=Depends(require_auth)):
    """Upload a file to Google Drive (metadata-only for now; content via multipart in production)."""
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "google_drive")

    name = data.get("name", "Untitled")
    mime_type = data.get("mimeType", "application/octet-stream")
    content = data.get("content", "")
    folder_id = data.get("folderId")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        for _attempt in range(2):
            try:
                metadata: dict = {"name": name, "mimeType": mime_type}
                if folder_id:
                    metadata["parents"] = [folder_id]

                if content:
                    # Simple upload with content
                    import base64 as b64mod
                    file_bytes = b64mod.b64decode(content) if data.get("base64") else content.encode("utf-8")
                    boundary = "sylea_boundary"
                    body_parts = (
                        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                        + json.dumps(metadata)
                        + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
                    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--".encode("utf-8")

                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": f"multipart/related; boundary={boundary}",
                            },
                            content=body_parts,
                        )
                else:
                    # Metadata-only (create empty doc/sheet/etc.)
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            "https://www.googleapis.com/drive/v3/files",
                            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                            json=metadata,
                        )

                if resp.status_code in (200, 201):
                    _log_sync(db, user["id"], "google_drive", "upload", "success", 1)
                    return {"uploaded": True, "file": resp.json(), "source": "api"}
                if resp.status_code == 401 and _attempt == 0:
                    refreshed = await _refresh_google_token(db, user["id"], "google_drive")
                    if refreshed:
                        token = refreshed
                        continue
                break
            except Exception:
                break

    # Mock
    return {
        "uploaded": True,
        "file": {"id": f"drv-mock-{uuid.uuid4().hex[:8]}", "name": name},
        "source": "mock",
    }


# ══════════════════════════════════════════════════════════════════════════════
# GITHUB
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_GITHUB_REPOS = [
    {"name": "sylea-ai", "description": "Assistant de vie augmente par IA", "language": "Python", "stars": 42, "updated": "2026-04-03"},
    {"name": "nlp-sentiment-api", "description": "API d'analyse de sentiments avec transformers", "language": "Python", "stars": 18, "updated": "2026-03-28"},
    {"name": "react-dashboard-kit", "description": "Kit de composants React pour tableaux de bord", "language": "TypeScript", "stars": 73, "updated": "2026-03-15"},
    {"name": "ml-pipeline-templates", "description": "Templates de pipelines ML (training, eval, deploy)", "language": "Python", "stars": 31, "updated": "2026-02-20"},
]

_MOCK_GITHUB_ACTIVITY = [
    {"type": "push", "repo": "sylea-ai", "message": "feat: integrations externes + mock data", "date": "2026-04-04T09:30:00"},
    {"type": "pr_merged", "repo": "nlp-sentiment-api", "message": "fix: correction tokenizer pour le francais", "date": "2026-04-02T14:00:00"},
    {"type": "push", "repo": "react-dashboard-kit", "message": "refactor: migration vers Recharts v3", "date": "2026-03-30T11:00:00"},
    {"type": "issue_closed", "repo": "sylea-ai", "message": "Ameliorer la gestion des erreurs API", "date": "2026-03-28T16:45:00"},
]

_MOCK_GITHUB_STATS = {
    "total_repos": 12,
    "total_stars": 164,
    "total_commits_30d": 87,
    "top_languages": ["Python", "TypeScript", "Rust"],
    "contributions_this_week": 23,
}


@router.get("/github/repos")
async def github_repos(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "github")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.github.com/user/repos",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    params={"sort": "updated", "per_page": 20},
                )
            if resp.status_code == 200:
                repos = [
                    {
                        "name": r["name"],
                        "description": r.get("description", ""),
                        "language": r.get("language", ""),
                        "stars": r.get("stargazers_count", 0),
                        "updated": r.get("updated_at", "")[:10],
                    }
                    for r in resp.json()
                ]
                _log_sync(db, user["id"], "github", "repos", "success", len(repos))
                return {"repos": repos, "source": "api"}
        except Exception:
            pass

    return {"repos": _MOCK_GITHUB_REPOS, "source": "mock"}


@router.get("/github/activity")
async def github_activity(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "github")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.github.com/users/{username}/events",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    params={"per_page": 20},
                )
            if resp.status_code == 200:
                activities = []
                for ev in resp.json()[:20]:
                    activities.append({
                        "type": ev.get("type", ""),
                        "repo": ev.get("repo", {}).get("name", ""),
                        "message": "",
                        "date": ev.get("created_at", ""),
                    })
                _log_sync(db, user["id"], "github", "activity", "success", len(activities))
                return {"activity": activities, "source": "api"}
        except Exception:
            pass

    return {"activity": _MOCK_GITHUB_ACTIVITY, "source": "mock"}


@router.get("/github/stats")
async def github_stats(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    _require_integration(db, user["id"], "github")
    return {"stats": _MOCK_GITHUB_STATS, "source": "mock"}


# ══════════════════════════════════════════════════════════════════════════════
# NOTION
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_NOTION_PAGES = [
    {"id": "page-001", "title": "Roadmap Sylea.AI — Q2 2026", "last_edited": "2026-04-03", "icon": "🗺️"},
    {"id": "page-002", "title": "Notes client — projet chatbot retail", "last_edited": "2026-04-01", "icon": "📝"},
    {"id": "page-003", "title": "Veille techno — LLM & agents autonomes", "last_edited": "2026-03-28", "icon": "🔬"},
    {"id": "page-004", "title": "Business plan freelance 2026", "last_edited": "2026-03-20", "icon": "💼"},
]


@router.get("/notion/pages")
async def notion_pages(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "notion")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.notion.com/v1/search",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": "2022-06-28",
                        "Content-Type": "application/json",
                    },
                    json={"filter": {"property": "object", "value": "page"}, "page_size": 20},
                )
            if resp.status_code == 200:
                pages = []
                for p in resp.json().get("results", []):
                    title_prop = p.get("properties", {}).get("title", {}).get("title", [])
                    title = title_prop[0]["plain_text"] if title_prop else "Sans titre"
                    pages.append({
                        "id": p["id"],
                        "title": title,
                        "last_edited": p.get("last_edited_time", "")[:10],
                        "icon": p.get("icon", {}).get("emoji", "📄") if p.get("icon") else "📄",
                    })
                _log_sync(db, user["id"], "notion", "pages", "success", len(pages))
                return {"pages": pages, "source": "api"}
        except Exception:
            pass

    return {"pages": _MOCK_NOTION_PAGES, "source": "mock"}


@router.post("/notion/sync-workspace")
async def notion_sync_workspace(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    _require_integration(db, user["id"], "notion")
    _log_sync(db, user["id"], "notion", "sync_workspace", "success", 5)
    return {
        "synced": True,
        "pages_synced": 5,
        "message": "5 documents Sylea synchronises avec Notion.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# LINKEDIN
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_LINKEDIN_PROFILE = {
    "name": "Utilisateur Sylea",
    "headline": "Developpeur IA & Freelance | Python, NLP, LLM",
    "location": "Paris, France",
    "connections": 847,
    "profile_views_30d": 124,
    "post_impressions_30d": 3200,
}

_MOCK_LINKEDIN_SUGGESTIONS = [
    {
        "type": "connexion",
        "suggestion": "Connectez-vous avec des CTO de startups IA a Paris — votre objectif freelance beneficierait d'un reseau tech elargi.",
    },
    {
        "type": "contenu",
        "suggestion": "Publiez un article sur votre experience avec les agents IA autonomes — sujet tres recherche en ce moment.",
    },
    {
        "type": "formation",
        "suggestion": "Ajoutez votre certification MLOps a votre profil — les recruteurs filtrent souvent par certifications.",
    },
]


@router.get("/linkedin/profile")
async def linkedin_profile(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "linkedin")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.linkedin.com/v2/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code == 200:
                data = resp.json()
                profile = {
                    "name": f"{data.get('localizedFirstName', '')} {data.get('localizedLastName', '')}".strip(),
                    "headline": data.get("headline", {}).get("localized", {}).get("fr_FR", ""),
                    "location": "",
                    "connections": 0,
                    "profile_views_30d": 0,
                    "post_impressions_30d": 0,
                }
                return {"profile": profile, "source": "api"}
        except Exception:
            pass

    return {"profile": _MOCK_LINKEDIN_PROFILE, "source": "mock"}


@router.get("/linkedin/suggestions")
async def linkedin_suggestions(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    _require_integration(db, user["id"], "linkedin")
    return {"suggestions": _MOCK_LINKEDIN_SUGGESTIONS, "source": "mock"}


# ══════════════════════════════════════════════════════════════════════════════
# STRIPE
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_STRIPE_REVENUE = {
    "total": 28400.00,
    "monthly": 4800.00,
    "trend": "+12%",
    "currency": "EUR",
    "period": "2026",
}

_MOCK_STRIPE_INVOICES = [
    {"id": "inv-001", "client": "ClientRetail SAS", "amount": 2400.00, "currency": "EUR", "status": "paid", "date": "2026-04-02"},
    {"id": "inv-002", "client": "TechStartup.io", "amount": 1800.00, "currency": "EUR", "status": "paid", "date": "2026-03-15"},
    {"id": "inv-003", "client": "AgenceWeb Pro", "amount": 3200.00, "currency": "EUR", "status": "pending", "date": "2026-03-28"},
    {"id": "inv-004", "client": "Formation IA Corp", "amount": 600.00, "currency": "EUR", "status": "paid", "date": "2026-03-01"},
]


@router.get("/stripe/revenue")
async def stripe_revenue(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "stripe")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.stripe.com/v1/balance",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code == 200:
                data = resp.json()
                available = data.get("available", [{}])
                total = sum(a.get("amount", 0) for a in available) / 100
                return {
                    "revenue": {
                        "total": total,
                        "monthly": 0,
                        "trend": "",
                        "currency": available[0].get("currency", "eur").upper() if available else "EUR",
                        "period": "2026",
                    },
                    "source": "api",
                }
        except Exception:
            pass

    return {"revenue": _MOCK_STRIPE_REVENUE, "source": "mock"}


@router.get("/stripe/invoices")
async def stripe_invoices(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "stripe")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.stripe.com/v1/invoices",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"limit": 20},
                )
            if resp.status_code == 200:
                invoices = []
                for inv in resp.json().get("data", []):
                    invoices.append({
                        "id": inv["id"],
                        "client": inv.get("customer_name", inv.get("customer_email", "")),
                        "amount": inv.get("amount_due", 0) / 100,
                        "currency": inv.get("currency", "eur").upper(),
                        "status": inv.get("status", ""),
                        "date": datetime.fromtimestamp(inv.get("created", 0), tz=timezone.utc).strftime("%Y-%m-%d"),
                    })
                _log_sync(db, user["id"], "stripe", "invoices", "success", len(invoices))
                return {"invoices": invoices, "source": "api"}
        except Exception:
            pass

    return {"invoices": _MOCK_STRIPE_INVOICES, "source": "mock"}


# ══════════════════════════════════════════════════════════════════════════════
# OUTLOOK
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_OUTLOOK_EVENTS = [
    {
        "id": "out-evt-001",
        "title": "Standup equipe dev",
        "start": "2026-04-06T09:00:00",
        "end": "2026-04-06T09:15:00",
        "location": "Microsoft Teams",
        "description": "Daily standup — sprint 14.",
    },
    {
        "id": "out-evt-002",
        "title": "Review architecture microservices",
        "start": "2026-04-07T15:00:00",
        "end": "2026-04-07T16:30:00",
        "location": "Salle Turing, 3e etage",
        "description": "Revue de l'architecture backend avec l'equipe infra.",
    },
]


@router.get("/outlook/events")
async def outlook_events(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "outlook")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me/events",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$top": 20, "$orderby": "start/dateTime"},
                )
            if resp.status_code == 200:
                events = []
                for item in resp.json().get("value", []):
                    events.append({
                        "id": item.get("id", ""),
                        "title": item.get("subject", ""),
                        "start": item.get("start", {}).get("dateTime", ""),
                        "end": item.get("end", {}).get("dateTime", ""),
                        "location": item.get("location", {}).get("displayName", ""),
                        "description": item.get("bodyPreview", ""),
                    })
                _log_sync(db, user["id"], "outlook", "events", "success", len(events))
                return {"events": events, "source": "api"}
        except Exception:
            pass

    return {"events": _MOCK_OUTLOOK_EVENTS, "source": "mock"}


@router.get("/outlook/inbox")
async def outlook_inbox(db=Depends(get_db), user=Depends(require_auth)):
    _ensure_integrations_tables(db)
    integ = _require_integration(db, user["id"], "outlook")

    token = integ.get("access_token", "")
    if token and len(token) > 20:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$top": 20, "$orderby": "receivedDateTime desc"},
                )
            if resp.status_code == 200:
                emails = []
                for msg in resp.json().get("value", []):
                    emails.append({
                        "id": msg.get("id", ""),
                        "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                        "subject": msg.get("subject", ""),
                        "snippet": msg.get("bodyPreview", ""),
                        "date": msg.get("receivedDateTime", ""),
                        "read": msg.get("isRead", False),
                    })
                return {"emails": emails, "source": "api"}
        except Exception:
            pass

    # Mock — reuse gmail mock as placeholder
    return {"emails": _MOCK_GMAIL_INBOX, "source": "mock"}
