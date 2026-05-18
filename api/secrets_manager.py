"""
Secrets management — Syléa.AI (sécurité niveau pro).

Abstraction unifiée pour lire les secrets en production sans dépendre de
fichiers `.env` (qui finissent dans les images Docker, les backups, etc.).

Backends supportés (résolution par ordre de priorité) :
  1. HashiCorp Vault           (SYLEA_SECRETS_BACKEND=vault)
  2. AWS Secrets Manager       (SYLEA_SECRETS_BACKEND=aws)
  3. GCP Secret Manager        (SYLEA_SECRETS_BACKEND=gcp)
  4. .env / variables d'env    (SYLEA_SECRETS_BACKEND=env, défaut dev)

Le code applicatif appelle UNIQUEMENT `get_secret("NOM_VARIABLE")` :
les détails (auth Vault, IAM AWS, etc.) sont confinés ici.

Cache LRU local (TTL 5 min) pour éviter de marteler le backend distant à chaque
appel. Les secrets sont sensibles → jamais loggués en clair.

Exemples (production) :
    export SYLEA_SECRETS_BACKEND=vault
    export VAULT_ADDR=https://vault.sylea.ai:8200
    export VAULT_TOKEN=hvs.CAES...
    export VAULT_PATH=secret/data/sylea/prod

    export SYLEA_SECRETS_BACKEND=aws
    export AWS_REGION=eu-west-3
    export AWS_SECRET_NAME=sylea/prod  # nom du secret JSON dans AWS SM

Le `.env` reste autorisé en dev (SYLEA_SECRETS_BACKEND non défini ou =env),
mais en production on impose un backend distant via :
    SYLEA_REQUIRE_REMOTE_SECRETS=true  → crash au boot si =env
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Protocol

logger = logging.getLogger("sylea.secrets_manager")

# Cache local : { name -> (value, expires_at) }
_secret_cache: dict[str, tuple[str | None, float]] = {}
_CACHE_TTL_S = 300  # 5 min — limite la charge sur Vault/AWS/GCP


# ─────────────────────────────────────────────────────────────────────────────
# Interface
# ─────────────────────────────────────────────────────────────────────────────

class SecretsBackend(Protocol):
    """Interface unifiée pour tous les backends."""

    def get(self, name: str) -> str | None: ...
    def name(self) -> str: ...


# ─────────────────────────────────────────────────────────────────────────────
# Backend ENV (.env / variables shell)
# ─────────────────────────────────────────────────────────────────────────────

class EnvBackend:
    """Lecture depuis os.environ — backend par défaut en dev."""

    def get(self, name: str) -> str | None:
        return os.environ.get(name)

    def name(self) -> str:
        return "env"


# ─────────────────────────────────────────────────────────────────────────────
# Backend HashiCorp Vault (KV v2)
# ─────────────────────────────────────────────────────────────────────────────

class VaultBackend:
    """HashiCorp Vault — KV secrets engine v2.

    Auth supportée : token (VAULT_TOKEN) ou AppRole (VAULT_ROLE_ID +
    VAULT_SECRET_ID). En production, préférer AppRole avec rotation auto.

    Le secret est récupéré à `VAULT_PATH` (ex. `secret/data/sylea/prod`),
    qui doit contenir un JSON `{ "data": { "DATABASE_URL": "...", ... } }`.
    """

    def __init__(self):
        try:
            import hvac  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "VaultBackend nécessite `hvac` (pip install hvac). "
                "Ajouter à requirements.txt en production."
            ) from e

        addr = os.environ.get("VAULT_ADDR")
        if not addr:
            raise RuntimeError("VAULT_ADDR manquant — impossible d'utiliser Vault.")

        self._client = hvac.Client(url=addr)
        self._path = os.environ.get("VAULT_PATH", "secret/data/sylea/prod")
        self._mount = os.environ.get("VAULT_MOUNT_POINT", "secret")

        # Auth : token direct ou AppRole
        token = os.environ.get("VAULT_TOKEN")
        role_id = os.environ.get("VAULT_ROLE_ID")
        secret_id = os.environ.get("VAULT_SECRET_ID")

        if token:
            self._client.token = token
        elif role_id and secret_id:
            self._client.auth.approle.login(role_id=role_id, secret_id=secret_id)
        else:
            raise RuntimeError(
                "Vault auth manquante : définir VAULT_TOKEN ou "
                "VAULT_ROLE_ID + VAULT_SECRET_ID"
            )

        if not self._client.is_authenticated():
            raise RuntimeError("Auth Vault échouée — vérifier le token/AppRole.")

        # Cache la lecture du secret (Vault renvoie tout le bundle en un appel)
        self._bundle: dict[str, str] | None = None

    def _load_bundle(self) -> dict[str, str]:
        if self._bundle is not None:
            return self._bundle
        try:
            # KV v2 : path "secret/data/sylea/prod" → lecture via read_secret_version
            # Le hvac normalise : on enlève le /data/ si présent
            normalized = self._path.replace("/data/", "/", 1)
            parts = normalized.split("/", 1)
            mount = parts[0] if len(parts) > 1 else self._mount
            subpath = parts[1] if len(parts) > 1 else self._path

            resp = self._client.secrets.kv.v2.read_secret_version(
                path=subpath, mount_point=mount
            )
            self._bundle = resp["data"]["data"]  # type: ignore[assignment]
        except Exception as e:
            logger.error("Vault read failed for path=%s: %s", self._path, e)
            self._bundle = {}
        return self._bundle  # type: ignore[return-value]

    def get(self, name: str) -> str | None:
        bundle = self._load_bundle()
        return bundle.get(name)

    def name(self) -> str:
        return "vault"


# ─────────────────────────────────────────────────────────────────────────────
# Backend AWS Secrets Manager
# ─────────────────────────────────────────────────────────────────────────────

class AwsSecretsManagerBackend:
    """AWS Secrets Manager — secret stocké au format JSON.

    Le secret AWS doit contenir un objet JSON où chaque clé = nom de variable
    Syléa (DATABASE_URL, JWT_SECRET_KEY, etc.). Lecture cachée au boot.

    Auth : credentials AWS standard (rôles IAM EC2/Fargate, ou clés explicites
    via AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY). Région via AWS_REGION.
    """

    def __init__(self):
        try:
            import boto3  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "AwsSecretsManagerBackend nécessite `boto3` "
                "(pip install boto3). Ajouter à requirements.txt en prod."
            ) from e

        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        secret_name = os.environ.get("AWS_SECRET_NAME")
        if not secret_name:
            raise RuntimeError("AWS_SECRET_NAME manquant.")

        self._client = boto3.client("secretsmanager", region_name=region)
        self._secret_name = secret_name
        self._bundle: dict[str, str] | None = None

    def _load_bundle(self) -> dict[str, str]:
        if self._bundle is not None:
            return self._bundle
        try:
            resp = self._client.get_secret_value(SecretId=self._secret_name)
            raw = resp.get("SecretString") or "{}"
            data = json.loads(raw)
            # Forcer toutes les valeurs en str (AWS renvoie parfois des int/bool)
            self._bundle = {str(k): str(v) for k, v in data.items()}
        except Exception as e:
            logger.error("AWS Secrets Manager read failed for %s: %s",
                         self._secret_name, e)
            self._bundle = {}
        return self._bundle  # type: ignore[return-value]

    def get(self, name: str) -> str | None:
        bundle = self._load_bundle()
        return bundle.get(name)

    def name(self) -> str:
        return "aws"


# ─────────────────────────────────────────────────────────────────────────────
# Backend GCP Secret Manager
# ─────────────────────────────────────────────────────────────────────────────

class GcpSecretManagerBackend:
    """Google Cloud Secret Manager — un secret distinct par variable.

    Conventions : un secret GCP par variable Syléa, nommé
    `sylea-<env>-<NAME>` (ex. `sylea-prod-DATABASE_URL`). Le préfixe est
    paramétrable via GCP_SECRET_PREFIX (défaut `sylea-prod-`).

    Auth : Application Default Credentials (ADC) — fonctionne sur Cloud Run,
    GKE, GCE par rôle IAM attaché. En local, `gcloud auth application-default
    login`.
    """

    def __init__(self):
        try:
            from google.cloud import secretmanager  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "GcpSecretManagerBackend nécessite "
                "`google-cloud-secret-manager`. Ajouter à requirements en prod."
            ) from e

        project = os.environ.get("GCP_PROJECT_ID")
        if not project:
            raise RuntimeError("GCP_PROJECT_ID manquant.")

        self._project = project
        self._prefix = os.environ.get("GCP_SECRET_PREFIX", "sylea-prod-")
        self._client = secretmanager.SecretManagerServiceClient()

    def get(self, name: str) -> str | None:
        try:
            full = f"projects/{self._project}/secrets/{self._prefix}{name}/versions/latest"
            resp = self._client.access_secret_version(request={"name": full})
            return resp.payload.data.decode("utf-8")
        except Exception as e:
            logger.debug("GCP Secret Manager miss for %s: %s", name, e)
            return None

    def name(self) -> str:
        return "gcp"


# ─────────────────────────────────────────────────────────────────────────────
# Factory + API publique
# ─────────────────────────────────────────────────────────────────────────────

_backend: SecretsBackend | None = None


def _make_backend() -> SecretsBackend:
    """Construit le backend une fois au démarrage selon SYLEA_SECRETS_BACKEND."""
    name = (os.environ.get("SYLEA_SECRETS_BACKEND") or "env").strip().lower()
    require_remote = os.environ.get("SYLEA_REQUIRE_REMOTE_SECRETS", "").strip().lower()
    require_remote_active = require_remote in ("1", "true", "yes", "on")

    if name == "env":
        if require_remote_active:
            raise RuntimeError(
                "SYLEA_REQUIRE_REMOTE_SECRETS=true mais SYLEA_SECRETS_BACKEND=env. "
                "Configurer Vault/AWS/GCP en production — refus de démarrer."
            )
        logger.info("[secrets] Backend = env (variables d'environnement)")
        return EnvBackend()

    if name == "vault":
        logger.info("[secrets] Backend = HashiCorp Vault")
        return VaultBackend()

    if name == "aws":
        logger.info("[secrets] Backend = AWS Secrets Manager")
        return AwsSecretsManagerBackend()

    if name == "gcp":
        logger.info("[secrets] Backend = GCP Secret Manager")
        return GcpSecretManagerBackend()

    raise RuntimeError(
        f"SYLEA_SECRETS_BACKEND={name!r} inconnu. "
        "Valeurs valides : env, vault, aws, gcp."
    )


def get_secrets_backend() -> SecretsBackend:
    """Retourne le backend singleton (lazy init)."""
    global _backend
    if _backend is None:
        _backend = _make_backend()
    return _backend


def get_secret(name: str, default: str | None = None) -> str | None:
    """Lecture d'un secret avec cache local (TTL 5 min).

    Stratégie :
      1. Cache local (hit → retour immédiat, pas de RTT réseau)
      2. Backend distant (Vault/AWS/GCP/env)
      3. Fallback `default` si rien trouvé

    Note : le cache est partagé entre tous les workers d'un même process,
    mais PAS entre workers gunicorn distincts (chacun a son cache local).
    Pour des secrets qui doivent changer en live, baisser _CACHE_TTL_S ou
    invalider via `clear_secret_cache(name)`.
    """
    now = time.time()
    cached = _secret_cache.get(name)
    if cached is not None:
        val, expires = cached
        if now < expires:
            return val if val is not None else default

    backend = get_secrets_backend()
    try:
        val = backend.get(name)
    except Exception as e:
        # On NE log JAMAIS la valeur, juste le nom (qui n'est pas sensible)
        logger.warning("[secrets] read failed for %s via %s: %s",
                       name, backend.name(), e)
        val = None

    # Cache même les misses (None) pour éviter de spammer le backend distant
    _secret_cache[name] = (val, now + _CACHE_TTL_S)

    return val if val is not None else default


def get_secret_required(name: str) -> str:
    """Variante stricte : crash si le secret est absent ou vide."""
    val = get_secret(name)
    if not val:
        raise RuntimeError(
            f"Secret obligatoire absent : {name}. "
            f"Configurer via backend {get_secrets_backend().name()}."
        )
    return val


def clear_secret_cache(name: str | None = None) -> None:
    """Invalide le cache (un secret précis ou tout)."""
    if name is None:
        _secret_cache.clear()
    else:
        _secret_cache.pop(name, None)


def get_secret_with_env_override(name: str, default: str | None = None) -> str | None:
    """Variante : env-var locale gagne TOUJOURS sur le backend distant.

    Utile pour les overrides d'urgence ou les tests : on peut forcer une
    valeur via `export NAME=...` sans modifier Vault. Si la variable env
    est absente, on délègue au backend distant via `get_secret`.
    """
    env_val = os.environ.get(name)
    if env_val is not None:
        return env_val
    return get_secret(name, default)


def list_active_backend_info() -> dict[str, Any]:
    """Diagnostic : nom du backend actif (pour /api/health/secrets)."""
    try:
        b = get_secrets_backend()
        return {"backend": b.name(), "cache_size": len(_secret_cache)}
    except Exception as e:
        return {"backend": "error", "error": str(e)}
