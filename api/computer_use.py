"""
Computer Use Engine for Agent 3 -- Sylea
Allows Claude to control the user's Windows PC via Anthropic Computer Use API.
"""

import anthropic
import pyautogui
import base64
import io
import math
import time
import asyncio
import json
import logging
from PIL import Image
from typing import Optional, Callable, AsyncGenerator

logger = logging.getLogger("sylea.computer_use")

# Disable pyautogui failsafe (moving mouse to corner won't crash)
# But we have our own safety system
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

# --- Configuration ---
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
BETA_FLAG = "computer-use-2025-01-24"
TOOL_TYPE = "computer_20250124"
MAX_ITERATIONS = 25

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
    "ctrl+w", "alt+F4", "ctrl+shift+Delete",
    "ctrl+alt+Delete", "ctrl+shift+Escape",
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


class ComputerUseSession:
    """Manages a single Computer Use session with Claude."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
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
        self.iteration = 0
        self.total_actions = 0

    def take_screenshot(self) -> str:
        """Capture screen, resize to API constraints, return base64 PNG."""
        img = pyautogui.screenshot()
        if self.scale < 1.0:
            img = img.resize((self.scaled_w, self.scaled_h), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    def scale_up(self, x: int, y: int) -> tuple[int, int]:
        """Convert API coordinates back to actual screen coordinates."""
        return int(x / self.scale), int(y / self.scale)

    def needs_confirmation(self, action: str, params: dict) -> tuple[bool, str]:
        """
        Check if an action is sensitive and needs user confirmation.
        Returns (needs_confirm, reason).
        """
        # Typing sensitive text
        if action == "type":
            text = params.get("text", "").lower()
            for pattern in SENSITIVE_TEXT_PATTERNS:
                if pattern in text:
                    return True, f"Texte sensible detecte: '{pattern}'"

        # Destructive keyboard shortcuts
        if action == "key":
            keys = params.get("text", "").lower()
            if keys in [k.lower() for k in DESTRUCTIVE_KEY_COMBOS]:
                return True, f"Raccourci potentiellement destructif: {keys}"
            # Enter/Return could submit forms
            if keys in ("return", "enter"):
                return True, "Soumission de formulaire (Entree)"

        # All clicks need confirmation if we're not sure it's safe
        # We'll be more lenient here - only flag specific cases

        return False, ""

    def execute_action(self, action: str, params: dict) -> dict:
        """Execute a single computer action. Returns tool_result content."""
        self.total_actions += 1

        if action == "screenshot":
            b64 = self.take_screenshot()
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
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
            # pyautogui.typewrite only works for ASCII
            # For French/Unicode, use clipboard method
            try:
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.1)
            except ImportError:
                # Fallback: try typewrite for ASCII
                pyautogui.typewrite(text, interval=0.02)

        elif action == "key":
            keys = params.get("text", "")
            # Handle combos like "ctrl+s", "alt+tab"
            if "+" in keys:
                parts = [k.strip() for k in keys.split("+")]
                pyautogui.hotkey(*parts)
            else:
                # Map common key names
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

        else:
            logger.warning(f"Action inconnue: {action}")
            return {"type": "text", "text": f"Action inconnue: {action}"}

        # After any non-screenshot action, take a screenshot so Claude can see the result
        time.sleep(0.3)  # Brief wait for UI to update
        b64 = self.take_screenshot()
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        }

    async def run(
        self,
        user_prompt: str,
        on_screenshot: Optional[Callable] = None,
        on_action: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None,
        on_confirmation_needed: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Main Computer Use agent loop as an async generator.
        Yields events for the frontend:
        - {"type": "screenshot", "data": base64_png}
        - {"type": "action", "action": "left_click", "params": {...}}
        - {"type": "thinking", "text": "..."}
        - {"type": "confirmation_needed", "action": "...", "params": {...}, "reason": "..."}
        - {"type": "confirmation_result", "approved": bool}
        - {"type": "complete", "text": "..."}
        - {"type": "error", "message": "..."}
        - {"type": "iteration", "current": N, "max": MAX}
        """
        self.is_running = True
        self.is_aborted = False
        self.iteration = 0
        self.total_actions = 0

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
                            "media_type": "image/png",
                            "data": initial_screenshot,
                        },
                    },
                ],
            }
        ]

        system_prompt = (
            "Tu es un agent qui controle l'ordinateur Windows de l'utilisateur. "
            "Tu peux voir l'ecran, cliquer, taper du texte, et naviguer. "
            "Commence toujours par observer l'ecran (screenshot) avant d'agir. "
            "Sois precis dans tes clics. Decris brievement ce que tu fais a chaque etape. "
            "Si tu rencontres une erreur ou un blocage, essaie une approche alternative. "
            "Quand la tache est terminee, dis-le clairement."
        )

        try:
            for iteration in range(MAX_ITERATIONS):
                if self.is_aborted:
                    yield {"type": "complete", "text": "Session annulee par l'utilisateur."}
                    break

                self.iteration = iteration + 1
                yield {"type": "iteration", "current": self.iteration, "max": MAX_ITERATIONS}

                # Call Claude API
                response = await asyncio.to_thread(
                    self.client.beta.messages.create,
                    model=ANTHROPIC_MODEL,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=tools,
                    messages=self.messages,
                    betas=[BETA_FLAG],
                )

                # Process response content blocks
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

                # If no tool calls, task is complete
                if not tool_use_blocks:
                    final_text = "\n".join(final_text_parts)
                    yield {"type": "complete", "text": final_text or "Tache terminee."}
                    break

                # Process each tool use
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
                        yield {
                            "type": "confirmation_needed",
                            "action": action,
                            "params": params,
                            "reason": reason,
                            "tool_use_id": block.id,
                        }

                        # Wait for user confirmation (with timeout)
                        self._confirmation_event.clear()
                        self._confirmation_result = None

                        try:
                            await asyncio.wait_for(
                                self._confirmation_event.wait(),
                                timeout=60.0  # 60 second timeout
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
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": [result_content],
                        })

                        # Send screenshot to frontend for live view
                        if result_content.get("type") == "image":
                            yield {"type": "screenshot", "data": result_content["source"]["data"]}

                    except Exception as e:
                        logger.error(f"Erreur action {action}: {e}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Erreur: {str(e)}",
                            "is_error": True,
                        })
                        yield {"type": "error", "message": f"Erreur action {action}: {str(e)}"}

                self.messages.append({"role": "user", "content": tool_results})

            else:
                yield {"type": "complete", "text": f"Limite de {MAX_ITERATIONS} iterations atteinte."}

        except Exception as e:
            logger.error(f"Erreur Computer Use: {e}")
            yield {"type": "error", "message": str(e)}

        finally:
            self.is_running = False

    def confirm(self, approved: bool):
        """Called when user approves/rejects a confirmation request."""
        self._confirmation_result = approved
        self._confirmation_event.set()

    def abort(self):
        """Abort the current session."""
        self.is_aborted = True
        # Also unblock any pending confirmation
        self._confirmation_result = False
        self._confirmation_event.set()


# --- Session manager (one session per user) ---
_sessions: dict[str, ComputerUseSession] = {}


def get_session(user_id: str, api_key: str) -> ComputerUseSession:
    """Get or create a Computer Use session for a user."""
    if user_id not in _sessions or not _sessions[user_id].is_running:
        _sessions[user_id] = ComputerUseSession(api_key=api_key)
    return _sessions[user_id]


def get_active_session(user_id: str) -> Optional[ComputerUseSession]:
    """Get the active session for a user, if any."""
    session = _sessions.get(user_id)
    if session and session.is_running:
        return session
    return None
