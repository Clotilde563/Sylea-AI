"""
Planificateur de taches cron pour Sylea Agent 3.

Verifie periodiquement les taches cron en base et les execute
quand leur expression cron correspond au moment actuel.
"""

import threading
import time
import json
import os
from datetime import datetime
from pathlib import Path

# Minimal cron expression parser (no external dependency)


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a 5-field cron expression matches a datetime.
    Fields: minute hour day-of-month month day-of-week
    Supports: * (any), */N (every N), N (exact), N-M (range), N,M (list)
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False

    values = [dt.minute, dt.hour, dt.day, dt.month, dt.weekday()]
    # cron weekday: 0=Sunday, python weekday: 0=Monday
    # Convert python weekday to cron: (python + 1) % 7 -> 0=Sun, 1=Mon, ..., 6=Sat
    cron_dow = (dt.weekday() + 1) % 7
    values[4] = cron_dow

    ranges = [
        (0, 59),   # minute
        (0, 23),   # hour
        (1, 31),   # day of month
        (1, 12),   # month
        (0, 6),    # day of week (0=Sunday)
    ]

    for i, field in enumerate(fields):
        if not _field_matches(field, values[i], ranges[i]):
            return False
    return True


def _field_matches(field: str, value: int, valid_range: tuple) -> bool:
    """Check if a single cron field matches a value."""
    if field == "*":
        return True

    for part in field.split(","):
        # Handle */N
        if part.startswith("*/"):
            try:
                step = int(part[2:])
                if step > 0 and value % step == 0:
                    return True
            except ValueError:
                continue
        # Handle N-M
        elif "-" in part:
            try:
                low, high = part.split("-", 1)
                if int(low) <= value <= int(high):
                    return True
            except ValueError:
                continue
        # Handle exact N
        else:
            try:
                if int(part) == value:
                    return True
            except ValueError:
                continue
    return False


class SyleaScheduler:
    """Background scheduler that checks cron jobs every 60 seconds.

    Cost-safety :
      - Fallback model : Haiku 4.5 (66% moins cher que Sonnet). Override via env
        SYLEA_SCHEDULER_MODEL.
      - Budget quotidien max : defaut $0.50 / 24h (env SYLEA_SCHEDULER_DAILY_CAP_USD).
        Au-dela, le scheduler refuse les nouveaux appels LLM jusqu'au lendemain.
      - max_tokens reduit a 300 (au lieu de 500).
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_check: dict[str, str] = {}  # cron_id -> last execution minute
        # Compteur de cout quotidien (reset a minuit). Fuite-guard.
        self._spent_today_usd: float = 0.0
        self._spent_day_key: str = ""  # "YYYY-MM-DD"

    def start(self):
        """Start the scheduler in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="sylea-scheduler")
        self._thread.start()
        print("[Scheduler] Demarre — verification toutes les 60s")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        print("[Scheduler] Arrete")

    def _run_loop(self):
        """Main loop: check every 60s for cron jobs to execute."""
        while self._running:
            try:
                self._check_and_execute()
            except Exception as e:
                print(f"[Scheduler] Erreur: {e}")
            # Sleep 60 seconds, checking every second if we should stop
            for _ in range(60):
                if not self._running:
                    return
                time.sleep(1)

    def _check_and_execute(self):
        """Check all enabled cron jobs and execute matching ones."""
        from sylea.core.storage.database import DatabaseManager

        db = DatabaseManager()
        db.connect()
        try:
            rows = db.conn.execute(
                "SELECT id, auth_user_id, label, instruction, cron_expr "
                "FROM agent3_cron WHERE enabled = 1"
            ).fetchall()

            now = datetime.now()
            # Use minute-level key to avoid re-executing within same minute
            current_minute = now.strftime("%Y-%m-%d %H:%M")

            for row in rows:
                cron_id = row[0]
                user_id = row[1]
                label = row[2]
                instruction = row[3]
                cron_expr = row[4]

                # Skip if already executed this minute
                if self._last_check.get(cron_id) == current_minute:
                    continue

                if _cron_matches(cron_expr, now):
                    self._last_check[cron_id] = current_minute
                    print(f"[Scheduler] Execution: '{label}' (cron: {cron_expr})")
                    self._execute_cron(db, cron_id, user_id, instruction)

            # Also check reminders
            self._check_reminders(db, now)

            # Phase 9B : retention pass (interne, idempotent 6h min entre runs)
            try:
                from api.agent3_retention import run_retention_pass
                run_retention_pass(db)  # no-op si < 6h depuis dernier run
            except Exception as e:
                print(f"[Scheduler] retention_pass warning: {e}")
        finally:
            db.disconnect()

    def _daily_budget_check(self) -> tuple[bool, float, float]:
        """Return (allowed, spent_today, daily_cap). Reset compteur a minuit."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._spent_day_key != today:
            self._spent_day_key = today
            self._spent_today_usd = 0.0
        try:
            cap = float(os.environ.get("SYLEA_SCHEDULER_DAILY_CAP_USD", "0.50"))
        except Exception:
            cap = 0.50
        return (self._spent_today_usd < cap), self._spent_today_usd, cap

    def _execute_cron(self, db, cron_id: str, user_id: str, instruction: str):
        """Execute a single cron job and store the result.

        Cost-safety :
          - Budget quotidien max (defaut $0.50) : au-dela, skip et enregistre
            un message d'attente jusqu'au lendemain.
          - Modele par defaut : Haiku 4.5 ($1/$5 /MTok) au lieu de Sonnet-4 ($3/$15).
          - max_tokens 300.
        """
        # Circuit breaker budget quotidien
        allowed, spent, cap = self._daily_budget_check()
        if not allowed:
            result_text = (
                f"[Cron skip — budget quotidien ${cap:.2f} atteint "
                f"(${spent:.4f} depenses). Reprend demain.]"
            )
            try:
                db.conn.execute(
                    "UPDATE agent3_cron SET last_run = ?, last_result = ? WHERE id = ?",
                    (datetime.now().isoformat(), result_text, cron_id),
                )
                db.conn.commit()
            except Exception:
                pass
            return

        model = os.environ.get("SYLEA_SCHEDULER_MODEL", "claude-haiku-4-5-20251001")
        max_tok = 300
        # Tarifs Haiku 4.5 par defaut
        in_rate = 1.0 / 1_000_000.0
        out_rate = 5.0 / 1_000_000.0
        if "sonnet" in model:
            in_rate = 3.0 / 1_000_000.0
            out_rate = 15.0 / 1_000_000.0

        result_text = ""
        try:
            # Try OpenClaw first (gratuit/local-routed si configure)
            try:
                from api.openclaw_bridge import openclaw_chat
                session_key = f"sylea-cron-{cron_id}"
                oc_response = openclaw_chat(instruction, session_key=session_key)
                if oc_response and oc_response.content:
                    result_text = oc_response.content[:2000]
                else:
                    result_text = "[Execution OK — pas de reponse]"
            except Exception:
                # Fallback: call Claude API directly (Haiku 4.5 par defaut)
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if api_key:
                    import httpx
                    resp = httpx.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": model,
                            "max_tokens": max_tok,
                            "messages": [{"role": "user", "content": instruction}],
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        result_text = data.get("content", [{}])[0].get("text", "OK")[:2000]
                        # Comptabilise le cout de cet appel dans le quota quotidien
                        usage = data.get("usage", {}) or {}
                        in_toks = int(usage.get("input_tokens", 0) or 0)
                        out_toks = int(usage.get("output_tokens", 0) or 0)
                        self._spent_today_usd += in_toks * in_rate + out_toks * out_rate
                        print(
                            f"[Scheduler] cron {cron_id} cost=${in_toks * in_rate + out_toks * out_rate:.5f} "
                            f"spent_today=${self._spent_today_usd:.4f}/${cap:.2f}"
                        )
                    else:
                        result_text = f"[Erreur API: {resp.status_code}]"
                else:
                    result_text = "[Execution impossible — pas de cle API ni de Gateway]"
        except Exception as e:
            result_text = f"[Erreur: {str(e)[:200]}]"

        # Update last_run and last_result
        try:
            db.conn.execute(
                "UPDATE agent3_cron SET last_run = ?, last_result = ? WHERE id = ?",
                (datetime.now().isoformat(), result_text, cron_id),
            )
            db.conn.commit()
        except Exception:
            pass

        # Send WebSocket notification to user
        try:
            import asyncio
            from api.websocket import ws_manager
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(ws_manager.send_to_user(user_id, {
                    "type": "cron_result",
                    "cron_id": cron_id,
                    "result": result_text[:500],
                    "timestamp": datetime.now().isoformat(),
                }))
        except Exception:
            pass

    def _check_reminders(self, db, now: datetime):
        """Check for due reminders and send notifications."""
        try:
            today = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")

            rows = db.conn.execute(
                "SELECT id, user_id, message, reminder_time, reminder_date "
                "FROM agent_reminders WHERE completed = 0 AND reminder_date = ? AND reminder_time <= ?",
                (today, current_time),
            ).fetchall()

            for row in rows:
                reminder_id = row[0]
                user_id = row[1]
                message = row[2]

                # Check if already notified this minute
                rkey = f"reminder-{reminder_id}"
                minute_key = now.strftime("%Y-%m-%d %H:%M")
                if self._last_check.get(rkey) == minute_key:
                    continue
                self._last_check[rkey] = minute_key

                print(f"[Scheduler] Rappel pour {user_id}: {message[:50]}")

                # Send WebSocket notification
                try:
                    import asyncio
                    from api.websocket import ws_manager
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(ws_manager.send_to_user(user_id, {
                            "type": "reminder",
                            "reminder_id": reminder_id,
                            "message": message,
                            "timestamp": now.isoformat(),
                        }))
                except Exception:
                    pass

                # Mark as completed
                try:
                    db.conn.execute(
                        "UPDATE agent_reminders SET completed = 1 WHERE id = ?",
                        (reminder_id,),
                    )
                    db.conn.commit()
                except Exception:
                    pass
        except Exception:
            pass


# Singleton
scheduler = SyleaScheduler()
