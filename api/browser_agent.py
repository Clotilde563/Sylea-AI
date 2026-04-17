"""
Browser Agent v2 pour Agent 3 — Sylea
Agent INTELLIGENT qui controle un navigateur via Playwright + Vision Claude.

Principes fondamentaux :
1. VERIFIE chaque action via screenshot (comme un humain)
2. Se CORRIGE automatiquement si erreur detectee
3. Ne dit JAMAIS "done" sans preuve visuelle
4. Demande a l'utilisateur UNIQUEMENT pour login/captcha/paiement
5. Optimise les couts : Haiku pour les verifs simples, Sonnet pour les decisions
"""

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import anthropic

from api._playwright_thread import get_playwright_thread
from api.agent3_context_compaction import ContextCompactor, estimate_tokens
from api.agent3_cost_tracker import get_cost_tracker
from api.agent3_permissions import (
    Decision,
    PermissionMode,
    PermissionPolicy,
    classify_action,
    get_policy,
)
from api.agent3_plan_mode import (
    ExecutionPlan,
    PlanStatus,
    RiskLevel,
    StepStatus,
    get_plan_store,
)

logger = logging.getLogger("sylea.browser_agent")

MODEL_SMART = "claude-sonnet-4-20250514"   # Decisions complexes + vision principale
MODEL_CHEAP = "claude-haiku-4-5-20251001"  # Verifications simples (login? erreur?)

SCREENSHOTS_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# ── System prompt : le cerveau de l'agent ──
SYSTEM_PROMPT = """Tu es un agent intelligent qui controle un navigateur web via Playwright.
Tu vois des screenshots et tu decides quelle action effectuer pour accomplir la tache.

=== REGLES CRITIQUES ===
1. VERIFIE toujours le resultat de tes actions via le screenshot suivant
2. Ne dis JAMAIS "done" sans avoir VISUELLEMENT CONFIRME que la tache est accomplie
3. Si une action echoue ou produit un resultat inattendu, essaie une approche DIFFERENTE
4. Si tu detectes une page de login/captcha/paiement, utilise "need_user"
5. Sois PRECIS dans tes clics — vise le CENTRE des elements visibles
6. Si tu ne sais pas quoi faire, analyse le screenshot attentivement avant d'agir

=== ACTIONS DISPONIBLES (reponds en JSON, rien d'autre) ===
{"action":"click","x":N,"y":N} — Cliquer a une position precise
{"action":"type","text":"..."} — Taper du texte au clavier (caractere par caractere)
{"action":"press","key":"..."} — Appuyer sur une touche (Enter, Tab, Escape, Control+a, Control+v, Control+Enter, Backspace, Delete, etc.)
{"action":"scroll","direction":"down|up","amount":N} — Scroller (amount en pixels, 300 par defaut)
{"action":"goto","url":"..."} — Naviguer vers une URL
{"action":"select_all_and_type","text":"..."} — Ctrl+A puis taper (remplace tout le contenu d'un champ)
{"action":"wait","seconds":N} — Attendre N secondes (max 5)
{"action":"need_user","instruction":"...","action_type":"login|captcha|payment|unknown"} — Demander a l'utilisateur d'agir manuellement
{"action":"done","result":"...","success":true|false} — Tache terminee. success=true UNIQUEMENT si tu vois la preuve visuelle

=== CONNAISSANCES WEB ===

**TradingView :**
- D'abord, va sur https://www.tradingview.com/chart/ pour ouvrir le graphique
- Le Pine Script Editor est un petit onglet/bouton TOUT EN BAS de la page, dans une barre de panneaux
- Il peut etre cache — scroll vers le bas ou cherche un petit texte "Pine Editor" ou une icone en forme de code "{}" dans la barre inferieure
- ATTENTION : le bouton "Indicators" en haut (icone fx) ouvre la recherche d'indicateurs. Ce n'est PAS le Pine Editor !!
- NE JAMAIS taper le code dans la barre de recherche d'indicateurs
- Si tu ne trouves pas le Pine Editor en bas, essaie de cliquer sur la petite fleche vers le haut (^) en bas a gauche pour expand le panneau inferieur
- L'editeur Pine utilise Monaco (comme VS Code) avec coloration syntaxique
- Pour coller du code : Ctrl+A pour tout selectionner, puis tape le code
- Pour compiler : Ctrl+Enter ou bouton "Add to chart"
- Un indicateur REUSSI = nouveau panneau avec des courbes apparait SOUS le graphique principal (pour overlay=false)
- Si TradingView demande un login → popup avec "Sign in", "Continue with Google" → utilise need_user
- Erreurs de compilation = texte rouge dans la console du Pine Editor

=== REGLE DE TERMINAISON STRICTE (TradingView / Pine Script) ===
Tu ne peux dire {"action":"done","success":true} QUE si TOUTES ces conditions sont vraies sur
le DERNIER SCREENSHOT que tu as analyse :
  1. Le code Pine Script est visible dans l'editeur (ou le graphique s'il est applique)
  2. L'indicateur est EFFECTIVEMENT AFFICHE sur le graphique, visible par au moins UN des signes :
       - Un nouveau panneau avec des courbes sous le graphique principal
       - Des labels, plots, ou courbes superposes sur le prix
       - Des bandes colorees
       - Des marqueurs de signaux d'achat/vente (triangles, fleches)
  3. AUCUNE erreur rouge de compilation n'est visible dans la console du Pine Editor

Si tu n'es PAS SUR a 100% que l'indicateur est visuellement applique :
  - Compile encore : action "press" avec "Control+Enter"
  - Ou clique explicitement sur "Add to chart" / "Ajouter au graphique"
  - Ou scroll dans le panneau inferieur pour verifier
  - Puis reprends un screenshot et re-analyse
Dire "done" prematurement est un ECHEC. Il vaut mieux faire 5 actions de plus que rendre
la main sans preuve visuelle.

**Formulaires web :**
- Toujours cliquer sur un champ AVANT de taper dedans
- Pour remplacer le contenu : Ctrl+A puis taper le nouveau texte
- Boutons de soumission : chercher "Submit", "Save", "Send", "OK", "Confirm"

**Navigation :**
- Popups/cookies : fermer avec "Accept", "OK", "Close", X, ou Escape
- Si la page ne repond pas : attendre quelques secondes puis re-essayer
- Scroll vers le bas pour voir plus de contenu

=== VERIFICATION ===
Apres chaque action importante, dans ton prochain message :
1. Analyse le nouveau screenshot
2. Confirme si l'action a eu l'effet attendu
3. Si NON → essaie une approche alternative (ne repete PAS la meme action)
4. Si OUI → passe a l'etape suivante

REPONDS UNIQUEMENT AVEC UN OBJET JSON. Pas de texte avant/apres."""


class BrowserAgent:
    """Agent intelligent v2 — vision + verification + auto-correction.

    Extensions inspirees ethiquement de Claude Code :
      - cost_tracker : traque tokens/USD de chaque appel LLM
      - compactor    : compresse l'historique quand il gonfle
      - policy       : permissions par action (plan/default/auto/bypass)
      - active_plan  : plan d'execution approuve par user (Plan Mode)
    """

    def __init__(self, api_key: str, user_id: str = "default"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.browser = None
        self.page = None
        self.context = None
        self.is_running = False
        self.is_aborted = False
        self.iteration = 0
        self._latest_screenshot: str = ""
        self._playwright = None
        self._user_action_event = asyncio.Event()
        self._user_action_result: Optional[str] = None

        # ── Extensions Claude-Code-inspired ──
        self.user_id = user_id
        self.cost_tracker = get_cost_tracker(user_id)
        self.compactor = ContextCompactor(self.client)
        self.policy: PermissionPolicy = get_policy(user_id)
        self.active_plan: Optional[ExecutionPlan] = None
        self._permission_event = asyncio.Event()
        self._permission_decision: Optional[str] = None  # "allow" | "deny"
        # Seuils d'alerte cout en USD
        self._cost_thresholds = (0.10, 0.50, 1.00, 5.00)

    # ── Browser lifecycle ──

    async def _ensure_browser(self):
        # Verifier si le contexte/page existant est encore valide
        try:
            if self.context and self.page and not self.page.is_closed():
                return
        except Exception:
            pass

        # Fermer proprement l'ancien contexte s'il existe
        await self._close()

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()

        # Utiliser un profil persistant pour conserver les sessions de login
        # (Google bloque OAuth dans les navigateurs automatises sans profil)
        profile_dir = Path(__file__).parent.parent / "data" / "browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Nettoyer les lockfiles residuels (si un Edge precedent n'a pas ferme
        # proprement, ils empechent la reouverture du profil)
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
            try:
                (profile_dir / lock_name).unlink(missing_ok=True)
            except Exception:
                pass

        try:
            self.context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="msedge",
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except Exception as launch_err:
            # Tentative de fallback : tuer les process msedge fantomes + retry
            logger.warning(f"launch_persistent_context echec : {launch_err}. Kill Edge + retry...")
            try:
                import subprocess
                subprocess.run(
                    ["taskkill", "/F", "/IM", "msedge.exe"],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
            # Re-nettoyer les lockfiles apres kill
            for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
                try:
                    (profile_dir / lock_name).unlink(missing_ok=True)
                except Exception:
                    pass
            self.context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="msedge",
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
        self.browser = self.context  # persistent context IS the browser
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def _close(self):
        try:
            if self.context:
                await self.context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self.browser = None
        self.context = None
        self.page = None

    @staticmethod
    def _is_browser_closed_error(err: Exception) -> bool:
        """Detecte les erreurs indiquant que le navigateur/page a ete ferme."""
        msg = str(err).lower()
        indicators = (
            "target page",
            "target closed",
            "has been closed",
            "browser has been closed",
            "context has been closed",
            "connection closed",
            "browser closed",
            "page closed",
            "crashed",
            "websocket",
        )
        return any(ind in msg for ind in indicators)

    async def _recover_browser(self, last_url: str = "") -> bool:
        """Tente de relancer le navigateur et revenir a l'URL precedente. Retourne True si succes."""
        try:
            await self._close()
        except Exception:
            pass
        try:
            await self._ensure_browser()
            if last_url:
                try:
                    await self.page.goto(last_url, wait_until="domcontentloaded", timeout=30000)
                    await self.page.wait_for_timeout(3000)
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(f"Recovery failed: {e}", exc_info=True)
            return False

    # ── Permissions ──

    def user_grant_permission(self, allow: bool):
        """Appele depuis un endpoint REST quand l'user repond au prompt permissions."""
        self._permission_decision = "allow" if allow else "deny"
        try:
            pw_loop = get_playwright_thread().loop
            if pw_loop and pw_loop.is_running():
                pw_loop.call_soon_threadsafe(self._permission_event.set)
            else:
                self._permission_event.set()
        except Exception:
            self._permission_event.set()

    async def _ask_permission(self, prompt: str, action: str, params: dict, risk: RiskLevel) -> AsyncGenerator[dict, None]:
        """Yield un event 'permission_needed' et attend reponse user (timeout 120s)."""
        yield {
            "type": "permission_needed",
            "prompt": prompt,
            "action": action,
            "params": params,
            "risk": risk.value,
        }
        self._permission_event.clear()
        self._permission_decision = None
        try:
            await asyncio.wait_for(self._permission_event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            self._permission_decision = "deny"
        yield {"type": "permission_result", "decision": self._permission_decision or "deny"}

    async def _evaluate_and_gate(self, action: str, params: dict) -> AsyncGenerator[dict, None]:
        """Gate une action : yield des events + set self._last_gate_result ('allow'|'deny')."""
        try:
            current_url = self.page.url or "" if self.page else ""
        except Exception:
            current_url = ""
        result = self.policy.evaluate(action, params, current_url)
        self._last_gate_result = "allow"
        if result.decision == Decision.ALLOW:
            return
        if result.decision == Decision.DENY:
            yield {
                "type": "permission_denied",
                "action": action,
                "reason": result.reason,
                "risk": result.risk.value,
            }
            self._last_gate_result = "deny"
            return
        if result.decision == Decision.DEFER_TO_PLAN:
            yield {
                "type": "plan_mode_active",
                "reason": result.reason,
                "action": action,
            }
            self._last_gate_result = "deny"
            return
        # ASK_USER
        async for event in self._ask_permission(result.confirmation_prompt, action, params, result.risk):
            yield event
        if self._permission_decision != "allow":
            self._last_gate_result = "deny"
            return
        if result.risk == RiskLevel.DESTRUCTIVE:
            self.policy.record_destructive()

    # ── Cost tracking helper ──

    def _record_usage_and_warn(self, response: object, model: str) -> list[dict]:
        """Enregistre l'usage de la reponse. Retourne une liste d'events a yield si seuil."""
        events: list[dict] = []
        try:
            self.cost_tracker.record_from_response(response, model=model)
            snapshot = self.cost_tracker.get()
            for threshold in self._cost_thresholds:
                if self.cost_tracker.crossed_threshold(threshold):
                    events.append({
                        "type": "cost_warning",
                        "threshold_usd": threshold,
                        "current_usd": snapshot["estimated_usd"],
                        "calls": snapshot["calls"],
                    })
            events.append({
                "type": "cost_update",
                "usd": snapshot["estimated_usd"],
                "input_tokens": snapshot["input_tokens"],
                "output_tokens": snapshot["output_tokens"],
                "calls": snapshot["calls"],
            })
        except Exception as e:
            logger.debug(f"_record_usage_and_warn failed: {e}")
        return events

    # ── Plan Mode: attacher un plan existant ──

    def attach_plan(self, plan: ExecutionPlan) -> None:
        """Associe un plan approuve par l'user a cette session."""
        self.active_plan = plan
        # Si le plan existe, on passe la policy en AUTO_SAFE (plan deja review par user)
        if self.policy.mode == PermissionMode.PLAN:
            self.policy.mode = PermissionMode.AUTO_SAFE

    # ── Screenshots ──

    async def _take_screenshot(self) -> str:
        if not self.page:
            return ""
        try:
            img_bytes = await self.page.screenshot(type="jpeg", quality=45, timeout=15000)
        except Exception:
            # Retry avec qualite plus basse si timeout
            try:
                img_bytes = await self.page.screenshot(type="jpeg", quality=30, timeout=10000)
            except Exception:
                return self._latest_screenshot or ""
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        self._latest_screenshot = b64
        return b64

    async def _save_final_screenshot(self) -> str:
        if not self._latest_screenshot:
            return ""
        try:
            filepath = SCREENSHOTS_DIR / "browser_agent_latest.jpg"
            filepath.write_bytes(base64.standard_b64decode(self._latest_screenshot))
            return str(filepath)
        except Exception as e:
            logger.error(f"Erreur sauvegarde screenshot: {e}")
            return ""

    # ── User interaction (Effectue / Abandonner) ──

    def _set_event_threadsafe(self):
        """L'event vit dans le thread Playwright ; .set() doit etre poste via call_soon_threadsafe."""
        try:
            pw_loop = get_playwright_thread().loop
            if pw_loop and pw_loop.is_running():
                pw_loop.call_soon_threadsafe(self._user_action_event.set)
            else:
                self._user_action_event.set()
        except Exception:
            self._user_action_event.set()

    def user_action_done(self, result: str):
        self._user_action_result = result
        self._set_event_threadsafe()

    def abort(self):
        self.is_aborted = True
        self._user_action_result = "abandon"
        self._set_event_threadsafe()

    async def _ask_user(self, instruction: str, action_type: str = "unknown") -> AsyncGenerator[dict, None]:
        """Pause l'agent et attend action utilisateur (login/captcha/paiement)."""
        yield {"type": "user_action_needed", "instruction": instruction, "action_type": action_type}
        self._user_action_event.clear()
        self._user_action_result = None
        try:
            await asyncio.wait_for(self._user_action_event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            self._user_action_result = "abandon"
        if self._user_action_result == "done":
            yield {"type": "user_action_result", "result": "done"}
            await self.page.wait_for_timeout(2000)
        else:
            yield {"type": "user_action_result", "result": "abandon"}

    # ── Quick checks avec Haiku (peu couteux) ──

    async def _quick_check(self, question: str, screenshot_b64: str) -> str:
        """Verification rapide via Haiku (tres peu couteux). Retourne la reponse."""
        try:
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=MODEL_CHEAP,
                max_tokens=100,
                system=[{
                    "type": "text",
                    "text": "Reponds TRES brievement (1-2 mots). Pas de JSON.",
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": screenshot_b64}},
                    ],
                }],
            )
            # Track usage (Haiku)
            try:
                self.cost_tracker.record_from_response(resp, model=MODEL_CHEAP)
            except Exception:
                pass
            return resp.content[0].text.strip().lower()
        except Exception as e:
            logger.warning(f"Quick check failed: {e}")
            try:
                self.cost_tracker.record_error()
            except Exception:
                pass
            return "unknown"

    async def _is_login_or_captcha(self, screenshot_b64: str) -> str:
        """Detecte login/captcha/paiement via Haiku. Retourne: 'login', 'captcha', 'payment', 'none'.

        Garde-fou : ne pas confondre un graphique de trading (Bitcoin, USD, prix)
        avec une vraie page de paiement. Une page de paiement montre un
        FORMULAIRE (carte bancaire, CVV, bouton "Payer") — pas juste des prix.
        """
        # Short-circuit : si on est sur TradingView, on n'est jamais sur une page
        # de login/captcha/paiement qui bloque (sauf auth, detectee par l'agent lui-meme).
        try:
            current_url = (self.page.url or "").lower()
            if "tradingview.com" in current_url:
                # TradingView peut avoir une modale de sign-in ; seul l'agent (via
                # son JSON "need_user") decide si c'est bloquant. On ne coupe pas
                # arbitrairement sur detection visuelle.
                return "none"
        except Exception:
            pass

        answer = await self._quick_check(
            "Regarde ce screenshot et determine ce qu'il represente. "
            "Reponds UN SEUL MOT parmi : 'login', 'captcha', 'payment', ou 'none'.\n\n"
            "Regles STRICTES :\n"
            "- 'login' UNIQUEMENT si tu vois un formulaire avec champ email/username ET "
            "champ mot de passe visibles et actifs, bloquant l'acces au contenu.\n"
            "- 'captcha' UNIQUEMENT si tu vois un vrai CAPTCHA (reCAPTCHA, hCaptcha, "
            "puzzle d'images, 'je ne suis pas un robot').\n"
            "- 'payment' UNIQUEMENT si tu vois un formulaire de paiement avec champ "
            "numero de carte bancaire, CVV, date d'expiration ET bouton 'Payer' / "
            "'Confirmer achat'. PAS un graphique de prix ou un ticker.\n"
            "- 'none' dans TOUS les autres cas, notamment : dashboards, graphiques "
            "de trading (meme avec BTC, USD, EUR, prix affiches), pages d'articles, "
            "editeurs de code, apps web standards, popups de cookies, tooltips de prix.\n\n"
            "En cas de doute : reponds 'none'.",
            screenshot_b64,
        )
        # Parsing strict : il faut que le mot soit le seul ou en debut de reponse
        answer_clean = answer.strip().lower().split()[0] if answer.strip() else "none"
        if answer_clean in ("login", "captcha", "payment"):
            return answer_clean
        return "none"

    # ── Point d'entree principal : l'agent intelligent ──

    async def run(self, task: str, url: str = "", code: str = "", timeout_seconds: float = 600.0) -> AsyncGenerator[dict, None]:
        """
        Point d'entree public. Bridge vers le thread Playwright (ProactorEventLoop).
        Tous les awaits Playwright tournent dans ce thread ; les events yieldes
        reviennent dans le loop appelant (FastAPI/uvicorn).
        """
        pw_thread = get_playwright_thread()

        def factory() -> AsyncGenerator[dict, None]:
            return self._run_internal(task, url, code, timeout_seconds)

        async for event in pw_thread.bridge_async_gen(factory):
            yield event

    async def _run_internal(self, task: str, url: str = "", code: str = "", timeout_seconds: float = 600.0) -> AsyncGenerator[dict, None]:
        """
        Execution reelle de l'agent. Tourne dans le thread Playwright.
        Pas de limite d'iterations : l'agent tourne jusqu'a ce qu'il dise "done"
        ou que le timeout wall-clock soit atteint (defaut 600s).
        """
        self.is_running = True
        self.is_aborted = False
        self.iteration = 0
        start_time = time.monotonic()

        try:
            await self._ensure_browser()

            # ── Navigation initiale ──
            if url:
                yield {"type": "thinking", "text": f"Ouverture de {url}..."}
                try:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await self.page.wait_for_timeout(4000)
                except Exception as e:
                    yield {"type": "thinking", "text": f"Erreur navigation: {e}"}

            # Fermer popups cookies/bannieres
            for sel in ['button:has-text("Accept")', 'button:has-text("Got it")', 'button:has-text("OK")', '[aria-label="Close"]', 'button:has-text("Not now")', 'button:has-text("Maybe later")']:
                try:
                    el = self.page.locator(sel).first
                    if await el.is_visible(timeout=500):
                        await el.click()
                        await self.page.wait_for_timeout(300)
                except Exception:
                    pass

            # Premier screenshot
            ss = await self._take_screenshot()
            yield {"type": "screenshot", "data": ss}

            # Verifier login/captcha (via Haiku — pas cher)
            page_type = await self._is_login_or_captcha(ss)
            if page_type in ("login", "captcha", "payment"):
                yield {"type": "thinking", "text": f"Page de {page_type} detectee. Demande a l'utilisateur..."}
                async for event in self._ask_user(
                    f"Le site demande {'une connexion' if page_type == 'login' else 'un captcha' if page_type == 'captcha' else 'un paiement'}. "
                    f"Effectue l'action puis clique 'Effectue'.",
                    page_type,
                ):
                    yield event
                if self._user_action_result != "done":
                    yield {"type": "complete", "text": f"{page_type.capitalize()} abandonne."}
                    return
                ss = await self._take_screenshot()
                yield {"type": "screenshot", "data": ss}

            # ── Pre-traitement CSS : ouvrir Pine Editor si TradingView ──
            # (approche hybride : CSS rapide pour elements connus + vision pour le reste)
            _pine_opened = False
            current_url = self.page.url or ""
            if "tradingview" in current_url.lower() and code:
                yield {"type": "thinking", "text": "Ouverture du Pine Editor (selecteurs CSS)..."}
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(500)
                pine_sels = [
                    '[data-tooltip*="Pine"]',
                    '[data-name="pine-editor"]',
                    'button:has-text("Pine Editor")',
                    'button:has-text("Éditeur Pine")',
                    'button[aria-label*="Pine"]',
                ]
                for sel in pine_sels:
                    try:
                        el = self.page.locator(sel).first
                        if await el.is_visible(timeout=1500):
                            await el.click()
                            await self.page.wait_for_timeout(2000)
                            _pine_opened = True
                            yield {"type": "thinking", "text": f"Pine Editor ouvert via CSS: {sel}"}
                            break
                    except Exception:
                        continue
                if _pine_opened:
                    # Coller le code directement
                    editor_sels = ['.view-lines', '.monaco-editor', 'textarea', '[role="textbox"]']
                    for sel in editor_sels:
                        try:
                            el = self.page.locator(sel).first
                            if await el.is_visible(timeout=2000):
                                await el.click()
                                await self.page.wait_for_timeout(300)
                                await self.page.keyboard.press("Control+a")
                                await self.page.wait_for_timeout(200)
                                await self.page.keyboard.press("Delete")
                                await self.page.wait_for_timeout(200)
                                # Taper ligne par ligne pour le code long
                                for line in code.split("\n"):
                                    await self.page.keyboard.type(line, delay=1)
                                    await self.page.keyboard.press("Enter")
                                yield {"type": "thinking", "text": f"Code Pine Script colle ({len(code)} chars)"}
                                break
                        except Exception:
                            continue
                    ss = await self._take_screenshot()
                    yield {"type": "screenshot", "data": ss}

            # ── Construire le contexte pour Claude ──
            user_content = f"TACHE : {task}\n"
            if code:
                if _pine_opened:
                    user_content += f"\nLE CODE A DEJA ETE COLLE DANS LE PINE EDITOR ({len(code)} chars).\n"
                    user_content += "Tu dois maintenant : 1) Verifier que le code est bien la, 2) Compiler avec Ctrl+Enter ou 'Add to chart', 3) Verifier que l'indicateur apparait sur le graphique.\n"
                else:
                    user_content += f"\nCODE A UTILISER :\n```\n{code[:4000]}\n```\n"
            user_content += f"\nURL actuelle : {self.page.url}\n"
            user_content += "\nVoici le screenshot actuel de la page. Que fais-tu en premier ?"

            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": ss}},
                ],
            }]

            # ── Boucle agent intelligent ──
            consecutive_failures = 0

            while True:
                if self.is_aborted:
                    yield {"type": "complete", "text": "Tache annulee par l'utilisateur."}
                    break

                # Timeout wall-clock (garde-fou)
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_seconds:
                    saved_path = await self._save_final_screenshot()
                    yield {
                        "type": "complete",
                        "text": f"Timeout atteint apres {int(elapsed)}s. Tache non terminee.",
                        "screenshot_path": saved_path,
                        "success": False,
                    }
                    break

                self.iteration += 1
                yield {"type": "step", "current": self.iteration}

                # ── Compaction du contexte si trop de messages/tokens ──
                try:
                    approx_tokens = estimate_tokens(messages)
                    if len(messages) > self.compactor.max_messages or approx_tokens > 60000:
                        yield {"type": "thinking", "text": f"Compaction du contexte (msgs={len(messages)}, ~{approx_tokens} tokens)..."}
                        messages = await self.compactor.maybe_compact(messages)
                        yield {"type": "thinking", "text": f"Contexte compacte : {len(messages)} messages."}
                except Exception as compact_err:
                    logger.warning(f"Compaction failed, continuing: {compact_err}")

                # Appel Claude Sonnet (decision complexe)
                try:
                    response = await asyncio.to_thread(
                        self.client.messages.create,
                        model=MODEL_SMART,
                        max_tokens=500,
                        system=[{
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }],
                        messages=messages,
                    )
                    # Track usage + warn si seuil atteint
                    for evt in self._record_usage_and_warn(response, MODEL_SMART):
                        yield evt
                except Exception as api_err:
                    try:
                        self.cost_tracker.record_error()
                    except Exception:
                        pass
                    err_msg = str(api_err)[:200]
                    # Detection specifique "credit balance too low" => signal explicite a l'user
                    if "credit" in err_msg.lower() and ("low" in err_msg.lower() or "balance" in err_msg.lower()):
                        yield {"type": "cost_exhausted", "message": err_msg}
                        yield {"type": "error", "message": "Credits API Anthropic epuises. Recharge ton compte."}
                        break
                    yield {"type": "thinking", "text": f"Erreur API: {err_msg[:100]}. Attente 5s..."}
                    await self.page.wait_for_timeout(5000)
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        yield {"type": "error", "message": f"API indisponible apres 3 tentatives: {err_msg}"}
                        break
                    continue

                consecutive_failures = 0  # Reset sur succes

                resp_text = "".join(b.text for b in response.content if hasattr(b, "text"))
                yield {"type": "thinking", "text": resp_text[:200]}
                messages.append({"role": "assistant", "content": resp_text})

                # ── Parser le JSON ──
                action_data = None
                # Essai 1 : JSON pur
                try:
                    action_data = json.loads(resp_text.strip())
                except Exception:
                    pass
                # Essai 2 : raw_decode
                if not action_data:
                    try:
                        start = resp_text.find("{")
                        if start >= 0:
                            decoder = json.JSONDecoder()
                            action_data, _ = decoder.raw_decode(resp_text[start:])
                    except Exception:
                        pass
                # Essai 3 : regex dans markdown
                if not action_data:
                    import re
                    json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)```', resp_text, re.DOTALL)
                    for block in json_blocks:
                        try:
                            action_data = json.loads(block.strip())
                            break
                        except Exception:
                            continue
                # Echec total
                if not action_data:
                    messages.append({"role": "user", "content": [{"type": "text", "text": "JSON invalide. Reponds UNIQUEMENT avec un objet JSON, rien d'autre."}]})
                    continue

                action = action_data.get("action", "")
                yield {"type": "action", "action": action, "params": action_data}

                # ── Executer l'action ──

                if action == "done":
                    success = action_data.get("success", True)
                    result_text = action_data.get("result", "Termine.")

                    if success:
                        # Verification finale stricte via Haiku
                        final_ss = await self._take_screenshot()
                        yield {"type": "screenshot", "data": final_ss}

                        # Question ciblee selon le contexte
                        current_url_l = (self.page.url or "").lower()
                        is_tv_pine = ("tradingview" in current_url_l) or bool(code)
                        if is_tv_pine:
                            verify_question = (
                                "Regarde attentivement le graphique TradingView. "
                                "Vois-tu UN OU PLUSIEURS INDICATEURS Pine Script "
                                "AFFICHES (courbes colorees, bandes, panneau separe sous le "
                                "graphique avec des valeurs, ou labels/plots sur le prix) ? "
                                "Tu dois voir quelque chose de VISUEL qui vient de notre code. "
                                "Pas seulement l'editeur avec du code : l'indicateur DOIT etre "
                                "applique au graphique. Reponds UNIQUEMENT 'oui' ou 'non'."
                            )
                        else:
                            verify_question = (
                                f"La tache suivante est-elle clairement et visuellement "
                                f"accomplie sur cet ecran ? Tache: {task}. Reponds oui ou non."
                            )

                        verify = await self._quick_check(verify_question, final_ss)
                        verify_failed = "non" in verify or "no" in verify

                        if verify_failed:
                            yield {"type": "thinking", "text": f"Verif visuelle : indicateur NON visible ({verify[:50]}). Continue..."}
                            if is_tv_pine:
                                correction_hint = (
                                    "ATTENTION : la verification visuelle montre que AUCUN "
                                    "indicateur n'est affiche sur le graphique. Tu ne peux PAS "
                                    "dire 'done' maintenant. Actions possibles a essayer :\n"
                                    "1. Compile le code : focus sur l'editeur Pine puis Ctrl+Enter\n"
                                    "2. Clique sur le bouton 'Add to chart' / 'Ajouter au graphique'\n"
                                    "3. Si erreur de compilation rouge affichee : lis-la et dis-le a l'utilisateur\n"
                                    "4. Si l'editeur est vide : recolle le code avec select_all_and_type\n"
                                    "5. Scroll dans le panneau inferieur — l'indicateur peut etre cache\n"
                                    "Analyse le screenshot et prends l'action appropriee. "
                                    "Ne reessaie PAS 'done' tant que tu ne VOIS PAS l'indicateur."
                                )
                            else:
                                correction_hint = (
                                    "ATTENTION : la verification montre que la tache N'EST PAS "
                                    "accomplie. Analyse le screenshot et prends une action corrective."
                                )
                            messages.append({"role": "user", "content": [
                                {"type": "text", "text": correction_hint},
                                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": final_ss}},
                            ]})
                            continue

                    saved_path = await self._save_final_screenshot()
                    yield {"type": "complete", "text": result_text, "screenshot_path": saved_path, "success": success}
                    break

                elif action == "need_user":
                    instruction = action_data.get("instruction", "Action requise.")
                    action_type = action_data.get("action_type", "unknown")
                    async for event in self._ask_user(instruction, action_type):
                        yield event
                    if self._user_action_result != "done":
                        yield {"type": "complete", "text": "Action utilisateur abandonnee."}
                        break
                    # Apres action utilisateur, prendre screenshot et continuer
                    new_ss = await self._take_screenshot()
                    yield {"type": "screenshot", "data": new_ss}
                    messages.append({"role": "user", "content": [
                        {"type": "text", "text": "L'utilisateur a effectue l'action. Voici le nouvel ecran. Continue la tache."},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": new_ss}},
                    ]})
                    continue

                # ── Sauvegarder l'URL courante avant l'action (pour recovery) ──
                try:
                    last_url = self.page.url or ""
                except Exception:
                    last_url = ""

                # ── Permission gate (sauf pour actions deja gerees : done / need_user) ──
                if action not in ("done", "need_user"):
                    self._last_gate_result = "allow"
                    async for gate_evt in self._evaluate_and_gate(action, action_data):
                        yield gate_evt
                    if self._last_gate_result != "allow":
                        # L'action est refusee : on informe le modele et on continue
                        deny_reason = "refusee par la policy de permissions"
                        messages.append({"role": "user", "content": [{
                            "type": "text",
                            "text": f"L'action '{action}' a ete {deny_reason}. "
                                    "Propose une alternative moins risquee ou appelle need_user.",
                        }]})
                        continue

                # ── Executer l'action avec recovery auto si le navigateur se ferme ──
                try:
                    if action == "click":
                        x, y = action_data.get("x", 0), action_data.get("y", 0)
                        await self.page.mouse.click(x, y)

                    elif action == "type":
                        await self.page.keyboard.type(action_data.get("text", ""), delay=8)

                    elif action == "select_all_and_type":
                        await self.page.keyboard.press("Control+a")
                        await self.page.wait_for_timeout(100)
                        text_to_type = action_data.get("text", "")
                        # Pour du code long, taper ligne par ligne
                        if len(text_to_type) > 500:
                            await self.page.keyboard.press("Delete")
                            await self.page.wait_for_timeout(100)
                            for line in text_to_type.split("\n"):
                                await self.page.keyboard.type(line, delay=1)
                                await self.page.keyboard.press("Enter")
                        else:
                            await self.page.keyboard.type(text_to_type, delay=5)

                    elif action == "press":
                        key = action_data.get("key", "Enter")
                        await self.page.keyboard.press(key)

                    elif action == "goto":
                        target_url = action_data.get("url", "")
                        if target_url:
                            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                            await self.page.wait_for_timeout(3000)

                    elif action == "scroll":
                        delta = action_data.get("amount", 300)
                        if action_data.get("direction") == "up":
                            delta = -delta
                        await self.page.mouse.wheel(0, delta)

                    elif action == "wait":
                        wait_s = min(action_data.get("seconds", 2), 5)
                        await self.page.wait_for_timeout(int(wait_s * 1000))

                    else:
                        messages.append({"role": "user", "content": [{"type": "text", "text": f"Action inconnue: '{action}'. Utilise une action valide."}]})
                        continue
                except Exception as action_err:
                    # Si le navigateur s'est ferme : on relance et on reprend
                    if self._is_browser_closed_error(action_err):
                        yield {"type": "thinking", "text": f"Navigateur ferme apres '{action}'. Relance en cours..."}
                        recovered = await self._recover_browser(last_url)
                        if not recovered:
                            yield {"type": "error", "message": "Impossible de relancer le navigateur apres fermeture inattendue."}
                            break
                        yield {"type": "thinking", "text": "Navigateur relance. Je continue la tache."}
                        # Prendre un nouveau screenshot et redonner le contexte au modele
                        try:
                            recovery_ss = await self._take_screenshot()
                            yield {"type": "screenshot", "data": recovery_ss}
                            messages.append({"role": "user", "content": [
                                {"type": "text", "text": f"Le navigateur a ete ferme apres l'action '{action}' et a ete relance. Nouveau screenshot ci-dessous. Reprends la tache."},
                                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": recovery_ss}},
                            ]})
                        except Exception:
                            pass
                        continue
                    # Autre erreur : on log mais on continue (l'agent verra le screenshot suivant)
                    yield {"type": "thinking", "text": f"Erreur action '{action}': {str(action_err)[:100]}"}
                    messages.append({"role": "user", "content": [{"type": "text", "text": f"L'action '{action}' a echoue : {str(action_err)[:200]}. Essaie une autre approche."}]})
                    continue

                # ── Screenshot apres action (avec recovery) ──
                try:
                    await self.page.wait_for_timeout(800)
                    new_ss = await self._take_screenshot()
                except Exception as ss_err:
                    if self._is_browser_closed_error(ss_err):
                        yield {"type": "thinking", "text": "Navigateur ferme pendant screenshot. Relance..."}
                        recovered = await self._recover_browser(last_url)
                        if not recovered:
                            yield {"type": "error", "message": "Impossible de relancer le navigateur."}
                            break
                        new_ss = await self._take_screenshot()
                        yield {"type": "thinking", "text": "Navigateur relance. Je continue la tache."}
                    else:
                        new_ss = self._latest_screenshot or ""
                yield {"type": "screenshot", "data": new_ss}

                # Verifier login/captcha apres action (via Haiku — pas cher)
                page_type = await self._is_login_or_captcha(new_ss)
                if page_type in ("login", "captcha", "payment"):
                    yield {"type": "thinking", "text": f"Page de {page_type} detectee apres action."}
                    async for event in self._ask_user(
                        f"{'Connexion requise' if page_type == 'login' else 'Captcha detecte' if page_type == 'captcha' else 'Paiement requis'}. "
                        f"Effectue l'action puis clique 'Effectue'.",
                        page_type,
                    ):
                        yield event
                    if self._user_action_result != "done":
                        yield {"type": "complete", "text": f"{page_type.capitalize()} abandonne."}
                        break
                    new_ss = await self._take_screenshot()
                    yield {"type": "screenshot", "data": new_ss}

                # ── Nettoyer les anciens screenshots du contexte (garder 2 max) ──
                img_indices = []
                for i, m in enumerate(messages):
                    if m.get("role") == "user" and isinstance(m.get("content"), list):
                        if any(isinstance(c, dict) and c.get("type") == "image" for c in m["content"]):
                            img_indices.append(i)
                for old_i in img_indices[:-2]:
                    messages[old_i]["content"] = [
                        c for c in messages[old_i]["content"]
                        if not (isinstance(c, dict) and c.get("type") == "image")
                    ]

                # Ajouter le nouveau screenshot au contexte
                feedback = f"Ecran apres l'action '{action}'. URL: {self.page.url}. Analyse et decide la prochaine etape."
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": feedback},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": new_ss}},
                ]})

        except Exception as e:
            logger.error(f"BrowserAgent error: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)[:300]}
        finally:
            await self._save_final_screenshot()
            self.is_running = False


# ── Session manager ──
_browser_agents: dict[str, BrowserAgent] = {}


def get_browser_agent(user_id: str, api_key: str) -> BrowserAgent:
    if user_id not in _browser_agents or not _browser_agents[user_id].is_running:
        _browser_agents[user_id] = BrowserAgent(api_key=api_key)
    return _browser_agents[user_id]


def get_active_browser_agent(user_id: str) -> Optional[BrowserAgent]:
    agent = _browser_agents.get(user_id)
    if agent and agent.is_running:
        return agent
    return None
