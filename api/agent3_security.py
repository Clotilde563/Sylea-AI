"""
Agent 3 — Module de securite transverse.

Regroupe les garde-fous appeles par le dispatcher natif :
  - validate_external_url() : anti-SSRF (bloque localhost, IPs privees,
    metadata cloud). Resout le hostname et verifie via `ipaddress` que
    l'IP n'est pas interne.
  - RateLimiter : bucket token in-memory par (user_id, action).
  - audit_log_action() : trace des actions destructives dans
    `agent3_audit_log` pour compliance/debug.
  - ensure_within_base() : path traversal robuste via Path.relative_to.

Voulu aussi legere que possible, sans dependances externes.
Les caches in-memory (rate-limit, resolution DNS) sont adaptes au mode
mono-process. Pour un cluster, basculer sur Redis plus tard.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("sylea.agent3.security")


# ─────────────────────────────────────────────────────────────────────────────
# SSRF / URL validation
# ─────────────────────────────────────────────────────────────────────────────

_DNS_CACHE_TTL = 30.0
_dns_cache: dict[str, tuple[list[str], float]] = {}
_dns_lock = threading.Lock()


def _resolve_host(host: str) -> list[str]:
    """Resout un hostname en IPs, cache 30s. Retourne [] en cas d'echec."""
    now = time.time()
    with _dns_lock:
        cached = _dns_cache.get(host)
        if cached and cached[1] > now:
            return cached[0]
    try:
        infos = socket.getaddrinfo(host, None)
        ips = list({info[4][0] for info in infos})
    except (socket.gaierror, OSError, UnicodeError):
        ips = []
    with _dns_lock:
        _dns_cache[host] = (ips, now + _DNS_CACHE_TTL)
    return ips


def _is_internal_ip(ip_str: str) -> bool:
    """True si l'IP est privee, loopback, link-local, multicast ou metadata cloud."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # format inconnu -> on refuse par defaut

    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    # Blocklist endpoints metadata cloud
    blocked = {
        "169.254.169.254",  # AWS / Azure / GCP IMDS
        "100.100.100.200",  # Alibaba Cloud metadata
        "fd00:ec2::254",    # AWS IMDS IPv6
    }
    if ip_str in blocked:
        return True
    return False


def validate_external_url(
    url: str, *, allowed_schemes: tuple[str, ...] = ("http", "https"),
) -> tuple[bool, str]:
    """Valide qu'une URL est safe pour un fetch externe.

    Retourne (ok, error_message). Si ok=False, le message est pedagogique
    pour le LLM (il peut tenter une autre URL).
    """
    if not url or not isinstance(url, str):
        return False, "URL manquante."
    url = url.strip()
    if len(url) > 2048:
        return False, "URL trop longue (> 2048 chars)."

    try:
        parsed = urlparse(url)
    except ValueError as e:
        return False, f"URL invalide : {e}"

    if parsed.scheme.lower() not in allowed_schemes:
        return False, f"Scheme '{parsed.scheme}' refuse (autorises : {','.join(allowed_schemes)})."

    host = (parsed.hostname or "").lower()
    if not host:
        return False, "Hostname manquant dans l'URL."

    # Refus formats ambigus (IPv6 incomplet, espaces, etc.)
    if " " in host or ".." in host:
        return False, "Hostname malforme."

    # Si c'est deja une IP litterale, on check directement.
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        if _is_internal_ip(str(literal)):
            return False, f"URL pointe vers une IP interne ({host}), refusee."
        return True, ""
    except ValueError:
        pass  # ce n'est pas une IP litterale -> on resout

    # Resolution DNS + check de TOUTES les IPs renvoyees (anti-rebinding).
    ips = _resolve_host(host)
    if not ips:
        return False, f"Impossible de resoudre le hostname '{host}'."
    for ip_str in ips:
        if _is_internal_ip(ip_str):
            return False, (
                f"Hostname '{host}' se resout vers une IP interne ({ip_str}), refuse."
            )
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting (token bucket in-memory)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    """Token bucket per (user_id, action_key). Mono-process.

    Exemple : 30 WEB_FETCH / minute / user.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        user_id: str | None,
        action: str,
        *,
        rate_per_minute: int,
        burst: int | None = None,
    ) -> tuple[bool, float]:
        """Retourne (allowed, retry_after_seconds). user_id=None ignore le limit."""
        if not user_id:
            return True, 0.0
        burst = burst if burst is not None else max(rate_per_minute, 1)
        rate_per_sec = rate_per_minute / 60.0
        key = (user_id, action)
        now = time.time()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=float(burst), last_refill=now)
                self._buckets[key] = b
            # Recharge
            elapsed = now - b.last_refill
            b.tokens = min(float(burst), b.tokens + elapsed * rate_per_sec)
            b.last_refill = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0.0
            needed = 1.0 - b.tokens
            retry = needed / rate_per_sec if rate_per_sec > 0 else 60.0
            return False, retry


# Instance globale partagee par le dispatcher.
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


# Limites par defaut (overridables via env). Pensees pour eviter qu'un LLM
# en boucle spamme les services externes, pas pour un usage humain normal.
DEFAULT_LIMITS: dict[str, int] = {
    "WEB_FETCH": int(os.getenv("AGENT3_RATELIMIT_WEB_FETCH_PER_MIN", "30")),
    "SEARCH": int(os.getenv("AGENT3_RATELIMIT_SEARCH_PER_MIN", "20")),
    "X_SEARCH": int(os.getenv("AGENT3_RATELIMIT_X_SEARCH_PER_MIN", "10")),
    "EMAIL": int(os.getenv("AGENT3_RATELIMIT_EMAIL_PER_MIN", "5")),
    "GMAIL_SEND": int(os.getenv("AGENT3_RATELIMIT_EMAIL_PER_MIN", "5")),
    "CALENDAR_EVENT": int(os.getenv("AGENT3_RATELIMIT_CAL_PER_MIN", "10")),
    "DRIVE_SAVE": int(os.getenv("AGENT3_RATELIMIT_DRIVE_PER_MIN", "10")),
    "CRON": int(os.getenv("AGENT3_RATELIMIT_CRON_PER_MIN", "5")),
    "COMPUTER_USE": int(os.getenv("AGENT3_RATELIMIT_CUSE_PER_MIN", "3")),
}


def check_rate_limit(
    user_id: str | None, action: str,
) -> tuple[bool, float]:
    """Raccourci qui applique la limite par defaut pour l'action donnee.

    Desactive automatiquement sous pytest (PYTEST_CURRENT_TEST defini) ou
    si AGENT3_DISABLE_RATELIMIT=1. Utile pour les tests unitaires qui
    enchainent beaucoup d'appels sans toucher au reseau.
    """
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("AGENT3_DISABLE_RATELIMIT") == "1":
        return True, 0.0
    limit = DEFAULT_LIMITS.get(action, 60)
    return get_rate_limiter().acquire(user_id, action, rate_per_minute=limit)


# ─────────────────────────────────────────────────────────────────────────────
# Audit log des actions destructives
# ─────────────────────────────────────────────────────────────────────────────

_DESTRUCTIVE_ACTIONS: set[str] = {
    "FILE_CREATE", "EMAIL", "GMAIL_SEND", "CALENDAR_EVENT", "DRIVE_SAVE",
    "CRON", "COMPUTER_USE",
    "CLAWHUB_INSTALL", "CLAWHUB_PUBLISH",
}


def is_destructive(action: str) -> bool:
    return action in _DESTRUCTIVE_ACTIONS


_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS agent3_audit_log (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT,
    action_type TEXT NOT NULL,
    action_summary TEXT,
    success INTEGER NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL
)
"""

_AUDIT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_audit_user_time "
    "ON agent3_audit_log(auth_user_id, created_at DESC)"
)


def _ensure_audit_table(db: Any) -> None:
    try:
        db.conn.execute(_AUDIT_DDL)
        db.conn.execute(_AUDIT_INDEX_DDL)
        db.conn.commit()
    except Exception as e:  # pragma: no cover
        logger.debug(f"audit table init failed: {e}")


def _extract_summary(action_input: dict[str, Any]) -> str:
    """Produit un resume textuel sans donnees sensibles pour l'audit log."""
    if not isinstance(action_input, dict):
        return ""
    safe_keys = (
        "to", "subject", "filename", "url", "title", "label",
        "cron_expr", "start", "end", "slug", "name",
    )
    bits: list[str] = []
    for k in safe_keys:
        if k in action_input and action_input[k]:
            val = str(action_input[k])[:120]
            bits.append(f"{k}={val}")
    return " | ".join(bits)[:500]


def audit_log_action(
    db: Any,
    user_id: str | None,
    action_type: str,
    action_input: dict[str, Any],
    *,
    success: bool,
    error_message: str = "",
) -> None:
    """Trace une action destructive dans la table d'audit. Best-effort."""
    if not is_destructive(action_type):
        return
    try:
        _ensure_audit_table(db)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_audit_log "
            "(id, auth_user_id, action_type, action_summary, success, error_message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id or "",
                action_type,
                _extract_summary(action_input),
                1 if success else 0,
                (error_message or "")[:500],
                now,
            ),
        )
        db.conn.commit()
    except Exception as e:  # pragma: no cover
        logger.warning(f"audit log write failed ({action_type}): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Path traversal — verification via relative_to (exception = echappement)
# ─────────────────────────────────────────────────────────────────────────────

def ensure_within_base(candidate: Path, base: Path) -> Path | None:
    """Retourne le chemin resolu si il est a l'interieur de `base`, sinon None.

    Plus robuste que `startswith()` face aux symlinks et differences de
    canonicalisation Windows/Unix.
    """
    try:
        candidate_resolved = candidate.resolve()
        base_resolved = base.resolve()
    except (OSError, RuntimeError):
        return None
    try:
        candidate_resolved.relative_to(base_resolved)
        return candidate_resolved
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Messages d'erreur user-friendly (FR) — evite que l'utilisateur voie des
# stack traces ou des messages httpx/Anthropic en anglais.
# ─────────────────────────────────────────────────────────────────────────────

_HTTP_STATUS_MESSAGES_FR: dict[int, str] = {
    400: "Requete mal formee",
    401: "Authentification requise ou expiree",
    403: "Acces refuse",
    404: "Ressource introuvable",
    408: "Le serveur a mis trop de temps a repondre",
    409: "Conflit (la ressource existe deja ou a ete modifiee)",
    410: "Ressource supprimee definitivement",
    413: "Contenu trop volumineux",
    422: "Donnees invalides",
    429: "Trop de requetes — attends quelques secondes",
    500: "Erreur serveur — reessaie plus tard",
    502: "Service distant temporairement indisponible",
    503: "Service distant surcharge",
    504: "Delai d'attente depasse cote serveur",
}

_EXCEPTION_MESSAGES_FR: dict[str, str] = {
    "ConnectError": "Impossible de joindre le serveur. Verifie ta connexion.",
    "ConnectTimeout": "Connexion trop lente au serveur distant.",
    "ReadTimeout": "Le serveur met trop de temps a repondre.",
    "TimeoutException": "Operation interrompue : delai depasse.",
    "TimeoutError": "Operation interrompue : delai depasse.",
    "PermissionError": "Permissions insuffisantes pour cette operation.",
    "FileNotFoundError": "Fichier introuvable.",
    "OSError": "Erreur systeme de fichier.",
    "JSONDecodeError": "Reponse du serveur illisible.",
    "KeyError": "Champ requis manquant.",
    "ValueError": "Valeur invalide.",
}


def friendly_http_error(status: int, *, context: str = "") -> str:
    """Retourne un message FR pour un status HTTP donne."""
    base = _HTTP_STATUS_MESSAGES_FR.get(status, f"Erreur HTTP {status}")
    if context:
        return f"{base} ({context})"
    return base


def friendly_exception_message(exc: BaseException, *, fallback: str = "Erreur technique") -> str:
    """Traduit une exception Python en message utilisateur FR court."""
    name = type(exc).__name__
    if name in _EXCEPTION_MESSAGES_FR:
        return _EXCEPTION_MESSAGES_FR[name]
    # Heuristiques sur le message lui-meme
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "Operation interrompue : delai depasse."
    if "connection refused" in msg or "could not connect" in msg:
        return "Impossible de joindre le serveur distant."
    if "not found" in msg or "404" in msg:
        return "Ressource introuvable."
    if "permission denied" in msg:
        return "Permissions insuffisantes."
    if "credit balance" in msg or "quota" in msg:
        return "Quota API epuise."
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# Mapping d'erreurs structurees par outil OpenClaw.
#
# Chaque outil a ses cas d'erreur typiques (patterns souvent presents dans le
# message d'erreur renvoye par le Gateway). On les traduit en messages FR
# clairs pour le LLM (qui les verra comme tool_result) et l'utilisateur final.
#
# Format : dict[tool_name, list[(pattern_lowercase, fr_message)]]
# Le pattern est cherche via `pattern in msg.lower()`. Si plusieurs matchs,
# le premier gagne (ordre = priorite).
# ─────────────────────────────────────────────────────────────────────────────

# Patterns communs (cross-tool), essayes en dernier recours.
_COMMON_OPENCLAW_ERRORS: list[tuple[str, str]] = [
    ("rate limit", "Limite d'API atteinte. Reessaie plus tard ou espace les appels."),
    ("quota", "Quota de l'API epuise. Attends la reinitialisation ou augmente le plan."),
    ("unauthorized", "Authentification refusee (cle API invalide ou expiree)."),
    ("forbidden", "Acces refuse par l'API."),
    ("payment required", "API payante — credits epuises ou carte expiree."),
    ("api key", "Cle API manquante ou mal configuree cote Gateway."),
    ("timeout", "Delai d'attente depasse — l'operation est trop longue."),
    ("connection", "Connexion au service distant impossible."),
    ("not found", "Ressource introuvable."),
    ("bad request", "Arguments invalides pour cet outil."),
    ("validation", "Arguments invalides (echec de validation)."),
    ("service unavailable", "Service temporairement indisponible. Reessaie dans quelques secondes."),
]

_OPENCLAW_ERROR_PATTERNS: dict[str, list[tuple[str, str]]] = {
    # ── Browser (Playwright) ──────────────────────────────────────────────
    "browser": [
        ("timeout", "Navigation interrompue : la page a mis trop de temps a charger."),
        ("net::err_name_not_resolved", "Domaine introuvable (DNS)."),
        ("net::err_connection_refused", "Serveur distant refuse la connexion."),
        ("not clickable", "Element non cliquable (hors ecran, bloque par overlay, ou desactive)."),
        ("element not found", "Element introuvable sur la page (selecteur invalide)."),
        ("login", "La page exige une authentification que l'agent ne peut pas fournir."),
        ("captcha", "Captcha detecte — impossible de continuer automatiquement."),
        ("cloudflare", "Challenge Cloudflare detecte — impossible de traverser automatiquement."),
        ("no screenshot", "Impossible de capturer la page (timeout ou protection anti-bot)."),
    ],

    # ── Code execution (shell / bash / process) ───────────────────────────
    "exec": [
        ("command not found", "Commande introuvable dans le PATH."),
        ("permission denied", "Permission refusee pour executer cette commande."),
        ("no such file", "Fichier ou dossier introuvable."),
        ("syntax error", "Erreur de syntaxe dans le script."),
        ("exit code 124", "Commande interrompue par timeout."),
        ("exit code 126", "Commande trouvee mais pas executable."),
        ("exit code 127", "Commande introuvable."),
        ("killed", "Commande interrompue (signal KILL, probablement par limite memoire)."),
        ("segfault", "Erreur de segmentation (segfault) dans le programme."),
    ],
    "bash": [
        ("command not found", "Commande introuvable."),
        ("permission denied", "Permission refusee."),
        ("no such file", "Fichier introuvable."),
        ("session not found", "Session bash fermee ou expiree."),
    ],
    "process": [
        ("no such process", "Processus introuvable (deja termine ?)."),
        ("operation not permitted", "Operation interdite (process protege)."),
    ],

    # ── Filesystem ───────────────────────────────────────────────────────
    "fs_read": [
        ("no such file", "Fichier introuvable."),
        ("permission denied", "Permission refusee en lecture."),
        ("is a directory", "Le chemin cible est un dossier, pas un fichier."),
    ],
    "fs_write": [
        ("permission denied", "Permission refusee en ecriture."),
        ("no space", "Disque plein — impossible d'ecrire."),
        ("read-only", "Systeme de fichiers en lecture seule."),
    ],
    "fs_edit": [
        # Differents formats possibles : "old string not found", "old_string not found"
        ("old string not found", "La chaine a remplacer n'a pas ete trouvee dans le fichier."),
        ("old_string not found", "La chaine a remplacer n'a pas ete trouvee dans le fichier."),
        ("string not found", "La chaine a remplacer n'a pas ete trouvee dans le fichier."),
        ("ambiguous", "La chaine a remplacer apparait plusieurs fois — utilise replace_all=true."),
    ],
    "fs_apply_patch": [
        ("hunk", "Impossible d'appliquer un hunk du patch (fichier modifie entretemps ?)."),
        ("malformed", "Patch mal forme — verifie la syntaxe unified diff."),
    ],

    # ── Media generation ─────────────────────────────────────────────────
    "image_generate": [
        ("content policy", "Prompt refuse par la politique de contenu (violence, NSFW, etc.)."),
        ("safety system", "Prompt bloque par le filtre de securite."),
        ("billing", "Facturation non configuree pour la generation d'images."),
        ("prompt too long", "Prompt trop long pour le modele."),
        ("invalid size", "Taille d'image non supportee."),
    ],
    "music_generate": [
        ("quota", "Quota de generation musicale epuise."),
        ("content policy", "Prompt refuse par la politique de contenu."),
        ("duration", "Duree demandee hors limites du modele."),
    ],
    "video_generate": [
        ("quota", "Quota de generation video epuise."),
        ("duration", "Duree trop longue pour le modele (max generalement 10s)."),
        ("aspect ratio", "Ratio d'aspect non supporte."),
        ("content policy", "Prompt refuse par la politique de contenu."),
    ],
    "voice_generate": [
        ("voice not found", "Voix demandee inconnue."),
        ("text too long", "Texte trop long pour la synthese vocale."),
    ],

    # ── Web search engines ───────────────────────────────────────────────
    "perplexity_search": [
        ("rate limit", "Limite Perplexity atteinte. Reessaie dans une minute."),
        ("invalid_model", "Modele Perplexity demande invalide."),
    ],
    "google_search": [
        ("daily limit exceeded", "Quota SerpAPI journalier epuise."),
        ("invalid api key", "Cle API Google/SerpAPI invalide ou absente."),
    ],
    "brave_search": [
        ("subscription", "Abonnement Brave Search insuffisant pour ce volume."),
    ],
    "tavily_search": [
        ("quota", "Quota Tavily epuise."),
    ],
    "exa_search": [
        ("invalid query", "Query Exa mal formee."),
    ],
    "firecrawl": [
        ("robots.txt", "Le site bloque le crawling via robots.txt."),
        ("too many urls", "Trop d'URLs demandees — reduis `max_pages`."),
        ("scrape failed", "Impossible de parser la page (contenu dynamique ?)."),
    ],

    # ── Messaging (multi-canal) ──────────────────────────────────────────
    "message": [
        ("not configured", "Canal non configure cote Gateway OpenClaw. Configure d'abord la connexion."),
        ("channel not found", "Canal inconnu dans la config du Gateway."),
        ("invalid recipient", "Destinataire invalide (numero WhatsApp, email, handle Slack, etc.)."),
        ("rate limit", "Limite d'envoi atteinte pour ce canal."),
        ("blocked", "Destinataire t'a bloque sur ce canal."),
    ],

    # ── Sessions (sub-agents) ────────────────────────────────────────────
    "sessions_spawn": [
        ("budget exceeded", "Budget du sous-agent depasse."),
        ("max sessions", "Trop de sous-agents actifs en parallele."),
    ],

    # ── Safety ───────────────────────────────────────────────────────────
    "content_moderation": [
        ("api key", "Cle API de moderation manquante cote Gateway."),
    ],
    "url_safety_check": [
        ("api key", "Google Safe Browsing API key manquante cote Gateway."),
    ],

    # ── Auto / cron / gateway ────────────────────────────────────────────
    "oc_cron": [
        ("invalid cron", "Expression cron mal formee (doit etre au format '* * * * *')."),
    ],
    "gateway": [
        ("permission denied", "Operation Gateway protegee (reserve admin)."),
    ],
}


def friendly_openclaw_tool_error(
    tool_anthropic_name: str, raw_error: str, *, fallback: str | None = None,
) -> str:
    """Traduit une erreur du Gateway OpenClaw en message FR user-friendly.

    Args:
        tool_anthropic_name : nom Anthropic du tool (ex: "browser", "fs_read").
        raw_error : message d'erreur tel que retourne par le Gateway.
        fallback : message par defaut si aucun pattern ne match.

    Returns:
        Un message FR court et actionnable. Si aucun pattern specifique ni
        commun ne match, retourne `fallback` ou un message generique.
    """
    if not raw_error:
        return fallback or f"L'outil '{tool_anthropic_name}' a echoue."
    msg_lower = raw_error.lower()

    # 1) Patterns specifiques au tool
    patterns = _OPENCLAW_ERROR_PATTERNS.get(tool_anthropic_name, [])
    for pattern, fr_msg in patterns:
        if pattern in msg_lower:
            return fr_msg

    # 2) Patterns communs (rate limit, quota, unauthorized, ...)
    for pattern, fr_msg in _COMMON_OPENCLAW_ERRORS:
        if pattern in msg_lower:
            return fr_msg

    # 3) Fallback : message generique + extrait de l'erreur brute.
    if fallback:
        return fallback
    return f"L'outil '{tool_anthropic_name}' a echoue : {raw_error[:200]}"


__all__ = [
    "validate_external_url",
    "RateLimiter",
    "get_rate_limiter",
    "check_rate_limit",
    "DEFAULT_LIMITS",
    "is_destructive",
    "audit_log_action",
    "ensure_within_base",
    "friendly_http_error",
    "friendly_exception_message",
    "friendly_openclaw_tool_error",
]
