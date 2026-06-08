"""
Presence + Engagement middleware — Syléa.AI.

Fix bug "Agent companion hallucine 'X jours sans nouvelles' alors que
l'utilisateur est actif sur l'app" :

Avant ce middleware, le seul moyen pour le backend de savoir que
l'utilisateur etait actif etait via `agent_messages` (chat) ou `decisions`
(analyse confirmee). Si l'utilisateur browsait dashboard / stats / tracking
sans ecrire de message ni creer de decision, il etait considere "absent".

Ce middleware touche `users.last_seen_at` sur CHAQUE requete authentifiee
(presence), et `users.last_engaged_at` sur les requetes mutatives (action).

## Architecture des 3 timestamps utilisateur (semantique Niveau 3)

Le code distingue maintenant 3 concepts qui etaient melanges :

| Timestamp                          | Source                      | Signal                                  |
|------------------------------------|-----------------------------|----------------------------------------|
| `users.last_seen_at`               | Ce middleware (TOUS verbs) | Presence : "tab ouvert / app lancee"   |
| `users.last_engaged_at`            | Ce middleware (POST/PUT/  | Action : "user fait qqch d'actif"      |
|                                    | PATCH/DELETE)              |                                        |
| `agent_messages.created_at` (user) | Endpoint chat companion    | Conversation : "user parle a l'agent"  |
| `decisions.cree_le`                | Endpoint dilemme/confirmer | Decision metier : "user a tranche"     |

L'agent companion utilise les 4 mais avec une priorite differente : presence
est le signal #1 pour eviter les faux "absent depuis X jours".

## Perfs

- **Debounce in-memory** : on ne touche la DB que si la derniere mise a jour
  pour cet user date de plus de `DEBOUNCE_SECONDS` (defaut 5 min).
- **Fire-and-forget** : l'UPDATE est `await` mais en cas d'echec on swallow
  l'exception (jamais bloquer la reponse user).
- **In-process dict** : OK en mono-instance. En multi-instance (k8s), chaque
  pod debounce independamment, mais comme le pire cas = X writes/min/user
  ou X = nombre de pods, l'impact reste negligeable.

## Securite

- N'attache **AUCUN cout** pour les requetes anonymes (early return).
- Decode JWT en silencieux : si token invalide, on log pas (la suite du
  pipeline traitera l'erreur 401 si endpoint le requiert).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Mutating HTTP methods qui signalent un "engagement" actif user.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Debounce : on ne touche la DB que si plus de X secondes depuis le dernier
# touch pour cet user. 300s = 5 min = compromis entre granularite et cost.
DEBOUNCE_SECONDS = 300

# Endpoints a EXCLURE du tracking presence (eviter pollution / bruit).
# - /api/health/* : liveness probes
# - WebSocket /ws/* : pas de cycle requete/reponse classique
# - /api/auth/refresh : appel automatique, ne reflete pas une vraie activite
_EXCLUDED_PATH_PREFIXES = (
    "/api/health",
    "/ws/",
    "/api/auth/refresh",
)


class PresenceMiddleware(BaseHTTPMiddleware):
    """Track presence (last_seen_at) + engagement (last_engaged_at) sur users.

    Touche la DB en debounced fire-and-forget apres que la reponse soit prete,
    pour ne JAMAIS bloquer ou ralentir une requete user.
    """

    # Au-dela de ce nombre d'entrees, on purge les plus anciennes (anti-OOM
    # multi-tenant : sans ca, le dict grossit d'1 entree par user a vie).
    _MAX_ENTRIES = 50_000

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        # debounce : auth_user_id -> (last_seen_touch_ts, last_engaged_touch_ts)
        # Stocke en seconds-epoch pour comparaison cheap.
        self._last_seen_touch: dict[str, float] = {}
        self._last_engaged_touch: dict[str, float] = {}

    def _evict_if_needed(self) -> None:
        """Purge anti-OOM : si un dict depasse _MAX_ENTRIES, on retire les
        entrees les plus anciennes (celles dont le dernier touch est le plus
        vieux que le debounce — elles seront re-touchees au prochain hit)."""
        cutoff = time.time() - DEBOUNCE_SECONDS
        for d in (self._last_seen_touch, self._last_engaged_touch):
            if len(d) > self._MAX_ENTRIES:
                stale = [k for k, ts in d.items() if ts < cutoff]
                for k in stale:
                    d.pop(k, None)
                # Si toujours trop gros (tous recents), on coupe brutalement
                # les plus anciens (le debounce se re-armera tout seul).
                if len(d) > self._MAX_ENTRIES:
                    for k in sorted(d, key=d.get)[: len(d) - self._MAX_ENTRIES]:
                        d.pop(k, None)

    async def dispatch(self, request, call_next):  # type: ignore[override]
        # 1) On laisse passer la requete d'abord (le middleware ne doit
        #    JAMAIS ralentir la reponse user — on touch apres).
        response = await call_next(request)

        # 2) Skip rapidement si pas une route auth-able.
        path = request.url.path
        if any(path.startswith(p) for p in _EXCLUDED_PATH_PREFIXES):
            return response

        # 3) Skip si pas de header Authorization Bearer.
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return response

        token = auth[7:].strip()
        if not token:
            return response

        # 4) Decode le JWT pour recuperer user_id (silent en cas d'echec).
        try:
            from api.auth.security import decode_token
            user_id = decode_token(token)
        except Exception:
            return response

        if not user_id:
            return response

        # 5) Debounce in-memory.
        now_epoch = time.time()
        should_touch_seen = (
            now_epoch - self._last_seen_touch.get(user_id, 0) >= DEBOUNCE_SECONDS
        )
        is_mutating = request.method in _MUTATING_METHODS
        should_touch_engaged = is_mutating and (
            now_epoch - self._last_engaged_touch.get(user_id, 0) >= DEBOUNCE_SECONDS
        )

        if not should_touch_seen and not should_touch_engaged:
            return response

        # 6) Touch DB en fire-and-forget : on N'ATTEND PAS le resultat pour
        #    renvoyer la reponse. Si l'UPDATE echoue, on log debug + on swallow.
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            await _touch_user_presence(
                user_id=user_id,
                touch_seen=should_touch_seen,
                touch_engaged=should_touch_engaged,
                now_iso=now_iso,
            )
            if should_touch_seen:
                self._last_seen_touch[user_id] = now_epoch
            if should_touch_engaged:
                self._last_engaged_touch[user_id] = now_epoch
            self._evict_if_needed()  # anti-OOM (no-op tant que < _MAX_ENTRIES)
        except Exception as e:
            # On ne casse JAMAIS la requete user pour un bug presence.
            logger.debug(f"[presence] touch failed: {e}")

        return response


async def _touch_user_presence(
    user_id: str,
    touch_seen: bool,
    touch_engaged: bool,
    now_iso: str,
) -> None:
    """Met a jour last_seen_at et/ou last_engaged_at pour cet user.

    Utilise SQLAlchemy async (compat SQLite + PostgreSQL via get_session_factory).
    """
    if not touch_seen and not touch_engaged:
        return

    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory

    # Construire le SET dynamiquement selon ce qu'il faut toucher.
    set_clauses = []
    params: dict[str, str] = {"uid": user_id, "now": now_iso}
    if touch_seen:
        set_clauses.append("last_seen_at = :now")
    if touch_engaged:
        set_clauses.append("last_engaged_at = :now")
    if not set_clauses:
        return

    sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :uid"

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(_sa_text(sql), params)
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            raise
