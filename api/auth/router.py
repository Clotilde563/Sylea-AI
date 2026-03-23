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
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth.models import RegisterIn, LoginIn, TokenOut, UserOut, OAuthIn
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
    return "".join(random.choices(string.digits, k=6))


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

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_email, smtp_password)
        server.send_message(msg)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_conn(db):
    """Extract raw sqlite3 connection from DatabaseManager or use directly."""
    if hasattr(db, 'conn'):
        return db.conn
    return db


def _get_user_by_email(db, email: str) -> dict | None:
    conn = _get_conn(db)
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM users LIMIT 0").description]
    return dict(zip(cols, row))


def _get_user_by_provider(db, provider: str, provider_id: str) -> dict | None:
    conn = _get_conn(db)
    row = conn.execute(
        "SELECT * FROM users WHERE provider = ? AND provider_id = ?",
        (provider, provider_id),
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM users LIMIT 0").description]
    return dict(zip(cols, row))


def _create_user(
    db,
    email: str,
    hashed_password: str | None = None,
    provider: str = "local",
    provider_id: str | None = None,
) -> dict:
    conn = _get_conn(db)
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, provider_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, hashed_password, provider, provider_id, now),
    )
    conn.commit()
    return {"id": user_id, "email": email, "provider": provider}


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(data: RegisterIn, db=Depends(get_db)):
    if len(data.password) < 4:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 4 caracteres)")

    existing = _get_user_by_email(db, data.email)
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
    user = _create_user(db, data.email, pending["password_hash"])
    del pending_verifications[data.email]

    token = create_access_token(user["id"])
    return TokenOut(access_token=token)


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db=Depends(get_db)):
    user = _get_user_by_email(db, data.email)
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

    # Find or create user
    user = _get_user_by_provider(db, "google", google_id)
    if not user:
        # Check if email exists with local account
        existing = _get_user_by_email(db, email)
        if existing:
            # Link Google to existing account
            _get_conn(db).execute(
                "UPDATE users SET provider = 'google', provider_id = ? WHERE id = ?",
                (google_id, existing["id"]),
            )
            _get_conn(db).commit()
            user = existing
        else:
            user = _create_user(db, email, provider="google", provider_id=google_id)

    jwt_token = create_access_token(user["id"])
    return TokenOut(access_token=jwt_token)


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

    # Find or create user
    user = _get_user_by_provider(db, "github", github_id)
    if not user:
        existing = _get_user_by_email(db, email)
        if existing:
            _get_conn(db).execute(
                "UPDATE users SET provider = 'github', provider_id = ? WHERE id = ?",
                (github_id, existing["id"]),
            )
            _get_conn(db).commit()
            user = existing
        else:
            user = _create_user(db, email, provider="github", provider_id=github_id)

    jwt_token = create_access_token(user["id"])
    return TokenOut(access_token=jwt_token)


# ── Me (current user info) ────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def get_me(
    db=Depends(get_db),
    user: dict = Depends(__import__('api.auth.dependencies', fromlist=['require_auth']).require_auth),
):
    row = _get_conn(db).execute("SELECT id, email, provider FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Utilisateur non trouve")
    return UserOut(id=row[0], email=row[1], provider=row[2])
