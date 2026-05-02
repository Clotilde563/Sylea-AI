"""
Computer Use Engine for Agent 3 -- Sylea
Allows Claude to control the user's Windows PC via Anthropic Computer Use API.
Utilise le VRAI navigateur de l'utilisateur (pas de Playwright = pas de detection).

Refactored with Claude Code patterns:
  - Retry with exponential backoff on API errors (429, 500)
  - Consecutive failure tracking (3-strike rule)
  - Message compaction: strip old screenshots, summarize old turns via Haiku
  - CostTracker integration: budget awareness + threshold warnings
  - Enhanced system prompt: error recovery, efficiency, stop conditions
  - Session cleanup and crash recovery
  - Image lifecycle management: keep only last N screenshots in conversation
"""

import base64
import io
import math
import os
import subprocess
import time
import asyncio
import json
import logging
import random
from typing import Optional, Callable, AsyncGenerator

logger = logging.getLogger("sylea.computer_use")

# ─────────────────────────────────────────────────────────────────────────────
# Imports desktop-only rendus optionnels pour permettre au module de se charger
# sur les serveurs headless (Railway, conteneurs sans display). Toutes les
# fonctions qui necessitent ces libs appellent _require_desktop() pour lever
# une erreur explicite plutot que de crasher le boot du serveur API.
# ─────────────────────────────────────────────────────────────────────────────
_DESKTOP_ERRORS: list[str] = []

try:
    import anthropic  # type: ignore
    _ANTHROPIC_AVAILABLE = True
except Exception as _e:
    anthropic = None  # type: ignore
    _ANTHROPIC_AVAILABLE = False
    _DESKTOP_ERRORS.append(f"anthropic: {_e}")

try:
    import pyautogui  # type: ignore
    _PYAUTOGUI_AVAILABLE = True
    # Disable pyautogui failsafe (moving mouse to corner won't crash)
    # But we have our own safety system
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
except Exception as _e:
    pyautogui = None  # type: ignore
    _PYAUTOGUI_AVAILABLE = False
    _DESKTOP_ERRORS.append(f"pyautogui: {_e}")

try:
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except Exception as _e:
    Image = None  # type: ignore
    _PIL_AVAILABLE = False
    _DESKTOP_ERRORS.append(f"PIL: {_e}")

_COMPUTER_USE_AVAILABLE = _ANTHROPIC_AVAILABLE and _PYAUTOGUI_AVAILABLE and _PIL_AVAILABLE

if not _COMPUTER_USE_AVAILABLE:
    logger.info(
        f"Computer Use desactive dans cet environnement (server headless probable). "
        f"Imports manquants : {_DESKTOP_ERRORS}"
    )


def _require_pyautogui() -> None:
    """Leve une erreur explicite si pyautogui n'est pas dispo."""
    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError(
            "Computer Use necessite pyautogui (environnement desktop). "
            "Installe pyautogui + execute l'agent depuis ta machine locale."
        )


def _require_desktop() -> None:
    """Leve une erreur si l'environnement n'a pas tous les imports desktop."""
    if not _COMPUTER_USE_AVAILABLE:
        raise RuntimeError(
            f"Computer Use indisponible sur cet environnement. "
            f"Imports manquants : {_DESKTOP_ERRORS}. "
            "Execute l'agent depuis une machine avec display (desktop)."
        )

# --- Configuration ---
# NOTE : claude-sonnet-4-6 NE SUPPORTE PAS le tool type `computer_20250124`
# (verifie via API : "'claude-sonnet-4-6' does not support tool types:
# computer_20250124"). On utilise donc claude-sonnet-4-5-20250929 pour
# Computer Use uniquement. Haiku 4.5 supporte aussi (low-cost pre-checks).
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
BETA_FLAG = "computer-use-2025-01-24"
TOOL_TYPE = "computer_20250124"
# Timeout wall-clock global (10 min). Pas de limite d'iterations :
# Claude s'arrete tout seul quand il a fini (stop_reason == "end_turn").
DEFAULT_TIMEOUT_SECONDS = 600.0

# --- Retry configuration ---
MAX_API_RETRIES = 3
RETRY_BASE_DELAY = 2.0       # seconds, doubles each attempt
RETRY_JITTER = 0.5           # random jitter factor

# --- Failure tracking ---
MAX_CONSECUTIVE_FAILURES = 3  # tool execution failures before warning model
MAX_TOTAL_ERRORS = 10         # total errors before hard stop

# --- Context management ---
MAX_SCREENSHOTS_IN_CONTEXT = 4   # keep only last N screenshots in messages
MAX_MESSAGES_BEFORE_COMPACT = 20  # trigger compaction after this many messages
COMPACT_TARGET_MESSAGES = 10      # target after compaction
IMAGE_TOKENS_ESTIMATE = 1600      # ~tokens per screenshot (JPEG scaled)

# --- Cost thresholds ---
COST_THRESHOLDS = [0.10, 0.50, 1.00, 5.00]  # USD warning thresholds

# --- Sensitive action detection ---
SENSITIVE_TEXT_PATTERNS = [
    "password", "passwd", "mot de passe",
    "credit card", "carte de credit", "carte bancaire",
    "ssn", "social security", "numero de securite sociale",
    "bank account", "compte bancaire",
    "routing number", "secret", "token", "api_key",
    "cvv", "cvc", "expiry", "expiration",
]

DESTRUCTIVE_KEY_COMBOS = [
    "ctrl+w", "alt+f4", "ctrl+shift+delete",
    "ctrl+alt+delete", "ctrl+shift+escape",
]

# URLs/domains that are considered sensitive
SENSITIVE_DOMAINS = [
    "bank", "banque", "paypal", "stripe",
    "payment", "paiement", "checkout",
]


def _get_screen_dimensions() -> tuple[int, int]:
    """Get actual screen resolution."""
    return pyautogui.size()


def _compute_scale(width: int, height: int) -> float:
    """Compute scale factor to fit within API constraints (max 1568px longest edge, ~1.15MP)."""
    long_edge = max(width, height)
    total_pixels = width * height
    long_edge_scale = 1568 / long_edge if long_edge > 1568 else 1.0
    total_pixels_scale = math.sqrt(1_150_000 / total_pixels) if total_pixels > 1_150_000 else 1.0
    return min(1.0, long_edge_scale, total_pixels_scale)


# ── Enhanced system prompt ───────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Tu es un agent qui controle l'ordinateur Windows de l'utilisateur via le Computer Use API.
Tu vois l'ecran, cliques, tapes du texte, et navigues dans le VRAI navigateur.

== REGLES FONDAMENTALES ==
1. OBSERVE avant d'agir : regarde toujours le screenshot avant chaque action.
2. UN SEUL objectif a la fois : decompoe la tache en micro-etapes.
3. VERIFIE apres chaque action : le screenshot suivant montre le resultat.
4. SOIS PRECIS dans tes clics : vise le centre de l'element cible.

== ACTIONS SPECIALES (UTILISE EN PRIORITE) ==
- open_url : ouvre une URL dans le navigateur par defaut.
  TOUJOURS utiliser cette action pour naviguer vers un site au lieu de
  cliquer sur la barre d'adresse et taper l'URL manuellement.
  Exemple : action='open_url', url='https://example.com'
- focus_window : met une fenetre au premier plan.
  Exemple : action='focus_window', title='Chrome'
- wait : attend 1 seconde (utile apres chargement de page).

== GESTION DES ERREURS ==
- Si un clic ne fonctionne pas : essaie un double-clic ou un clic sur une zone adjacente.
- Si une page ne charge pas : attends (action='wait') puis reprends un screenshot.
- Si tu es bloque apres 3 tentatives sur la meme action : CHANGE de strategie.
  Essaie : raccourci clavier, menu contextuel, URL directe, ou barre de recherche.
- Si le navigateur n'est pas au premier plan : utilise focus_window.
- NE BOUCLE PAS indefiniment sur une action qui echoue.

== GESTION DES IDENTIFIANTS ==
Si un site demande une connexion (email, mot de passe, etc.),
tu NE tapes PAS d'identifiants toi-meme. A la place, ARRETE-TOI
et reponds avec un message texte expliquant quel champ doit etre rempli.
L'utilisateur te donnera les infos, ou fera l'action lui-meme.

== EFFICACITE ==
- Prefere les raccourcis clavier quand c'est plus rapide (Ctrl+L pour barre d'adresse, Ctrl+T nouvel onglet).
- Ne prends pas de screenshot explicite — chaque action en prend un automatiquement.
- Si la tache est terminee, DIS-LE clairement et arrete-toi.
- Si tu ne peux pas accomplir la tache, explique pourquoi et arrete-toi.

== SCROLL ==
- Pour lire le contenu d'une page : scroll vers le bas progressivement.
- scroll_amount : 3 pour un scroll normal, 5 pour un scroll rapide.
"""


class ComputerUseSession:
    """Manages a single Computer Use session with Claude.

    Patterns from Claude Code applied:
    - Retry with exponential backoff on API errors
    - Consecutive failure tracking
    - Message compaction (strip old screenshots)
    - Cost tracking integration
    - Crash recovery
    """

    def __init__(self, api_key: str, user_id: str = "default"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.user_id = user_id
        self.screen_w, self.screen_h = _get_screen_dimensions()
        self.scale = _compute_scale(self.screen_w, self.screen_h)
        self.scaled_w = int(self.screen_w * self.scale)
        self.scaled_h = int(self.screen_h * self.scale)
        self.messages: list[dict] = []
        self.is_running = False
        self.is_aborted = False
        self._pending_confirmation: Optional[dict] = None
        self._confirmation_result: Optional[bool] = None
        self._confirmation_event = asyncio.Event()
        # Pause/resume pour actions utilisateur (login, paiement, captcha)
        self._user_action_event = asyncio.Event()
        self._user_action_result: Optional[str] = None  # "done" ou "abandon"
        self.iteration = 0
        self.total_actions = 0
        # Error tracking (Claude Code pattern)
        self._consecutive_failures = 0
        self._total_errors = 0
        self._last_action_error: Optional[str] = None
        # Cost tracking
        self._cost_tracker = None
        # Latest screenshot for endpoint
        self._latest_screenshot: Optional[str] = None
        # Compactor
        self._compactor = None

    def _get_cost_tracker(self):
        """Lazy-load cost tracker."""
        if self._cost_tracker is None:
            try:
                from api.agent3_cost_tracker import get_cost_tracker
                self._cost_tracker = get_cost_tracker(f"cu_{self.user_id}")
            except ImportError:
                pass
        return self._cost_tracker

    def _get_compactor(self):
        """Lazy-load context compactor."""
        if self._compactor is None:
            try:
                from api.agent3_context_compaction import ContextCompactor
                self._compactor = ContextCompactor(
                    self.client,
                    model=HAIKU_MODEL,
                    max_messages=MAX_MESSAGES_BEFORE_COMPACT,
                    target_messages=COMPACT_TARGET_MESSAGES,
                    keep_last=6,
                )
            except ImportError:
                pass
        return self._compactor

    def take_screenshot(self) -> str:
        """Capture screen, resize to API constraints, return base64 JPEG.
        Utilise mss (10x plus rapide que pyautogui) si disponible.
        Compresse en JPEG pour reduire la taille (moins de tokens API)."""
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Ecran principal
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except (ImportError, Exception) as e:
            logger.debug(f"mss failed ({e}), falling back to pyautogui")
            try:
                img = pyautogui.screenshot()
            except Exception as e2:
                logger.error(f"Screenshot failed completely: {e2}")
                raise RuntimeError(f"Impossible de capturer l'ecran: {e2}") from e2

        if self.scale < 1.0:
            img = img.resize((self.scaled_w, self.scaled_h), Image.LANCZOS)
        buffer = io.BytesIO()
        # JPEG quality 60 : 3x plus petit que PNG, assez pour Claude Vision
        img.save(buffer, format="JPEG", quality=60)
        return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    def scale_up(self, x: int, y: int) -> tuple[int, int]:
        """Convert API coordinates back to actual screen coordinates."""
        return int(x / self.scale), int(y / self.scale)

    def needs_confirmation(self, action: str, params: dict) -> tuple[bool, str]:
        """Check if an action is sensitive and needs user confirmation."""
        # Typing sensitive text
        if action == "type":
            text = params.get("text", "").lower()
            for pattern in SENSITIVE_TEXT_PATTERNS:
                if pattern in text:
                    return True, f"Texte sensible detecte: '{pattern}'"

        # Destructive keyboard shortcuts
        if action == "key":
            keys = params.get("text", "").lower()
            if keys in DESTRUCTIVE_KEY_COMBOS:
                return True, f"Raccourci potentiellement destructif: {keys}"

        return False, ""

    # ── Detection d'actions necessitant l'utilisateur ──

    _LOGIN_KEYWORDS = [
        "email", "e-mail", "mot de passe", "password", "identifiant",
        "connexion", "connecter", "se connecter", "sign in", "log in",
        "login", "authentifi", "credentials", "username", "utilisateur",
    ]
    _PAYMENT_KEYWORDS = [
        "carte", "paiement", "payment", "credit card", "cvv", "expiration",
        "numero de carte", "facturation", "billing",
    ]
    _CAPTCHA_KEYWORDS = [
        "captcha", "robot", "verification", "je ne suis pas un robot",
        "i'm not a robot", "recaptcha", "hcaptcha", "verif",
    ]

    @staticmethod
    def _is_user_action_needed(text: str) -> bool:
        """Detecte si le texte de Claude indique un besoin d'intervention utilisateur."""
        t = text.lower()
        all_keywords = (
            ComputerUseSession._LOGIN_KEYWORDS
            + ComputerUseSession._PAYMENT_KEYWORDS
            + ComputerUseSession._CAPTCHA_KEYWORDS
        )
        matches = sum(1 for kw in all_keywords if kw in t)
        return matches >= 2

    @staticmethod
    def _detect_action_type(text: str) -> str:
        """Determine le type d'action utilisateur requise."""
        t = text.lower()
        if any(kw in t for kw in ComputerUseSession._CAPTCHA_KEYWORDS):
            return "captcha"
        if any(kw in t for kw in ComputerUseSession._PAYMENT_KEYWORDS):
            return "payment"
        if any(kw in t for kw in ComputerUseSession._LOGIN_KEYWORDS):
            return "login"
        return "unknown"

    def user_action_done(self, result: str):
        """Appele quand l'utilisateur a termine son action (login, captcha, etc.)."""
        self._user_action_result = result
        self._user_action_event.set()

    # ── Action execution with crash recovery ──

    def execute_action(self, action: str, params: dict) -> dict:
        """Execute a single computer action. Returns tool_result content.

        Includes crash recovery: if pyautogui fails, attempts fallback strategies.
        """
        self.total_actions += 1

        if action == "screenshot":
            b64 = self.take_screenshot()
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            }

        elif action == "left_click":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.click(x, y)
            time.sleep(0.3)

        elif action == "right_click":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.rightClick(x, y)
            time.sleep(0.3)

        elif action == "middle_click":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.middleClick(x, y)
            time.sleep(0.3)

        elif action == "double_click":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.doubleClick(x, y)
            time.sleep(0.3)

        elif action == "triple_click":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.tripleClick(x, y)
            time.sleep(0.3)

        elif action == "mouse_move":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.moveTo(x, y)

        elif action == "left_click_drag":
            sx, sy = self.scale_up(*params["start_coordinate"])
            ex, ey = self.scale_up(*params["coordinate"])
            pyautogui.moveTo(sx, sy)
            pyautogui.mouseDown()
            pyautogui.moveTo(ex, ey, duration=0.5)
            pyautogui.mouseUp()

        elif action == "left_mouse_down":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.moveTo(x, y)
            pyautogui.mouseDown()

        elif action == "left_mouse_up":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.moveTo(x, y)
            pyautogui.mouseUp()

        elif action == "type":
            text = params.get("text", "")
            try:
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.1)
            except ImportError:
                pyautogui.typewrite(text, interval=0.02)

        elif action == "key":
            keys = params.get("text", "")
            if "+" in keys:
                parts = [k.strip() for k in keys.split("+")]
                pyautogui.hotkey(*parts)
            else:
                key_map = {
                    "Return": "enter", "Escape": "escape", "Tab": "tab",
                    "BackSpace": "backspace", "Delete": "delete",
                    "space": "space", "Space": "space",
                }
                mapped = key_map.get(keys, keys.lower())
                pyautogui.press(mapped)
            time.sleep(0.2)

        elif action == "scroll":
            x, y = self.scale_up(*params["coordinate"])
            pyautogui.moveTo(x, y)
            direction = params.get("scroll_direction", "down")
            amount = params.get("scroll_amount", 3)
            if direction == "up":
                pyautogui.scroll(amount)
            elif direction == "down":
                pyautogui.scroll(-amount)
            elif direction == "left":
                pyautogui.hscroll(-amount)
            elif direction == "right":
                pyautogui.hscroll(amount)
            time.sleep(0.2)

        elif action == "hold_key":
            key = params.get("text", "")
            duration = params.get("duration", 1)
            pyautogui.keyDown(key)
            time.sleep(duration)
            pyautogui.keyUp(key)

        elif action == "wait":
            time.sleep(1)

        elif action == "open_url":
            url = params.get("url", "")
            if url:
                try:
                    os.startfile(url)
                except Exception:
                    subprocess.Popen(["cmd", "/c", "start", "", url], shell=True)
                time.sleep(5)
                # Focus browser
                self._try_focus_browser()

        elif action == "focus_window":
            title = params.get("title", "")
            self._try_focus_window(title)

        else:
            logger.warning(f"Action inconnue: {action}")
            return {"type": "text", "text": f"Action inconnue: {action}"}

        # After any non-screenshot action, take a screenshot so Claude can see the result
        time.sleep(0.3)
        try:
            b64 = self.take_screenshot()
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            }
        except Exception as e:
            # Screenshot failed after action — still report success with text
            logger.warning(f"Post-action screenshot failed: {e}")
            return {"type": "text", "text": f"Action '{action}' executee, mais screenshot echoue: {e}"}

    def _try_focus_browser(self):
        """Try to focus any browser window. Crash-safe."""
        try:
            for title in ["Chrome", "Edge", "Firefox", "Brave", "Opera"]:
                windows = pyautogui.getWindowsWithTitle(title)
                if windows:
                    w = windows[0]
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                    time.sleep(0.5)
                    return True
        except Exception as e:
            logger.debug(f"Focus browser failed: {e}")
        return False

    def _try_focus_window(self, title: str):
        """Try to focus a window by title. Crash-safe."""
        try:
            windows = pyautogui.getWindowsWithTitle(title)
            if windows:
                w = windows[0]
                if w.isMinimized:
                    w.restore()
                w.activate()
                time.sleep(0.5)
                return True
        except Exception as e:
            logger.debug(f"Focus window '{title}' failed: {e}")
        return False

    # ── API call with retry ──────────────────────────────────────────────────

    async def _call_api_with_retry(
        self, system_prompt: str, tools: list, messages: list
    ) -> object:
        """Call Claude API with exponential backoff retry on transient errors.

        Pattern from Claude Code: retry 429/500/overloaded errors with
        exponential backoff + jitter. Hard-fail on 4xx client errors.
        """
        last_error = None
        for attempt in range(MAX_API_RETRIES + 1):
            try:
                response = await asyncio.to_thread(
                    self.client.beta.messages.create,
                    model=ANTHROPIC_MODEL,
                    max_tokens=4096,
                    system=[{
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    tools=tools,
                    messages=messages,
                    betas=[BETA_FLAG],
                )
                # Record cost
                tracker = self._get_cost_tracker()
                if tracker:
                    tracker.record_from_response(response, model=ANTHROPIC_MODEL)
                return response
            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < MAX_API_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, RETRY_JITTER)
                    logger.warning(f"Rate limited (429), retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_API_RETRIES})")
                    await asyncio.sleep(delay)
                    continue
            except anthropic.InternalServerError as e:
                last_error = e
                if attempt < MAX_API_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, RETRY_JITTER)
                    logger.warning(f"Server error (500), retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_API_RETRIES})")
                    await asyncio.sleep(delay)
                    continue
            except anthropic.APIStatusError as e:
                # Overloaded (529) — retryable
                if e.status_code == 529 and attempt < MAX_API_RETRIES:
                    last_error = e
                    delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, RETRY_JITTER)
                    logger.warning(f"API overloaded (529), retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue
                # Credit exhausted — hard fail
                err_msg = str(e).lower()
                if "credit" in err_msg or "balance" in err_msg:
                    raise RuntimeError("Credit API Anthropic epuise. Verifie ton compte.") from e
                raise
            except anthropic.APIConnectionError as e:
                last_error = e
                if attempt < MAX_API_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Connection error, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

        raise RuntimeError(
            f"API indisponible apres {MAX_API_RETRIES + 1} tentatives: {last_error}"
        )

    # ── Image lifecycle management ───────────────────────────────────────────

    def _prune_old_screenshots(self):
        """Remove old screenshots from message history to save tokens.

        Claude Code pattern: keep only the last N screenshots, replace
        older ones with [screenshot omis] text placeholders.
        """
        image_positions: list[tuple[int, int]] = []  # (msg_idx, content_block_idx)

        for i, msg in enumerate(self.messages):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for j, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "image":
                    image_positions.append((i, j))

        # Keep only the last MAX_SCREENSHOTS_IN_CONTEXT
        if len(image_positions) <= MAX_SCREENSHOTS_IN_CONTEXT:
            return  # Nothing to prune

        to_remove = image_positions[:-MAX_SCREENSHOTS_IN_CONTEXT]
        for msg_idx, block_idx in to_remove:
            content = self.messages[msg_idx]["content"]
            if isinstance(content, list) and block_idx < len(content):
                content[block_idx] = {
                    "type": "text",
                    "text": "[screenshot precedent omis pour economiser les tokens]",
                }

        if to_remove:
            logger.debug(f"Pruned {len(to_remove)} old screenshots from context")

    # ── Context compaction ───────────────────────────────────────────────────

    async def _maybe_compact_messages(self) -> bool:
        """Compact messages if they exceed the threshold.

        Returns True if compaction happened.
        """
        compactor = self._get_compactor()
        if not compactor:
            return False

        if len(self.messages) <= MAX_MESSAGES_BEFORE_COMPACT:
            return False

        try:
            new_messages = await compactor.maybe_compact(self.messages)
            if len(new_messages) < len(self.messages):
                old_count = len(self.messages)
                self.messages = new_messages
                logger.info(f"Context compacted: {old_count} -> {len(new_messages)} messages")
                return True
        except Exception as e:
            logger.warning(f"Context compaction failed: {e}")

        return False

    # ── Cost threshold check ─────────────────────────────────────────────────

    def _check_cost_thresholds(self) -> list[dict]:
        """Check if we crossed any cost thresholds. Returns events to yield."""
        tracker = self._get_cost_tracker()
        if not tracker:
            return []

        events = []
        snapshot = tracker.get()
        for threshold in COST_THRESHOLDS:
            if tracker.crossed_threshold(threshold):
                events.append({
                    "type": "cost_warning",
                    "threshold_usd": threshold,
                    "current_usd": snapshot["estimated_usd"],
                    "calls": snapshot["calls"],
                    "input_tokens": snapshot["input_tokens"],
                    "output_tokens": snapshot["output_tokens"],
                })
                logger.info(f"Cost threshold crossed: ${threshold:.2f} (current: ${snapshot['estimated_usd']:.4f})")
        return events

    # ── Main loop ────────────────────────────────────────────────────────────

    async def run(
        self,
        user_prompt: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        on_screenshot: Optional[Callable] = None,
        on_action: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None,
        on_confirmation_needed: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Main Computer Use agent loop as an async generator.

        Claude Code patterns applied:
        - Retry on API errors with exponential backoff
        - Track consecutive failures; warn model after 3
        - Prune old screenshots to save tokens
        - Compact messages when history grows too large
        - Emit cost warnings at thresholds

        Yields events for the frontend:
        - {"type": "screenshot", "data": base64_jpeg}
        - {"type": "action", "action": "left_click", "params": {...}}
        - {"type": "thinking", "text": "..."}
        - {"type": "confirmation_needed", "action": "...", "params": {...}, "reason": "..."}
        - {"type": "confirmation_result", "approved": bool}
        - {"type": "user_action_needed", "instruction": "...", "action_type": "..."}
        - {"type": "user_action_result", "result": "done"|"abandon"}
        - {"type": "cost_warning", "threshold_usd": N, "current_usd": N, ...}
        - {"type": "cost_update", "estimated_usd": N, "calls": N}
        - {"type": "compaction", "old_count": N, "new_count": N}
        - {"type": "complete", "text": "..."}
        - {"type": "error", "message": "..."}
        - {"type": "step", "current": N}
        """
        self.is_running = True
        self.is_aborted = False
        self.iteration = 0
        self.total_actions = 0
        self._consecutive_failures = 0
        self._total_errors = 0
        self._last_action_error = None
        start_time = time.monotonic()

        # Reset cost tracker for this session
        tracker = self._get_cost_tracker()
        if tracker:
            tracker.reset()

        tools = [
            {
                "type": TOOL_TYPE,
                "name": "computer",
                "display_width_px": self.scaled_w,
                "display_height_px": self.scaled_h,
            },
        ]

        # Start with an initial screenshot so Claude knows the current state
        try:
            initial_screenshot = await asyncio.to_thread(self.take_screenshot)
        except Exception as e:
            yield {"type": "error", "message": f"Impossible de capturer l'ecran: {str(e)}"}
            self.is_running = False
            return

        self._latest_screenshot = initial_screenshot
        yield {"type": "screenshot", "data": initial_screenshot}

        self.messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": initial_screenshot,
                        },
                    },
                ],
            }
        ]

        try:
            while True:
                if self.is_aborted:
                    yield {"type": "complete", "text": "Session annulee par l'utilisateur."}
                    break

                # Wall-clock timeout
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_seconds:
                    yield {
                        "type": "complete",
                        "text": f"Timeout atteint apres {int(elapsed)}s. Tache non terminee.",
                        "success": False,
                    }
                    break

                # Total errors hard stop
                if self._total_errors >= MAX_TOTAL_ERRORS:
                    yield {
                        "type": "complete",
                        "text": f"Trop d'erreurs ({self._total_errors}). Session terminee.",
                        "success": False,
                    }
                    break

                self.iteration += 1
                yield {"type": "step", "current": self.iteration}

                # ── Prune old screenshots before API call ──
                self._prune_old_screenshots()

                # ── Compact messages if too many ──
                old_msg_count = len(self.messages)
                compacted = await self._maybe_compact_messages()
                if compacted:
                    yield {
                        "type": "compaction",
                        "old_count": old_msg_count,
                        "new_count": len(self.messages),
                    }

                # ── Call Claude API with retry ──
                try:
                    response = await self._call_api_with_retry(
                        SYSTEM_PROMPT, tools, self.messages,
                    )
                except RuntimeError as e:
                    yield {"type": "error", "message": str(e)}
                    yield {"type": "complete", "text": str(e), "success": False}
                    break

                # ── Emit cost update ──
                if tracker:
                    snapshot = tracker.get()
                    yield {
                        "type": "cost_update",
                        "estimated_usd": snapshot["estimated_usd"],
                        "calls": snapshot["calls"],
                        "input_tokens": snapshot["input_tokens"],
                        "output_tokens": snapshot["output_tokens"],
                    }

                # ── Check cost thresholds ──
                for cost_event in self._check_cost_thresholds():
                    yield cost_event

                # ── Process response content blocks ──
                response_content = []
                tool_use_blocks = []
                final_text_parts = []

                for block in response.content:
                    if hasattr(block, "text") and block.type == "text":
                        response_content.append({"type": "text", "text": block.text})
                        final_text_parts.append(block.text)
                        yield {"type": "thinking", "text": block.text}
                    elif block.type == "tool_use":
                        response_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                        tool_use_blocks.append(block)

                self.messages.append({"role": "assistant", "content": response_content})

                # ── If no tool calls — check end conditions ──
                if not tool_use_blocks:
                    final_text = "\n".join(final_text_parts)

                    # Detect user action needed (login, captcha, payment)
                    if self._is_user_action_needed(final_text):
                        action_type = self._detect_action_type(final_text)
                        logger.info(f"User action needed: {action_type} — pausing session")
                        yield {
                            "type": "user_action_needed",
                            "instruction": final_text,
                            "action_type": action_type,
                        }

                        # Wait for user (5 min max)
                        self._user_action_event.clear()
                        self._user_action_result = None
                        try:
                            await asyncio.wait_for(self._user_action_event.wait(), timeout=300.0)
                        except asyncio.TimeoutError:
                            self._user_action_result = "abandon"

                        if self._user_action_result == "done":
                            logger.info("User action done — resuming session")
                            yield {"type": "user_action_result", "result": "done"}
                            new_screenshot = await asyncio.to_thread(self.take_screenshot)
                            self._latest_screenshot = new_screenshot
                            yield {"type": "screenshot", "data": new_screenshot}
                            self.messages.append({
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "L'utilisateur a effectue l'action demandee. Voici l'ecran actuel. Verifie le resultat et continue la tache initiale."},
                                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": new_screenshot}},
                                ],
                            })
                            # Reset failure counter on successful user interaction
                            self._consecutive_failures = 0
                            continue
                        else:
                            logger.info("User action abandoned — stopping session")
                            yield {"type": "user_action_result", "result": "abandon"}
                            yield {"type": "complete", "text": "Tache abandonnee. L'action requise n'a pas ete effectuee."}
                            break
                    else:
                        # Task truly complete
                        yield {"type": "complete", "text": final_text or "Tache terminee."}
                        break

                # ── Process each tool use ──
                tool_results = []
                for block in tool_use_blocks:
                    if self.is_aborted:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Session annulee par l'utilisateur.",
                            "is_error": True,
                        })
                        continue

                    action = block.input.get("action", "")
                    params = {k: v for k, v in block.input.items() if k != "action"}

                    # Check if confirmation is needed
                    confirm_needed, reason = self.needs_confirmation(action, params)

                    if confirm_needed:
                        self._confirmation_event.clear()
                        self._confirmation_result = None

                        yield {
                            "type": "confirmation_needed",
                            "action": action,
                            "params": params,
                            "reason": reason,
                            "tool_use_id": block.id,
                        }

                        try:
                            await asyncio.wait_for(
                                self._confirmation_event.wait(),
                                timeout=60.0,
                            )
                        except asyncio.TimeoutError:
                            self._confirmation_result = False

                        approved = self._confirmation_result or False
                        yield {"type": "confirmation_result", "approved": approved}

                        if not approved:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": "Action refusee par l'utilisateur.",
                                "is_error": True,
                            })
                            continue

                    # Execute the action
                    yield {"type": "action", "action": action, "params": params}

                    try:
                        result_content = await asyncio.to_thread(
                            self.execute_action, action, params
                        )

                        # Reset consecutive failures on success
                        self._consecutive_failures = 0
                        self._last_action_error = None

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": [result_content],
                        })

                        # Send screenshot to frontend for live view
                        if result_content.get("type") == "image":
                            self._latest_screenshot = result_content["source"]["data"]
                            yield {"type": "screenshot", "data": result_content["source"]["data"]}

                    except Exception as e:
                        self._consecutive_failures += 1
                        self._total_errors += 1
                        self._last_action_error = str(e)
                        logger.error(f"Action {action} failed (consecutive: {self._consecutive_failures}): {e}")

                        # Build informative error for the model
                        error_msg = f"Erreur action '{action}': {str(e)}"
                        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            error_msg += (
                                f"\n\nATTENTION: {self._consecutive_failures} erreurs consecutives. "
                                "Change de strategie. Essaie: un autre element, un raccourci clavier, "
                                "focus_window, ou open_url. NE REPETE PAS la meme action."
                            )

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": error_msg,
                            "is_error": True,
                        })

                        yield {"type": "error", "message": f"Erreur action {action}: {str(e)}"}

                        # Try to get a screenshot anyway so model can see current state
                        try:
                            recovery_ss = await asyncio.to_thread(self.take_screenshot)
                            self._latest_screenshot = recovery_ss
                            # Don't add to tool_results (already have error),
                            # but send to frontend
                            yield {"type": "screenshot", "data": recovery_ss}
                        except Exception:
                            pass

                self.messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            logger.error(f"Erreur Computer Use: {e}")
            yield {"type": "error", "message": str(e)}

        finally:
            self.is_running = False
            # Log final stats
            if tracker:
                final = tracker.get()
                logger.info(
                    f"Computer Use session ended: {self.iteration} iterations, "
                    f"{self.total_actions} actions, {self._total_errors} errors, "
                    f"${final['estimated_usd']:.4f} USD"
                )

    def confirm(self, approved: bool):
        """Called when user approves/rejects a confirmation request."""
        self._confirmation_result = approved
        self._confirmation_event.set()

    def abort(self):
        """Abort the current session."""
        self.is_aborted = True
        self._confirmation_result = False
        self._confirmation_event.set()
        self._user_action_result = "abandon"
        self._user_action_event.set()

    def get_stats(self) -> dict:
        """Get session statistics."""
        result = {
            "iteration": self.iteration,
            "total_actions": self.total_actions,
            "total_errors": self._total_errors,
            "consecutive_failures": self._consecutive_failures,
            "is_running": self.is_running,
            "is_aborted": self.is_aborted,
            "screen": f"{self.screen_w}x{self.screen_h}",
            "scaled": f"{self.scaled_w}x{self.scaled_h}",
            "messages_count": len(self.messages),
        }
        tracker = self._get_cost_tracker()
        if tracker:
            result["cost"] = tracker.get()
        return result


# --- Session manager (one session per user) ---
_sessions: dict[str, ComputerUseSession] = {}


def get_session(user_id: str, api_key: str) -> ComputerUseSession:
    """Get or create a Computer Use session for a user.

    Creates a fresh session if none exists or the previous one is not running.
    """
    existing = _sessions.get(user_id)
    if existing and existing.is_running:
        return existing
    # Create fresh session (clean state)
    _sessions[user_id] = ComputerUseSession(api_key=api_key, user_id=user_id)
    return _sessions[user_id]


def get_active_session(user_id: str) -> Optional[ComputerUseSession]:
    """Get the active session for a user, if any."""
    session = _sessions.get(user_id)
    if session and session.is_running:
        return session
    return None
