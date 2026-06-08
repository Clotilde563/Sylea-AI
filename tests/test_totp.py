"""Tests pour api.auth.totp (RFC 6238 TOTP + backup codes + chiffrement)."""

from __future__ import annotations

import time

import pytest

from api.auth.totp import (
    BackupCode,
    build_provisioning_uri,
    create_setup,
    current_code,
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    generate_secret,
    verify_backup_code,
    verify_code,
    _hotp,
    _base32_decode,
)


# ─── Génération secret ───────────────────────────────────────────────────────

def test_generate_secret_format():
    s = generate_secret()
    assert len(s) >= 32  # 20 bytes en Base32
    # Base32 alphabet
    valid = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert all(c in valid for c in s)


def test_generate_secret_unique():
    secrets = {generate_secret() for _ in range(50)}
    assert len(secrets) == 50  # tous différents


# ─── HOTP / TOTP ─────────────────────────────────────────────────────────────

def test_hotp_rfc4226_vectors():
    """Vecteurs de test RFC 4226 Appendix D."""
    secret = b"12345678901234567890"
    expected = [
        (0, "755224"),
        (1, "287082"),
        (2, "359152"),
        (3, "969429"),
        (4, "338314"),
        (5, "254676"),
        (6, "287922"),
        (7, "162583"),
        (8, "399871"),
        (9, "520489"),
    ]
    for counter, code in expected:
        assert _hotp(secret, counter) == code


def test_current_code_format():
    secret = generate_secret()
    code = current_code(secret)
    assert len(code) == 6
    assert code.isdigit()


def test_verify_code_correct():
    secret = generate_secret()
    code = current_code(secret)
    assert verify_code(secret, code) is True


def test_verify_code_wrong():
    secret = generate_secret()
    assert verify_code(secret, "000000") is False
    assert verify_code(secret, "999999") is False


def test_verify_code_format_validation():
    secret = generate_secret()
    assert verify_code(secret, "") is False
    assert verify_code(secret, "12345") is False  # trop court
    assert verify_code(secret, "1234567") is False  # trop long
    assert verify_code(secret, "12345a") is False  # lettre


def test_verify_code_window_tolerance():
    """Le code généré -30s doit encore être valide (window=1)."""
    from api.auth.totp import _totp_at
    secret = generate_secret()
    code_30s_ago = _totp_at(secret, time.time() - 30)
    assert verify_code(secret, code_30s_ago, window=1) is True


def test_verify_code_outside_window():
    """Le code généré -90s (3 steps) ne doit PAS être valide (window=1)."""
    from api.auth.totp import _totp_at
    secret = generate_secret()
    code_old = _totp_at(secret, time.time() - 90)
    assert verify_code(secret, code_old, window=1) is False


# ─── Provisioning URI ─────────────────────────────────────────────────────────

def test_provisioning_uri_format():
    uri = build_provisioning_uri("ABCD1234", "user@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "Syl%C3%A9a.AI" in uri or "Syléa.AI" in uri  # encoded ou non
    assert "user%40example.com" in uri  # email encoded
    assert "secret=ABCD1234" in uri
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri


def test_provisioning_uri_custom_issuer():
    uri = build_provisioning_uri("S1", "u@e.c", issuer="MyCo")
    assert "MyCo" in uri


# ─── Backup codes ─────────────────────────────────────────────────────────────

def test_generate_backup_codes_count():
    codes = generate_backup_codes(n=10)
    assert len(codes) == 10
    assert all(isinstance(c, BackupCode) for c in codes)


def test_generate_backup_codes_format():
    codes = generate_backup_codes(n=5)
    for c in codes:
        # Format XXXX-XXXX-XX (10 chars + 2 dashes)
        assert len(c.code) == 12
        assert c.code[4] == "-"
        assert c.code[9] == "-"
        # Pas de caractères ambigus
        assert "0" not in c.code
        assert "O" not in c.code
        assert "1" not in c.code or c.code.count("1") == 0
        assert "I" not in c.code


def test_generate_backup_codes_unique():
    codes = generate_backup_codes(n=20)
    raw_codes = {c.code for c in codes}
    assert len(raw_codes) == 20


def test_verify_backup_code_correct():
    codes = generate_backup_codes(n=3)
    for c in codes:
        assert verify_backup_code(c.code, c.hashed) is True


def test_verify_backup_code_wrong():
    codes = generate_backup_codes(n=2)
    assert verify_backup_code("WRONG-CODE-XX", codes[0].hashed) is False


def test_verify_backup_code_case_insensitive():
    codes = generate_backup_codes(n=1)
    # L'utilisateur peut taper en minuscules
    assert verify_backup_code(codes[0].code.lower(), codes[0].hashed) is True


def test_verify_backup_code_handles_garbage():
    assert verify_backup_code("", "") is False
    assert verify_backup_code("foo", "") is False


# ─── Encryption ───────────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip(monkeypatch):
    # Utilise une clé Fernet valide
    from cryptography.fernet import Fernet
    monkeypatch.setenv(
        "SYLEA_CREDENTIALS_MASTER_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    secret = generate_secret()
    encrypted = encrypt_secret(secret)
    assert encrypted != secret  # vraiment chiffré
    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret


def test_encrypt_different_each_time(monkeypatch):
    """Fernet utilise un IV aléatoire → 2 chiffrements du même secret
    donnent 2 ciphertexts différents."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv(
        "SYLEA_CREDENTIALS_MASTER_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    secret = generate_secret()
    e1 = encrypt_secret(secret)
    e2 = encrypt_secret(secret)
    assert e1 != e2  # différents
    assert decrypt_secret(e1) == secret
    assert decrypt_secret(e2) == secret


# ─── Setup flow complet ───────────────────────────────────────────────────────

def test_create_setup_returns_all_fields(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv(
        "SYLEA_CREDENTIALS_MASTER_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    setup = create_setup("user@example.com")
    assert setup.secret_b32  # secret généré
    assert setup.encrypted_secret  # déjà chiffré, prêt DB
    assert setup.provisioning_uri.startswith("otpauth://")
    assert len(setup.backup_codes) == 10
    assert len(setup.backup_codes_hashed) == 10
    # Le secret en clair peut être vérifié avec le code TOTP courant
    assert verify_code(setup.secret_b32, current_code(setup.secret_b32))


def test_create_setup_secret_encryption_works(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv(
        "SYLEA_CREDENTIALS_MASTER_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    setup = create_setup("user@example.com")
    # Le secret encrypté DOIT pouvoir être déchiffré et retomber sur le clair
    assert decrypt_secret(setup.encrypted_secret) == setup.secret_b32
