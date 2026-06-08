"""
Scheduler pour les notifs des dilemmes en mode TRACKING.

Fonctionne en daemon thread (similaire a api/scheduler.py). Wakes toutes
les 60s et :

  1. Recupere les trackings dont next_notif_at <= now via
     find_pending_notifications_async (JOIN profil_utilisateur pour avoir
     auth_user_id).
  2. Pour chaque tracking, dispatche selon status :

     status='tracking' :
       - Trouve la periode pending courante (premier choice == None)
       - Si retry_count == 0 :
           - Envoie notif WS (push OS via Tauri + banner in-app)
           - Increment retry_count, set next_notif_at = now + 7 jours
       - Si retry_count >= 1 :
           - Auto-marque la periode comme 'none' via auto_overdue_async
           - Recharge le tracking (peut etre passe a awaiting_validation)

     status='awaiting_validation' :
       - delta = now - last_responded_at
       - Si delta < 7 jours (= scheduler trigger au D+3 reminder) :
           - Envoie notif "valide ton recap" WS
           - Set next_notif_at = last_responded_at + 7 jours
       - Sinon (= scheduler trigger au D+7 auto-validate) :
           - Auto-valide le tracking (applique impact)
           - Envoie notif WS "tracking valide automatiquement"

Cost-safety : le scheduler n'appelle JAMAIS d'API LLM. Il manipule juste
des rows DB et envoie des messages WS. Coute zero a faire tourner.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("sylea.dilemmes_tracking_scheduler")


class DilemmesTrackingScheduler:
    """Background daemon thread qui pousse les notifs de tracking."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._running = False
        # Anti-spam : ne pas envoyer 2x la meme notif dans la meme minute.
        # Cle = f"{tracking_id}:{minute_key}"
        self._sent_this_tick: set[str] = set()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True,
            name="sylea-tracking-scheduler",
        )
        self._thread.start()
        logger.info("[TrackingScheduler] Demarre — verification toutes les 60s")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[TrackingScheduler] Arrete")

    def _run_loop(self) -> None:
        # Petit jitter au demarrage pour eviter de tirer pile a la meme
        # minute que api/scheduler.py (qui declenche aussi des asyncio.run).
        time.sleep(5)
        while self._running:
            try:
                asyncio.run(self._tick_async())
            except Exception as e:
                logger.warning(f"[TrackingScheduler] tick erreur: {e}")
            # Sleep 60s, sortie rapide si stop demande.
            for _ in range(60):
                if not self._running:
                    return
                time.sleep(1)

    async def _tick_async(self) -> None:
        """Une iteration du scheduler. Idempotent."""
        from api import dilemmes_tracking as dt

        now_utc = datetime.now(timezone.utc)
        minute_key = now_utc.strftime("%Y-%m-%d %H:%M")

        try:
            pending = await dt.find_pending_notifications_async(now_utc)
        except Exception as e:
            logger.warning(f"[TrackingScheduler] find_pending failed: {e}")
            return

        if not pending:
            return

        logger.info(f"[TrackingScheduler] {len(pending)} tracking(s) a traiter")

        for tracking in pending:
            tracking_id = tracking["id"]
            key = f"{tracking_id}:{minute_key}"
            if key in self._sent_this_tick:
                continue
            self._sent_this_tick.add(key)

            try:
                if tracking["status"] == "tracking":
                    await self._handle_tracking_period(tracking, now_utc)
                elif tracking["status"] == "awaiting_validation":
                    await self._handle_awaiting_validation(tracking, now_utc)
            except Exception as e:
                logger.warning(
                    f"[TrackingScheduler] dispatch {tracking_id} failed: {e}"
                )

        # Nettoie le cache anti-spam toutes les heures (sinon il grossit
        # indefiniment). On garde uniquement la derniere heure.
        if now_utc.minute == 0:
            self._sent_this_tick.clear()

    # ── status='tracking' : notif de periode ────────────────────────────────

    async def _handle_tracking_period(
        self, tracking: dict, now_utc: datetime
    ) -> None:
        """Traite un tracking avec une periode pending."""
        from api import dilemmes_tracking as dt

        tracking_id = tracking["id"]
        user_id = tracking["user_id"]               # profil.id
        auth_user_id = tracking.get("auth_user_id")  # depuis le JOIN

        choices = tracking.get("choices_json", []) or []
        pending_choice = None
        for c in choices:
            if c.get("choice") is None:
                pending_choice = c
                break

        if pending_choice is None:
            # Toutes les periodes sont repondues — incoherent avec status='tracking',
            # corrige en passant a awaiting_validation.
            logger.warning(
                f"[TrackingScheduler] {tracking_id} status=tracking mais "
                f"aucun choice pending — forcage en awaiting_validation"
            )
            # Force transition en repondant 'none' a la derniere (no-op si deja
            # repondue). En pratique on ne devrait jamais passer ici.
            return

        retry_count = int(pending_choice.get("retry_count", 0) or 0)

        if retry_count == 0:
            # 1ere notif pour cette periode
            await self._send_period_notification(
                tracking, pending_choice, auth_user_id, is_retry=False,
            )
            await self._increment_retry_and_reschedule(
                tracking_id, pending_choice["periode_idx"],
            )
        else:
            # Deja >= 1 retry sans reponse -> auto-marque 'none' et avance
            logger.info(
                f"[TrackingScheduler] {tracking_id} periode "
                f"{pending_choice['periode_idx']} auto-marquee 'none' "
                f"(retry_count={retry_count})"
            )
            try:
                await dt.auto_overdue_async(tracking_id, user_id)
            except Exception as e:
                logger.warning(f"[TrackingScheduler] auto_overdue failed: {e}")

    async def _send_period_notification(
        self,
        tracking: dict,
        pending_choice: dict,
        auth_user_id: str | None,
        is_retry: bool,
    ) -> None:
        """Envoie une notif WS de fin de periode au desktop + web."""
        if not auth_user_id:
            return
        try:
            from api.websocket import ws_manager
        except Exception:
            return

        options = tracking.get("options_json", []) or []
        # Construit la liste des actions [Option A, Option B, ..., Aucun]
        actions = []
        for idx, opt in enumerate(options):
            actions.append({
                "id": str(idx),
                "label": opt.get("description") or f"Option {idx + 1}",
            })
        actions.append({"id": "none", "label": "Aucun des deux"})

        payload = {
            "type": "dilemme_tracking_period",
            "tracking_id": tracking["id"],
            "periode_idx": pending_choice["periode_idx"],
            "question": tracking["question"],
            "actions": actions,
            "is_retry": is_retry,
            "nb_periodes": tracking["nb_periodes"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            await ws_manager.send_to_user(auth_user_id, payload)
            logger.info(
                f"[TrackingScheduler] notif periode envoyee "
                f"(tracking={tracking['id']}, periode={pending_choice['periode_idx']}, "
                f"is_retry={is_retry})"
            )
        except Exception as e:
            logger.warning(f"[TrackingScheduler] send_to_user failed: {e}")

    async def _increment_retry_and_reschedule(
        self, tracking_id: str, periode_idx: int, retry_after_days: int = 7,
    ) -> None:
        """Increment retry_count sur la periode courante + reschedule
        next_notif_at = now + retry_after_days."""
        import json
        from datetime import timedelta
        from sqlalchemy import text
        from api.database import get_session_factory

        factory = get_session_factory()
        next_retry = (datetime.now(timezone.utc)
                      + timedelta(days=retry_after_days)).isoformat()

        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT choices_json FROM dilemmes_tracking WHERE id = :id"
                ),
                {"id": tracking_id},
            )
            row = result.mappings().first()
            if not row:
                return
            try:
                choices = json.loads(row["choices_json"])
            except Exception:
                return
            for c in choices:
                if c.get("periode_idx") == periode_idx:
                    c["retry_count"] = int(c.get("retry_count", 0) or 0) + 1
                    break

            await session.execute(
                text(
                    "UPDATE dilemmes_tracking SET "
                    "choices_json = :ch, next_notif_at = :n WHERE id = :id"
                ),
                {
                    "ch": json.dumps(choices, ensure_ascii=False),
                    "n": next_retry,
                    "id": tracking_id,
                },
            )
            await session.commit()

    # ── status='awaiting_validation' : relance D+3, auto-validate D+7 ────────

    async def _handle_awaiting_validation(
        self, tracking: dict, now_utc: datetime
    ) -> None:
        """
        Trigger a D+3 (reminder) puis D+7 (auto-validate).

        On distingue les 2 cas via le delta now - last_responded_at :
          - delta < 7 jours -> reminder D+3 (premier passage)
          - delta >= 7 jours -> auto-validate (deuxieme passage)
        """
        from datetime import timedelta
        from sqlalchemy import text
        from api.database import get_session_factory

        tracking_id = tracking["id"]
        auth_user_id = tracking.get("auth_user_id")
        choices = tracking.get("choices_json", []) or []

        # last_responded_at = max des responded_at
        last_responded_at: datetime | None = None
        for c in choices:
            r = c.get("responded_at")
            if not r:
                continue
            try:
                dt_val = datetime.fromisoformat(r)
                if dt_val.tzinfo is None:
                    dt_val = dt_val.replace(tzinfo=timezone.utc)
                if last_responded_at is None or dt_val > last_responded_at:
                    last_responded_at = dt_val
            except Exception:
                continue

        if last_responded_at is None:
            # Pas de last_responded — incoherent. On force auto-validate
            # comme garde-fou (apres tout, status='awaiting_validation' veut
            # bien dire que tout est repondu).
            logger.warning(
                f"[TrackingScheduler] {tracking_id} awaiting sans "
                f"last_responded_at — auto-validate de secours"
            )
            await self._auto_validate(tracking)
            return

        delta = now_utc - last_responded_at

        if delta < timedelta(days=7):
            # Reminder D+3 : on previent l'user qu'il a un recap a valider
            await self._send_awaiting_reminder(tracking, auth_user_id)
            # Reschedule pour le D+7 auto-validate
            target = (last_responded_at + timedelta(days=7)).isoformat()
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE dilemmes_tracking SET next_notif_at = :n "
                        "WHERE id = :id"
                    ),
                    {"n": target, "id": tracking_id},
                )
                await session.commit()
        else:
            # Auto-validate
            logger.info(
                f"[TrackingScheduler] {tracking_id} auto-validate "
                f"(awaiting depuis {delta.days} jours)"
            )
            await self._auto_validate(tracking)

    async def _send_awaiting_reminder(
        self, tracking: dict, auth_user_id: str | None,
    ) -> None:
        """Envoie une notif WS de relance pour valider le recap."""
        if not auth_user_id:
            return
        try:
            from api.websocket import ws_manager
        except Exception:
            return

        payload = {
            "type": "dilemme_tracking_validation_reminder",
            "tracking_id": tracking["id"],
            "question": tracking["question"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await ws_manager.send_to_user(auth_user_id, payload)
            logger.info(
                f"[TrackingScheduler] reminder envoyee "
                f"(tracking={tracking['id']})"
            )
        except Exception as e:
            logger.warning(f"[TrackingScheduler] reminder send failed: {e}")

    async def _auto_validate(self, tracking: dict) -> None:
        """Auto-valide un tracking sans intervention user (passe les 7 jours).

        Le scheduler tournant en thread sync sans contexte FastAPI, on
        recree manuellement DB + ProfilRepository + profil.
        """
        from api import dilemmes_tracking as dt

        tracking_id = tracking["id"]
        user_id = tracking["user_id"]
        auth_user_id = tracking.get("auth_user_id")

        if not auth_user_id:
            logger.warning(
                f"[TrackingScheduler] auto_validate skip {tracking_id} : "
                f"pas d'auth_user_id"
            )
            return

        # Charge le profil via sync repo (DB request-scoped).
        from sylea.core.storage.database import DatabaseManager
        from sylea.core.storage.repositories import ProfilRepository

        db = DatabaseManager()
        db.connect()
        try:
            profil_repo = ProfilRepository(db)
            profil = profil_repo.charger(auth_user_id=auth_user_id)
            if profil is None:
                logger.warning(
                    f"[TrackingScheduler] auto_validate skip {tracking_id} : "
                    f"profil introuvable pour auth_user_id={auth_user_id}"
                )
                return

            result = await dt.validate_tracking_async(
                tracking_id, user_id, profil, profil_repo,
            )
            if not result.get("ok"):
                logger.warning(
                    f"[TrackingScheduler] auto_validate failed "
                    f"{tracking_id} : {result.get('error')}"
                )
                return

            # Push WS pour informer l'user que c'est fait
            try:
                from api.websocket import ws_manager
                await ws_manager.send_to_user(auth_user_id, {
                    "type": "dilemme_tracking_auto_validated",
                    "tracking_id": tracking_id,
                    "question": tracking["question"],
                    "impact_jours_applique": result.get("impact_jours_applique"),
                    "delta_probabilite": result.get("delta_probabilite"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass
        finally:
            db.disconnect()


# Singleton
scheduler = DilemmesTrackingScheduler()


def is_enabled() -> bool:
    """Check si le scheduler doit demarrer au boot de FastAPI.

    Decouple de SYLEA_SCHEDULER_ENABLED depuis 2026-06-01 : ce scheduler-ci
    ne fait que des UPDATE DB + push WS (cout zero LLM) donc il peut tourner
    en dev sans souci, alors que api/scheduler.py declenche des appels
    Anthropic et reste OFF par defaut.

    Defaut : ON (opt-out via SYLEA_TRACKING_SCHEDULER_ENABLED=false).
    """
    val = os.environ.get(
        "SYLEA_TRACKING_SCHEDULER_ENABLED", "true"
    ).strip().lower()
    return val in ("1", "true", "yes", "on")


__all__ = ["scheduler", "DilemmesTrackingScheduler", "is_enabled"]
