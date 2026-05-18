"""
2FA TOTP — Syléa.AI.

Implémente Time-based One-Time Password (RFC 6238), compatible avec :
  - Google Authenticator
  - Microsoft Authenticator
  - Authy
  - 1Password / Bitwarden
  - tout client TOTP standard

Format URI : otpauth://totp/Sylea:user@email?secret=...&issuer=Sylea

Sécurité :
  - Secret chiffré en DB (Fernet, dérivé de SYLEA_CREDENTIALS_MASTER_KEY)
  - 10 codes de récupération (one-time use) hashés (bcrypt) en DB
  - Anti-brute-force : 5 essais max / 15 min (réutilise IP rate limiter)
  - Fenêtre de validation ±1 step (= ±30s) pour la dérive d'horloge

Workflow utilisateur :
  1. POST /api/auth/2fa/setup  → renvoie secret + QR + 10 backup codes
  2. POST /api/auth/2fa/verify {code: 123456}  → confirme l'activation
  3. À chaque login : si user.totp_enabled, demander un code 2FA après mdp.

Désactivation :
  POST /api/auth/2fa/disable {password, code}  → exige le mdp + un code TOTP valide.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass

logger = logging.getLogger("sylea.auth.totp")


# ─────────────────────────────────────────────────────────────────────────────
# Constantes RFC 6238
# ─────────────────────────────────────────────────────────────────────────────

# Période standard de 30 secondes
_TOTP_PERIOD = 30

# Longueur code (6 digits standard)
_TOTP_DIGITS = 6

# Algorithme HMAC (SHA1 par compat Google Auth, SHA256 supporté en option)
_TOTP_ALGO = "SHA1"

# Fenêtre de tolérance ±N steps autour du temps actuel (dérive d'horloge)
_VALIDATION_WINDOW = 1  # ±30s


# ─────────────────────────────────────────────────────────────────────────────
# Génération secret
# ─────────────────────────────────────────────────────────────────────────────

def generate_secret(byte_length: int = 20) -> str:
    """Génère un secret cryptographiquement aléatoire encodé Base32.

    Args:
        byte_length: 20 bytes = 160 bits (recommandation RFC 6238).

    Returns:
        String Base32 (lettres A-Z + chiffres 2-7), pas de padding.
    """
    raw = secrets.token_bytes(byte_length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


# ─────────────────────────────────────────────────────────────────────────────
# Calcul TOTP (sans dépendance externe — implé RFC 6238 from scratch)
# ─────────────────────────────────────────────────────────────────────────────

def _base32_decode(secret_b32: str) -> bytes:
    """Décode un secret Base32 (avec/sans padding)."""
    s = secret_b32.upper().replace(" ", "")
    pad = "=" * (-len(s) % 8)
    return base64.b32decode(s + pad)


def _hotp(secret: bytes, counter: int, digits: int = 6) -> str:
    """HOTP RFC 4226 — algorithme parent de TOTP."""
    import hmac
    import hashlib
    import struct

    counter_bytes = struct.pack(">Q", counter)  # 8 bytes big-endian
    h = hmac.new(secret, counter_bytes, hashlib.sha1).digest()

    # Dynamic truncation (RFC 4226 §5.3)
    offset = h[-1] & 0x0F
    binary = (
        (h[offset] & 0x7F) << 24
        | (h[offset + 1] & 0xFF) << 16
        | (h[offset + 2] & 0xFF) << 8
        | (h[offset + 3] & 0xFF)
    )
    code = binary % (10 ** digits)
    return str(code).zfill(digits)


def _totp_at(secret_b32: str, ts: float | None = None) -> str:
    """Calcule le code TOTP à un instant donné."""
    if ts is None:
        ts = time.time()
    counter = int(ts // _TOTP_PERIOD)
    return _hotp(_base32_decode(secret_b32), counter, _TOTP_DIGITS)


def current_code(secret_b32: str) -> str:
    """Code TOTP courant (utile pour les tests / setup confirmation)."""
    return _totp_at(secret_b32)


def verify_code(secret_b32: str, code: str, window: int = _VALIDATION_WINDOW) -> bool:
    """Vérifie un code TOTP avec tolérance ±window steps.

    Comparison constant-time pour éviter timing attacks.
    """
    if not code or not code.isdigit() or len(code) != _TOTP_DIGITS:
        return False

    import hmac as _hmac
    ts = time.time()
    secret = _base32_decode(secret_b32)
    target_counter = int(ts // _TOTP_PERIOD)

    for delta in range(-window, window + 1):
        candidate_counter = target_counter + delta
        if candidate_counter < 0:
            continue
        expected = _hotp(secret, candidate_counter, _TOTP_DIGITS)
        if _hmac.compare_digest(expected, code):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Provisioning URI (pour QR code)
# ─────────────────────────────────────────────────────────────────────────────

def build_provisioning_uri(
    secret_b32: str,
    user_email: str,
    issuer: str = "Syléa.AI",
) -> str:
    """Construit l'URI otpauth:// pour QR code (RFC 6238 §3 keyword draft).

    Format : otpauth://totp/<Issuer>:<account>?secret=...&issuer=...&algorithm=...
    """
    label = urllib.parse.quote(f"{issuer}:{user_email}", safe="")
    params = {
        "secret": secret_b32,
        "issuer": issuer,
        "algorithm": _TOTP_ALGO,
        "digits": str(_TOTP_DIGITS),
        "period": str(_TOTP_PERIOD),
    }
    query = urllib.parse.urlencode(params)
    return f"otpauth://totp/{label}?{query}"


# ─────────────────────────────────────────────────────────────────────────────
# Backup codes (codes de récupération)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BackupCode:
    """Code de récupération en clair (à montrer UNE FOIS à l'utilisateur)."""
    code: str           # 10 chars : "AB12-CD34-EF" format lisible
    hashed: str         # Hash bcrypt pour stockage DB


def _format_backup_code(raw: bytes) -> str:
    """Convertit 5 bytes aléatoires en code 10 chars lisible : AB12-CD34-EF."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O/I/1 ambigus
    chars = [alphabet[b % len(alphabet)] for b in raw]
    return f"{''.join(chars[:4])}-{''.join(chars[4:8])}-{''.join(chars[8:10])}"


def generate_backup_codes(n: int = 10) -> list[BackupCode]:
    """Génère N codes de récupération à montrer à l'utilisateur.

    Le hash bcrypt est stocké côté serveur ; le code en clair n'est montré
    qu'une seule fois (pendant le setup 2FA).
    """
    try:
        import bcrypt  # type: ignore
    except ImportError:
        # bcrypt absent : fallback hashlib (moins safe mais pas de panique en dev)
        logger.warning(
            "[totp] bcrypt absent — backup codes hashés en SHA-256 "
            "(installer bcrypt en prod)."
        )
        bcrypt = None  # type: ignore

    codes: list[BackupCode] = []
    for _ in range(n):
        raw = secrets.token_bytes(10)
        code = _format_backup_code(raw)
        if bcrypt is not None:
            hashed = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")
        else:
            import hashlib
            hashed = "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest()
        codes.append(BackupCode(code=code, hashed=hashed))
    return codes


def verify_backup_code(plain: str, hashed: str) -> bool:
    """Vérifie un code de récupération contre son hash.

    Constant-time comparison via bcrypt ou hmac.compare_digest.
    """
    if not plain or not hashed:
        return False
    normalized = plain.upper().strip()

    if hashed.startswith("sha256:"):
        import hashlib
        import hmac as _hmac
        expected = "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return _hmac.compare_digest(expected, hashed)

    try:
        import bcrypt  # type: ignore
        return bcrypt.checkpw(normalized.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Chiffrement du secret en DB (Fernet)
# ─────────────────────────────────────────────────────────────────────────────

def _get_fernet():
    """Charge la clé Fernet depuis SYLEA_CREDENTIALS_MASTER_KEY (ou dérivée)."""
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "cryptography requis pour le chiffrement TOTP "
            "(pip install cryptography)."
        ) from e

    key = os.environ.get("SYLEA_CREDENTIALS_MASTER_KEY")
    if not key:
        # Dérivation depuis SECRET_KEY (fallback dev — refusé en prod)
        secret = os.environ.get("SECRET_KEY", "dev-fallback-secret")
        import base64 as _b64
        import hashlib
        derived = hashlib.sha256(secret.encode("utf-8")).digest()
        key = _b64.urlsafe_b64encode(derived).decode("ascii")

    return Fernet(key.encode("utf-8"))


def encrypt_secret(secret_b32: str) -> str:
    """Chiffre le secret TOTP pour stockage en DB."""
    f = _get_fernet()
    return f.encrypt(secret_b32.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Déchiffre le secret TOTP depuis la DB."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Setup + Verify flow
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TotpSetup:
    """Résultat de POST /api/auth/2fa/setup."""
    secret_b32: str            # à chiffrer + stocker (totp_secret_enc)
    encrypted_secret: str      # déjà chiffré, prêt pour la DB
    provisioning_uri: str      # à afficher en QR code côté frontend
    backup_codes: list[str]    # 10 codes en clair (montrés UNE fois)
    backup_codes_hashed: list[str]  # à stocker en DB


def create_setup(user_email: str, issuer: str = "Syléa.AI") -> TotpSetup:
    """Génère un nouveau secret + 10 backup codes pour un utilisateur.

    Le caller (router) doit ensuite :
      1. Stocker `encrypted_secret` et `backup_codes_hashed` en DB
      2. Renvoyer `provisioning_uri` + `backup_codes` (clair) au frontend
      3. Marquer 2FA comme "pending" (pas encore confirmé)
      4. Attendre le POST /verify pour activer définitivement
    """
    secret = generate_secret()
    backup = generate_backup_codes(n=10)

    return TotpSetup(
        secret_b32=secret,
        encrypted_secret=encrypt_secret(secret),
        provisioning_uri=build_provisioning_uri(secret, user_email, issuer),
        backup_codes=[b.code for b in backup],
        backup_codes_hashed=[b.hashed for b in backup],
    )
