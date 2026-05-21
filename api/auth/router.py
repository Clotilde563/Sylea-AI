"""Authentication routes: register, login, OAuth."""

import os
import random
import smtplib
import string
import uuid
import sqlite3
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.auth.models import RegisterIn, LoginIn, TokenOut, UserOut, OAuthIn, AppleOAuthIn
from api.auth.security import hash_password, verify_password, create_access_token
from api.dependencies import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Pending verifications (in-memory) ────────────────────────────────────────

pending_verifications: dict[str, dict] = {}
# {email: {"code": "123456", "password_hash": "...", "expires": datetime}}


class VerifyCodeIn(BaseModel):
    email: str
    code: str


def _generate_code() -> str:
    """Génère un code de vérification 6 chiffres cryptographiquement sûr.

    Avant : utilisait `random.choices()` qui n'est PAS sûr cryptographiquement
    (mersenne twister prédictible si on observe quelques sorties). Risque : un
    attaquant pouvait potentiellement prédire les codes de récupération.

    Maintenant : `secrets.choice()` utilise os.urandom() (CSPRNG OS-level).
    """
    import secrets
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _cleanup_expired():
    """Remove expired entries from pending_verifications."""
    now = datetime.now(timezone.utc)
    expired = [k for k, v in pending_verifications.items() if v["expires"] < now]
    for k in expired:
        del pending_verifications[k]


def send_verification_email(to_email: str, code: str):
    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_email or not smtp_password:
        # Fallback: just print the code (dev mode)
        print(f"[DEV] Verification code for {to_email}: {code}")
        return

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = "Sylea.AI -- Code de verification"

    body = f"""
    <html>
    <body style="font-family: Arial; background: #0a0a14; color: #e8e8f0; padding: 2rem;">
        <div style="max-width: 400px; margin: 0 auto; text-align: center;">
            <h1 style="color: #60a5fa;">Sylea.AI</h1>
            <p>Votre code de verification :</p>
            <div style="font-size: 2.5rem; font-weight: 700; letter-spacing: 0.5rem; color: #818cf8; margin: 1.5rem 0; padding: 1rem; background: rgba(255,255,255,0.05); border-radius: 12px;">
                {code}
            </div>
            <p style="color: #888;">Ce code expire dans 10 minutes.</p>
        </div>
    </body>
    </html>
    """
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
    except Exception as e:
        # Si l'email échoue, on log l'erreur mais on continue (le code est en mémoire)
        print(f"[SMTP ERROR] Could not send email to {to_email}: {e}")
        print(f"[DEV FALLBACK] Verification code for {to_email}: {code}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_conn(db):
    """Extract raw sqlite3 connection from DatabaseManager or use directly."""
    if hasattr(db, 'conn'):
        return db.conn
    return db


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers async (migration PG, 2026-05-15) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def _get_user_by_email_async(email: str) -> dict | None:
    """Async version — PG-compatible."""
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    factory = _gsf()
    try:
        async with factory() as session:
            result = await session.execute(
                _sa_text("SELECT * FROM users WHERE email = :email"),
                {"email": email},
            )
            row = result.mappings().first()
    except Exception:
        return None
    return dict(row) if row else None


async def _get_user_by_provider_async(provider: str, provider_id: str) -> dict | None:
    """Async version — PG-compatible."""
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    factory = _gsf()
    try:
        async with factory() as session:
            result = await session.execute(
                _sa_text(
                    "SELECT * FROM users WHERE provider = :prov AND provider_id = :pid"
                ),
                {"prov": provider, "pid": provider_id},
            )
            row = result.mappings().first()
    except Exception:
        return None
    return dict(row) if row else None


async def _create_user_async(
    email: str,
    hashed_password: str | None = None,
    provider: str = "local",
    provider_id: str | None = None,
) -> dict:
    """Async version — PG-compatible."""
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    factory = _gsf()
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with factory() as session:
        try:
            await session.execute(
                _sa_text(
                    "INSERT INTO users "
                    "(id, email, hashed_password, provider, provider_id, created_at) "
                    "VALUES (:id, :email, :pw, :prov, :pid, :now)"
                ),
                {
                    "id": user_id, "email": email, "pw": hashed_password,
                    "prov": provider, "pid": provider_id, "now": now,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return {"id": user_id, "email": email, "provider": provider}


async def _upsert_google_integration_async(
    user_id: str,
    services_scopes: dict,
    access_token: str,
    refresh_token: str,
    expires_at: int | str,
    granted_scope: str,
    now_iso: str,
) -> None:
    """Helper async pour upserter les integrations Google apres login OAuth."""
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    factory = _gsf()
    for _svc, _scopes_needed in services_scopes.items():
        if not any(sc in granted_scope for sc in _scopes_needed):
            continue
        async with factory() as session:
            try:
                # SELECT existant
                result = await session.execute(
                    _sa_text(
                        "SELECT id FROM user_integrations "
                        "WHERE auth_user_id = :uid AND provider = :prov"
                    ),
                    {"uid": user_id, "prov": _svc},
                )
                existing = result.first()
                if existing:
                    await session.execute(
                        _sa_text(
                            "UPDATE user_integrations SET access_token = :acc, "
                            "refresh_token = :ref, token_expires_at = :exp, "
                            "scopes = :sc, updated_at = :now "
                            "WHERE auth_user_id = :uid AND provider = :prov"
                        ),
                        {
                            "acc": access_token, "ref": refresh_token,
                            "exp": str(expires_at), "sc": granted_scope,
                            "now": now_iso, "uid": user_id, "prov": _svc,
                        },
                    )
                else:
                    await session.execute(
                        _sa_text(
                            "INSERT INTO user_integrations "
                            "(id, auth_user_id, provider, access_token, refresh_token, "
                            " token_expires_at, scopes, connected_at, updated_at) "
                            "VALUES (:id, :uid, :prov, :acc, :ref, :exp, :sc, :now, :now)"
                        ),
                        {
                            "id": str(uuid.uuid4()), "uid": user_id, "prov": _svc,
                            "acc": access_token, "ref": refresh_token,
                            "exp": str(expires_at), "sc": granted_scope,
                            "now": now_iso,
                        },
                    )
                await session.commit()
            except Exception:
                await session.rollback()


# ═══════════════════════════════════════════════════════════════════════════
#  Sync wrappers (retro-compat pour callers sync/CLI)
# ═══════════════════════════════════════════════════════════════════════════

def _run_async(coro):
    """Helper: execute une coroutine depuis un contexte sync.

    Si on est deja dans un event loop (FastAPI), delegue a un thread separe
    via ThreadPoolExecutor pour eviter le RuntimeWarning 'coroutine never awaited'.
    """
    import asyncio as _aio
    try:
        return _aio.run(coro)
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_aio.run, coro)
            return future.result()


def _get_user_by_email(db, email: str) -> dict | None:
    """Sync wrapper — delegue toujours a async (PG-compatible)."""
    return _run_async(_get_user_by_email_async(email))


def _get_user_by_provider(db, provider: str, provider_id: str) -> dict | None:
    """Sync wrapper — delegue toujours a async (PG-compatible)."""
    return _run_async(_get_user_by_provider_async(provider, provider_id))


def _create_user(
    db,
    email: str,
    hashed_password: str | None = None,
    provider: str = "local",
    provider_id: str | None = None,
) -> dict:
    """Sync wrapper — delegue toujours a async (PG-compatible)."""
    return _run_async(_create_user_async(email, hashed_password, provider, provider_id))


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(data: RegisterIn, db=Depends(get_db)):
    if len(data.password) < 4:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 4 caracteres)")

    existing = await _get_user_by_email_async(data.email)
    if existing:
        raise HTTPException(status_code=409, detail="Un compte existe deja avec cet email")

    # Cleanup expired entries
    _cleanup_expired()

    # Generate 6-digit verification code
    code = _generate_code()
    pending_verifications[data.email] = {
        "code": code,
        "password_hash": hash_password(data.password),
        "expires": datetime.now(timezone.utc) + timedelta(minutes=10),
    }

    # Send verification email
    send_verification_email(data.email, code)

    return {"message": "Code de verification envoye", "requires_verification": True}


@router.post("/verify", response_model=TokenOut)
async def verify_code(data: VerifyCodeIn, db=Depends(get_db)):
    _cleanup_expired()

    pending = pending_verifications.get(data.email)
    if not pending:
        raise HTTPException(status_code=400, detail="Aucune verification en attente pour cet email")

    if pending["expires"] < datetime.now(timezone.utc):
        del pending_verifications[data.email]
        raise HTTPException(status_code=400, detail="Le code a expire. Veuillez vous reinscrire.")

    if pending["code"] != data.code:
        raise HTTPException(status_code=400, detail="Code de verification incorrect")

    # Code is valid — create the user
    user = await _create_user_async(data.email, pending["password_hash"])
    del pending_verifications[data.email]

    token = create_access_token(user["id"])
    return TokenOut(access_token=token)


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db=Depends(get_db)):
    user = await _get_user_by_email_async(data.email)
    if not user or not user.get("hashed_password"):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    if not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token = create_access_token(user["id"])
    return TokenOut(access_token=token)


# ── OAuth Google ──────────────────────────────────────────────────────────────

@router.post("/oauth/google", response_model=TokenOut)
async def oauth_google(data: OAuthIn, db=Depends(get_db)):
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=501, detail="Google OAuth non configure")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": data.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": data.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Code Google invalide")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    # Get user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Impossible de recuperer le profil Google")

    google_user = user_resp.json()
    google_id = google_user.get("id", "")
    email = google_user.get("email", "")

    # Find or create user (async, PG-compatible)
    user = await _get_user_by_provider_async("google", google_id)
    if not user:
        # Check if email exists with local account
        existing = await _get_user_by_email_async(email)
        if existing:
            # Link Google to existing account (async, PG-compatible).
            from sqlalchemy import text as _sa_text
            from api.database import get_session_factory as _gsf
            _factory = _gsf()
            async with _factory() as _session:
                try:
                    await _session.execute(
                        _sa_text(
                            "UPDATE users SET provider = 'google', "
                            "provider_id = :gid WHERE id = :uid"
                        ),
                        {"gid": google_id, "uid": existing["id"]},
                    )
                    await _session.commit()
                except Exception:
                    await _session.rollback()
            user = existing
        else:
            user = await _create_user_async(
                email, provider="google", provider_id=google_id,
            )

    jwt_token = create_access_token(user["id"])

    # Auto-connect Google integrations (Calendar, Gmail, Drive) UNIQUEMENT
    # si le token recu a les scopes etendus. Sinon, ecrire un token "login-only"
    # casse les integrations (Google API renvoie 403 sans les bonnes permissions).
    # On detecte les scopes via la reponse token (`scope` field) puis on n'auto-
    # connecte que les services compatibles. Le user peut completer plus tard via
    # /integrations/google/oauth (flux state='integration', scopes etendus).
    _google_access = token_data.get("access_token", "")
    _google_refresh = token_data.get("refresh_token", "")
    _google_expires = token_data.get("expires_in", 3600)
    _granted_scope = (token_data.get("scope") or "").lower()
    _user_id = user["id"]

    # Mapping provider -> scope requis (au moins UN match suffit)
    _required_scopes = {
        "gmail": ("gmail.readonly", "gmail.send", "gmail.modify"),
        "google_calendar": ("calendar.readonly", "calendar.events", "calendar"),
        # `drive.file` requis pour creer/modifier des fichiers (drive_save).
        # `drive.readonly` seul ne suffit pas pour ecrire.
        "google_drive": ("drive.file", "drive.readonly", "drive"),
    }

    if _google_access:
        _now_iso = datetime.now(timezone.utc).isoformat()
        # Ensure integrations table exists
        try:
            from api.routers.integrations import _ensure_integrations_tables
            _ensure_integrations_tables(db)
        except Exception:
            pass

        # Upsert async pour toutes les integrations Google (compat PG + SQLite).
        try:
            await _upsert_google_integration_async(
                user_id=_user_id,
                services_scopes=_required_scopes,
                access_token=_google_access,
                refresh_token=_google_refresh,
                expires_at=_google_expires,
                granted_scope=_granted_scope,
                now_iso=_now_iso,
            )
        except Exception:
            pass

    return TokenOut(access_token=jwt_token)


# ── OAuth Google URL ──────────────────────────────────────────────────────────

@router.get("/oauth/google/url")
async def google_oauth_url(redirect_uri: str = "", state: str = "login"):
    """Return the Google OAuth consent URL.
    state='login' → scopes basiques (openid/email/profile) — pas de verification Google requise.
    state='integration' → scopes etendus (Calendar/Gmail/Drive) — pour connecter les services."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=501, detail="Google OAuth non configure")

    if not redirect_uri:
        redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:5173/auth/callback")

    # Login = scopes basiques uniquement (pas besoin de verification Google)
    # Integration = scopes etendus (Calendar, Gmail, Drive)
    if state == "integration":
        scope_list = [
            "openid", "email", "profile",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/drive.readonly",
            # `drive.file` permet de creer/modifier les fichiers crees par
            # l'app (pas un acces complet a Drive). Necessaire pour drive_save.
            "https://www.googleapis.com/auth/drive.file",
        ]
    else:
        scope_list = ["openid", "email", "profile"]

    scopes = " ".join(scope_list)

    import urllib.parse
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })

    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


# ── OAuth GitHub URL ──────────────────────────────────────────────────────────

@router.get("/oauth/github/url")
async def github_oauth_url(redirect_uri: str = ""):
    """Return the GitHub OAuth authorization URL."""
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth non configure")

    if not redirect_uri:
        redirect_uri = os.environ.get("GITHUB_REDIRECT_URI", "http://localhost:5173/auth/callback")

    import urllib.parse
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": "github_login",
    })

    return {"url": f"https://github.com/login/oauth/authorize?{params}"}


# ── OAuth GitHub ──────────────────────────────────────────────────────────────

@router.post("/oauth/github", response_model=TokenOut)
async def oauth_github(data: OAuthIn, db=Depends(get_db)):
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=501, detail="GitHub OAuth non configure")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": data.code,
            },
            headers={"Accept": "application/json"},
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Code GitHub invalide")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Token GitHub non obtenu")

    # Get user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails_resp = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if user_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Impossible de recuperer le profil GitHub")

    github_user = user_resp.json()
    github_id = str(github_user.get("id", ""))

    # Get primary email
    email = ""
    if emails_resp.status_code == 200:
        for e in emails_resp.json():
            if e.get("primary"):
                email = e.get("email", "")
                break
    if not email:
        email = github_user.get("email") or f"github-{github_id}@sylea.ai"

    # Find or create user (async, PG-compatible).
    user = await _get_user_by_provider_async("github", github_id)
    if not user:
        existing = await _get_user_by_email_async(email)
        if existing:
            from sqlalchemy import text as _sa_text
            from api.database import get_session_factory as _gsf
            _factory = _gsf()
            async with _factory() as _session:
                try:
                    await _session.execute(
                        _sa_text(
                            "UPDATE users SET provider = 'github', "
                            "provider_id = :gid WHERE id = :uid"
                        ),
                        {"gid": github_id, "uid": existing["id"]},
                    )
                    await _session.commit()
                except Exception:
                    await _session.rollback()
            user = existing
        else:
            user = await _create_user_async(
                email, provider="github", provider_id=github_id,
            )

    jwt_token = create_access_token(user["id"])
    return TokenOut(access_token=jwt_token)


# ── OAuth Apple ───────────────────────────────────────────────────────────────

@router.get("/oauth/apple/url")
async def oauth_apple_url(redirect_uri: str = "", state: str = ""):
    """Génère l'URL d'autorisation Apple. Le frontend redirige l'utilisateur dessus.

    Note : Apple impose `response_mode=form_post` quand scope inclut name/email,
    donc le redirect_uri DOIT pointer vers une URL backend qui accepte POST.
    """
    from api.auth.apple_oauth import build_authorize_url, get_apple_oauth_config

    cfg = get_apple_oauth_config()
    if not cfg["configured"]:
        raise HTTPException(status_code=501, detail="Apple OAuth non configuré")

    if not redirect_uri:
        redirect_uri = os.environ.get("APPLE_REDIRECT_URI", "")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri requis")

    # Génère un state anti-CSRF si non fourni
    if not state:
        state = uuid.uuid4().hex

    url = build_authorize_url(redirect_uri=redirect_uri, state=state)
    return {"url": url, "state": state}


@router.post("/oauth/apple", response_model=TokenOut)
async def oauth_apple(data: AppleOAuthIn, db=Depends(get_db)):
    """Échange un code Apple contre un JWT Syléa.

    Deux modes d'appel selon le canal :
      - Web (Sign in with Apple JS) : le frontend reçoit le code et nous le
        relaie, on échange contre id_token côté serveur (sécurisé : la clé
        privée Apple reste server-side).
      - Native (mobile / desktop natif) : la lib native renvoie déjà l'id_token
        validé Apple ; on peut le passer directement via `id_token` pour éviter
        l'aller-retour /auth/token (ce code reste accepté quand même).

    Au PREMIER login, Apple ne renvoie le nom de l'utilisateur QUE dans le form
    POST initial (pas dans l'id_token). Le frontend doit nous le transmettre
    via `first_name` / `last_name` à ce moment-là.
    """
    from api.auth.apple_oauth import (
        AppleUser,
        exchange_code,
        get_apple_oauth_config,
        verify_id_token,
    )

    cfg = get_apple_oauth_config()
    if not cfg["configured"]:
        raise HTTPException(status_code=501, detail="Apple OAuth non configuré")

    # Mode 1 : id_token déjà fourni (native flow) → vérification directe
    if data.id_token:
        try:
            apple_user: AppleUser = await verify_id_token(data.id_token)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=f"id_token Apple invalide : {e}")
    else:
        # Mode 2 : code → exchange → id_token → verify (web flow)
        if not data.code:
            raise HTTPException(status_code=400, detail="code ou id_token requis")
        redirect_uri = data.redirect_uri or os.environ.get("APPLE_REDIRECT_URI", "")
        if not redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri requis")
        try:
            tokens = await exchange_code(data.code, redirect_uri=redirect_uri)
            apple_user = await verify_id_token(tokens.id_token)
        except (ValueError, RuntimeError) as e:
            # On NE log JAMAIS le code (one-time) ni les tokens
            raise HTTPException(status_code=401, detail=f"Échec auth Apple : {e}")

    apple_id = apple_user.sub
    # Email obligatoire pour créer un compte. Si Apple ne nous le donne pas
    # (cas relais privé révoqué), on génère un placeholder stable.
    email = apple_user.email or f"apple-{apple_id}@privaterelay.appleid.com"

    # 1) Compte Apple déjà lié ?
    user = await _get_user_by_provider_async("apple", apple_id)
    if user:
        jwt_token = create_access_token(user["id"])
        return TokenOut(access_token=jwt_token)

    # 2) Sinon : email déjà connu en local ? On lie le compte.
    existing = await _get_user_by_email_async(email)
    if existing:
        from sqlalchemy import text as _sa_text
        from api.database import get_session_factory as _gsf
        _factory = _gsf()
        async with _factory() as _session:
            try:
                await _session.execute(
                    _sa_text(
                        "UPDATE users SET provider = 'apple', "
                        "provider_id = :aid WHERE id = :uid"
                    ),
                    {"aid": apple_id, "uid": existing["id"]},
                )
                await _session.commit()
            except Exception:
                await _session.rollback()
        user = existing
    else:
        # 3) Création d'un nouveau compte.
        user = await _create_user_async(
            email, provider="apple", provider_id=apple_id,
        )

    jwt_token = create_access_token(user["id"])
    return TokenOut(access_token=jwt_token)


@router.post("/oauth/apple/callback")
async def oauth_apple_form_post_callback(
    request: Request,
    code: str = Form(...),
    state: str = Form(""),
    id_token: str | None = Form(None),
    user: str | None = Form(None),  # JSON string : {"name":{"firstName":"...","lastName":"..."},"email":"..."}
    error: str | None = Form(None),
):
    """Endpoint POST appelé par Apple (form_post mode) après authentification.

    Apple impose `response_mode=form_post` quand scope inclut name/email.
    Le browser de l'utilisateur fait donc un POST vers ce endpoint avec le
    code, l'id_token et les données utilisateur en form-encoded.

    On convertit en redirection 302 GET vers /auth/callback côté frontend
    avec les query params attendus par AuthCallbackPage (state="apple_login",
    code=..., first_name=..., last_name=...).
    """
    import json
    import urllib.parse

    frontend_base = os.environ.get("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")

    if error:
        # Apple renvoie une erreur (ex. user_cancelled_authorize)
        params = urllib.parse.urlencode({
            "error": error,
            "state": state or "apple_login",
        })
        return RedirectResponse(url=f"{frontend_base}/auth/callback?{params}", status_code=303)

    # Parse les infos utilisateur (envoyées uniquement au PREMIER login)
    first_name = ""
    last_name = ""
    if user:
        try:
            user_data = json.loads(user)
            name = user_data.get("name", {}) if isinstance(user_data, dict) else {}
            first_name = name.get("firstName", "") or ""
            last_name = name.get("lastName", "") or ""
        except Exception:
            pass  # Apple peut envoyer du JSON malformé exceptionnellement

    # Force state à apple_login pour que le frontend route correctement
    forwarded_state = state if state.startswith("apple_") else "apple_login"

    params = {
        "code": code,
        "state": forwarded_state,
    }
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name
    if id_token:
        # Optionnel : permet au frontend de vérifier le JWT sans réappel API
        params["id_token"] = id_token

    query = urllib.parse.urlencode(params)
    return RedirectResponse(url=f"{frontend_base}/auth/callback?{query}", status_code=303)


# ── CSRF token (apps natives Tauri/mobile sans gestion cookie cross-origin) ──

@router.get("/csrf-token")
async def get_csrf_token_endpoint():
    """Retourne un token CSRF signé en JSON (sans cookie).

    Utilisé par les clients natifs (Tauri desktop, app mobile) qui ne peuvent
    pas garantir la propagation cross-origin du cookie sylea_csrf.

    Le token retourné est valide pour le mode "signed-token only" du
    CSRFMiddleware : envoyé en header X-CSRF-Token sur les POST/PUT/PATCH/
    DELETE, il est accepté si sa signature HMAC est valide (sans nécessité
    de cookie match).

    Sécurité : la signature HMAC empêche un attaquant de forger un token
    sans connaître SYLEA_CSRF_SECRET. Combinée au Bearer JWT (auth), elle
    offre une protection équivalente au double-submit pour les apps
    natives.
    """
    from api.csrf_middleware import generate_csrf_token
    return {"csrf_token": generate_csrf_token()}


# ── Me (current user info) ────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def get_me(
    db=Depends(get_db),
    user: dict = Depends(__import__('api.auth.dependencies', fromlist=['require_auth']).require_auth),
):
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    _factory = _gsf()
    async with _factory() as _session:
        _result = await _session.execute(
            _sa_text("SELECT id, email, provider FROM users WHERE id = :uid"),
            {"uid": user["id"]},
        )
        row = _result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Utilisateur non trouve")
    return UserOut(id=row[0], email=row[1], provider=row[2])
