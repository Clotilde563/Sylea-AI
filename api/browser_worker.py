"""
Worker autonome pour l'automatisation TradingView.
Tourne dans un processus Python SEPARE (pas dans uvicorn).
Lit le code Pine Script depuis un fichier, ecrit les evenements en JSON sur stdout.

Usage: python browser_worker.py <code_file_path>
"""

import base64
import json
import os
import re
import sys
import time


# Anti-detection JavaScript — injecte dans TOUTES les pages (y compris popups OAuth)
ANTI_DETECT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['fr-FR', 'fr', 'en-US', 'en']
});
// Masquer la detection via permissions API
const _origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (
    p.name === 'notifications'
    ? Promise.resolve({state: Notification.permission})
    : _origQuery(p)
);
"""


def emit(event: dict) -> None:
    """Ecrit un evenement JSON sur stdout (line-delimited)."""
    print(json.dumps(event, ensure_ascii=False), flush=True)


def vision_decide(screenshot_b64: str, instruction: str, history: list[str] = None) -> dict:
    """Analyse un screenshot avec Claude Vision."""
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"action": "done", "success": False, "message": "No API key"}

    history_text = ""
    if history:
        history_text = "\n\nACTIONS DEJA EFFECTUEES:\n" + "\n".join(f"- {h}" for h in history[-6:])

    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": screenshot_b64},
        },
        {
            "type": "text",
            "text": f"""{instruction}{history_text}

Reponds en JSON pur avec UNE seule action:
{{"action":"click","x":<int>,"y":<int>,"reason":"..."}}
{{"action":"type","text":"...","reason":"..."}}
{{"action":"press","key":"Control+a","reason":"..."}}
{{"action":"scroll","direction":"down","reason":"..."}}
{{"action":"wait","seconds":2,"reason":"..."}}
{{"action":"done","success":true/false,"message":"..."}}

Viewport: 1280x800 pixels. Coordonnees (x,y) depuis le coin haut-gauche.
JSON UNIQUEMENT, pas de markdown.""",
        },
    ]

    try:
        with httpx.Client(timeout=45) as c:
            r = c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": content}],
                },
            )
            if r.status_code == 200:
                txt = r.json()["content"][0]["text"].strip()
                m = re.search(r"\{[^{}]*\}", txt, re.DOTALL)
                if m:
                    return json.loads(m.group())
    except Exception as e:
        emit({"type": "warning", "msg": f"Vision error: {e}"})

    return {"action": "done", "success": False, "message": "Vision analysis failed"}


def fix_pine_code(code: str, error: str) -> str | None:
    """Corrige un script Pine Script avec Claude."""
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 3000,
                    "messages": [{
                        "role": "user",
                        "content": f"""Corrige ce script Pine Script v6 qui a une erreur.

ERREUR: {error}

CODE:
{code}

Retourne UNIQUEMENT le code corrige. Pas de markdown. Commence par //@version=6""",
                    }],
                },
            )
            if r.status_code == 200:
                txt = r.json()["content"][0]["text"].strip()
                txt = re.sub(r"^```\w*\n?", "", txt)
                txt = re.sub(r"\n?```$", "", txt)
                return txt.strip()
    except Exception:
        pass
    return None


def screenshot_b64(page) -> str:
    data = page.screenshot(type="jpeg", quality=70)
    return base64.b64encode(data).decode()


def set_monaco_code(page, code: str) -> bool:
    """Injecte le code dans l'editeur Monaco via l'API JavaScript."""
    escaped = json.dumps(code)
    result = page.evaluate(f"""() => {{
        try {{
            // Methode 1 : API Monaco globale
            if (typeof monaco !== 'undefined') {{
                const editors = monaco.editor.getEditors();
                if (editors.length > 0) {{
                    editors[editors.length - 1].setValue({escaped});
                    return 'monaco_api';
                }}
            }}
        }} catch(e) {{}}

        try {{
            // Methode 2 : Chercher le modele Monaco
            if (typeof monaco !== 'undefined') {{
                const models = monaco.editor.getModels();
                if (models.length > 0) {{
                    models[models.length - 1].setValue({escaped});
                    return 'monaco_model';
                }}
            }}
        }} catch(e) {{}}

        return null;
    }}""")

    if result:
        emit({"type": "info", "msg": f"Code injecte via {result}"})
        return True

    # Fallback : selection tout + coller via le clavier
    emit({"type": "info", "msg": "Fallback clavier pour entrer le code..."})
    return False


def click_apply_button(page) -> bool:
    """Trouve et clique le bouton 'Add to chart' / 'Apply' dans le Pine Editor."""
    # Methode 1 : Chercher le bouton dans le tv-script-widget par sa position
    # (premier bouton dans la barre d'outils du script)
    clicked = page.evaluate("""() => {
        const panel = document.querySelector('.tv-script-widget');
        if (!panel) return null;

        // Chercher tous les boutons dans la barre du haut
        const btns = panel.querySelectorAll('button');
        for (const btn of btns) {
            const cls = btn.className || '';
            // Le bouton Apply/Add to chart a souvent la classe 'pending' ou est le premier bouton
            if (cls.includes('pending') || cls.includes('apply')) {
                btn.click();
                return 'pending_class';
            }
        }

        // Sinon prendre le premier bouton qui n'est PAS le dropdown titre
        for (const btn of btns) {
            const rect = btn.getBoundingClientRect();
            const text = btn.textContent.trim();
            // Le bouton Apply est entre le titre et le bouton Save
            // Position Y autour de 79, X entre 880 et 920
            if (rect.y > 60 && rect.y < 100 && rect.x > 850 && rect.x < 930
                && !text.includes('script') && !text.includes('Save') && !text.includes('More')) {
                btn.click();
                return 'position_match';
            }
        }

        return null;
    }""")

    if clicked:
        emit({"type": "info", "msg": f"Bouton Apply clique ({clicked})"})
        return True

    # Methode 2 : Selectors connus
    for sel in [
        ".tv-script-widget button:first-of-type",
        "button[class*='pending']",
        "[data-name='add-script-to-chart']",
        "button:has-text('Add to chart')",
        "button:has-text('Ajouter au graphique')",
        "button:has-text('Appliquer')",
        "button:has-text('Apply')",
    ]:
        try:
            page.click(sel, timeout=2000)
            emit({"type": "info", "msg": f"Apply clique via: {sel}"})
            return True
        except Exception:
            continue

    # Methode 3 : Raccourci clavier Ctrl+S puis chercher le bouton
    emit({"type": "info", "msg": "Tentative raccourci clavier..."})
    page.keyboard.press("Control+s")
    time.sleep(1)

    return False


def check_compilation_errors(page) -> dict:
    """Verifie s'il y a des erreurs de compilation Pine Script."""
    # Chercher les erreurs dans le DOM
    errors = page.evaluate("""() => {
        const results = [];

        // Erreurs dans le widget Pine Script
        const panel = document.querySelector('.tv-script-widget');
        if (panel) {
            // Chercher les elements d'erreur
            panel.querySelectorAll('[class*="error"], [class*="Error"], .monaco-editor .squiggly-error').forEach(el => {
                const text = el.textContent.trim();
                if (text) results.push(text.substring(0, 200));
            });
        }

        // Chercher les notifications/toasts d'erreur
        document.querySelectorAll('[class*="toast"], [class*="notification"], [class*="alert"]').forEach(el => {
            const text = el.textContent.trim();
            if (text && (text.toLowerCase().includes('error') || text.toLowerCase().includes('erreur') || text.includes('line '))) {
                results.push(text.substring(0, 200));
            }
        });

        // Chercher les erreurs dans la console Pine
        document.querySelectorAll('[class*="console"] [class*="error"], [class*="output"] [class*="error"]').forEach(el => {
            const text = el.textContent.trim();
            if (text) results.push(text.substring(0, 200));
        });

        return results;
    }""")

    if errors and len(errors) > 0:
        return {"has_errors": True, "errors": errors}

    return {"has_errors": False, "errors": []}


SESSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "tv_session.json",
)

# Profil navigateur persistant (conserve cookies + login entre les sessions)
BROWSER_PROFILE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".tv_browser_profile",
)


def check_logged_in(page) -> bool:
    """Verifie si l'utilisateur est connecte a TradingView."""
    return page.evaluate("""() => {
        // Indicateurs POSITIFS de connexion (fiables)
        // 1. Menu utilisateur avec avatar
        const userMenu = document.querySelector('[data-name="user-menu"]');
        if (userMenu) return true;

        // 2. Avatar dans le header
        const avatar = document.querySelector(
            'img[class*="avatar"], [class*="userAvatar"], [class*="profileAvatar"]'
        );
        if (avatar) return true;

        // 3. Lien vers le profil
        const profileLink = document.querySelector('a[href*="/u/"]');
        if (profileLink) return true;

        // 4. Cookies specifiques de session (via l'URL de l'API)
        // Non accessible directement, mais on peut verifier les elements de la page

        // Indicateurs NEGATIFS (pas connecte)
        // Bouton Sign in explicite
        const signInBtn = document.querySelector(
            '[data-name="header-user-menu-sign-in"]'
        );
        if (signInBtn) return false;

        // Bouton avec texte Sign in
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            const text = (btn.textContent || '').trim().toLowerCase();
            if (text === 'sign in' || text === 'se connecter' ||
                text === 'get started' || text === 'commencer') {
                return false;
            }
        }

        // Par defaut : NON connecte (plus sur que d'assumer connecte)
        return false;
    }""")


def handle_login(page, context) -> bool:
    """Gere la connexion TradingView — navigue vers la page de login
    et attend que l'utilisateur se connecte manuellement.
    NE PAS cliquer automatiquement sur Google (declenche l'anti-bot)."""
    emit({"type": "info", "msg": "Connexion a TradingView necessaire..."})

    # Aller sur la page de connexion
    try:
        page.goto(
            "https://www.tradingview.com/accounts/signin/",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        time.sleep(3)
    except Exception as e:
        emit({"type": "warning", "msg": f"Page de login: {e}"})

    scr = screenshot_b64(page)
    emit({"type": "browser", "msg": "Page de connexion TradingView", "screenshot": scr})
    emit({"type": "info", "msg": "Connectez-vous dans le navigateur (Google ou email/mot de passe) — 90s max..."})

    # Attendre que l'utilisateur se connecte (max 90s)
    for i in range(45):
        time.sleep(2)

        # Gerer les popups OAuth (Google, Apple, etc.)
        if len(context.pages) > 1:
            emit({"type": "info", "msg": "Popup OAuth detecte — completez la connexion..."})
            # Attendre que le popup se ferme (max 60s)
            for _ in range(60):
                if len(context.pages) <= 1:
                    emit({"type": "info", "msg": "Popup ferme"})
                    break
                time.sleep(1)
            time.sleep(3)

        # Verifier redirection apres login
        current_url = page.url
        if "/chart" in current_url or (
            "/accounts/" not in current_url
            and "tradingview.com" in current_url
        ):
            emit({"type": "success", "msg": "Connexion detectee (redirection) !"})
            return True

        if check_logged_in(page):
            emit({"type": "success", "msg": "Connexion reussie !"})
            return True

    emit({"type": "warning", "msg": "Timeout connexion (90s)"})
    return False


def main():
    if len(sys.argv) < 2:
        emit({"type": "final", "msg": "Usage: browser_worker.py <code_file>", "success": False})
        return

    code_file = sys.argv[1]
    max_retries = 2

    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()

    from playwright.sync_api import sync_playwright

    pw = None
    browser = None
    try:
        emit({"type": "info", "msg": "Lancement du navigateur..."})
        pw = sync_playwright().start()

        # Utiliser un profil persistant pour conserver les cookies/login
        os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
        context = pw.chromium.launch_persistent_context(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=False,
            channel="msedge",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--disable-popup-blocking",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
            ),
            locale="fr-FR",
            ignore_https_errors=True,
        )
        browser = context
        page = context.pages[0] if context.pages else context.new_page()

        # Anti-detection : injecter dans la page principale ET tous les popups
        page.add_init_script(ANTI_DETECT_JS)

        def _on_new_page(new_page):
            """Injecte l'anti-detection dans les popups (Google OAuth, etc.)."""
            try:
                new_page.add_init_script(ANTI_DETECT_JS)
                emit({"type": "info", "msg": "Anti-detection injecte dans popup"})
            except Exception:
                pass

        context.on("page", _on_new_page)
        page.route("**/*.{mp4,webm,ogg,mp3,wav}", lambda route: route.abort())

        # ── 1. Naviguer vers TradingView ──
        emit({"type": "info", "msg": "Navigation vers TradingView..."})
        page.goto(
            "https://www.tradingview.com/chart/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(6)

        # ── 2. Fermer popups & cookies ──
        for sel in [
            "button:has-text('Accept all')",
            "button:has-text('Accepter tout')",
            "button:has-text('Accept')",
            "button:has-text('Accepter')",
        ]:
            try:
                page.click(sel, timeout=2000)
                emit({"type": "info", "msg": "Cookies acceptes"})
                time.sleep(1)
                break
            except Exception:
                continue

        for sel in [
            "button[aria-label='Close']",
            "button[aria-label='Fermer']",
            ".tv-dialog__close",
            "[data-name='close']",
        ]:
            try:
                page.click(sel, timeout=1500)
                time.sleep(0.5)
            except Exception:
                continue

        time.sleep(2)
        scr = screenshot_b64(page)
        emit({"type": "browser", "msg": "TradingView charge", "screenshot": scr})

        # ── 2b. Verifier la connexion ──
        if not check_logged_in(page):
            login_ok = handle_login(page, context)
            if not login_ok:
                emit({
                    "type": "warning",
                    "msg": "Non connecte — tentative sans login",
                })
            else:
                # Recharger la page apres login
                page.goto(
                    "https://www.tradingview.com/chart/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                time.sleep(4)
        else:
            emit({"type": "success", "msg": "Connecte a TradingView"})

        # ── 3. Ouvrir Pine Editor ──
        emit({"type": "info", "msg": "Ouverture du Pine Editor..."})
        pine_opened = False

        # Methode principale : data-name='pine-dialog-button'
        try:
            page.click("[data-name='pine-dialog-button']", timeout=5000)
            pine_opened = True
            emit({"type": "success", "msg": "Pine Editor ouvert (pine-dialog-button)"})
            time.sleep(2)
        except Exception:
            pass

        # Fallback : autres selecteurs
        if not pine_opened:
            for sel in [
                "[data-name='pine-editor']",
                "[data-name='scripteditor']",
                "button:has-text('Pine Editor')",
                "button:has-text('Editeur Pine')",
                "button:has-text('Pine')",
                "button[id*='pine']",
            ]:
                try:
                    page.click(sel, timeout=2000)
                    pine_opened = True
                    emit({"type": "success", "msg": f"Pine Editor ouvert ({sel})"})
                    time.sleep(2)
                    break
                except Exception:
                    continue

        # Fallback Vision
        if not pine_opened:
            emit({"type": "info", "msg": "Analyse visuelle pour trouver le Pine Editor..."})
            scr = screenshot_b64(page)
            decision = vision_decide(
                scr,
                "Sur cette page TradingView, trouve un bouton ou icone pour ouvrir "
                "le Pine Editor (editeur de code Pine Script). "
                "Regarde dans la barre d'outils en haut, les icones sur les cotes, "
                "ou la barre en bas. Clique dessus.",
            )
            if decision.get("action") == "click":
                page.mouse.click(decision["x"], decision["y"])
                pine_opened = True
                emit({"type": "success", "msg": f"Pine Editor via Vision: {decision.get('reason', '')}"})
                time.sleep(2)

        if not pine_opened:
            scr = screenshot_b64(page)
            emit({
                "type": "final",
                "msg": "Pine Editor introuvable",
                "screenshot": scr,
                "success": False,
            })
            return

        # ── 4. Boucle: code -> compile -> check ──
        current_code = code
        vision_history = []

        for attempt in range(max_retries + 1):
            scr = screenshot_b64(page)
            emit({
                "type": "browser",
                "msg": f"Editeur Pine - tentative {attempt + 1}/{max_retries + 1}",
                "screenshot": scr,
            })

            # ── 4a. Entrer le code dans l'editeur Monaco ──
            lines_count = len(current_code.splitlines())
            emit({"type": "info", "msg": f"Injection du code ({lines_count} lignes)..."})

            # Cliquer dans l'editeur pour le focus
            editor_focused = False
            try:
                page.click(".monaco-editor.pine-editor-monaco", timeout=3000)
                editor_focused = True
                time.sleep(0.5)
            except Exception:
                # Fallback : cliquer via Vision
                scr = screenshot_b64(page)
                decision = vision_decide(
                    scr,
                    "Clique au CENTRE de la zone d'edition de code Pine Script. "
                    "C'est la zone avec un fond clair/blanc contenant du code. "
                    "PAS dans les boutons, PAS dans les onglets.",
                    vision_history,
                )
                if decision.get("action") == "click":
                    page.mouse.click(decision["x"], decision["y"])
                    editor_focused = True
                    time.sleep(0.5)

            # Injecter le code via Monaco API
            code_injected = set_monaco_code(page, current_code)

            if not code_injected:
                # Fallback clavier : Ctrl+A, Delete, puis insertion texte
                emit({"type": "info", "msg": "Injection via clavier..."})
                page.keyboard.press("Control+a")
                time.sleep(0.3)
                page.keyboard.press("Delete")
                time.sleep(0.3)
                # Pour le clavier, inserer ligne par ligne
                page.keyboard.insert_text(current_code)
                time.sleep(1)

            time.sleep(1.5)

            scr = screenshot_b64(page)
            emit({"type": "browser", "msg": "Code injecte dans l'editeur", "screenshot": scr})

            # ── 4b. Compiler / Ajouter au graphique ──
            emit({"type": "info", "msg": "Compilation — ajout au graphique..."})

            applied = click_apply_button(page)

            if not applied:
                # Dernier recours : Vision
                scr = screenshot_b64(page)
                decision = vision_decide(
                    scr,
                    "Trouve le bouton pour APPLIQUER ou AJOUTER le script Pine au graphique. "
                    "Cherche un bouton qui ressemble a 'Add to chart', 'Apply', 'Ajouter', "
                    "ou une icone de lecture/play dans la barre d'outils du Pine Editor "
                    "(en haut du panneau de droite).",
                    vision_history,
                )
                if decision.get("action") == "click":
                    page.mouse.click(decision["x"], decision["y"])
                    applied = True
                    emit({"type": "info", "msg": f"Apply via Vision: {decision.get('reason', '')}"})

            time.sleep(5)

            # ── 4c. Verifier les erreurs ──
            emit({"type": "info", "msg": "Verification du resultat..."})

            # D'abord verifier via le DOM
            error_result = check_compilation_errors(page)

            if error_result["has_errors"]:
                error_msg = " | ".join(error_result["errors"][:3])
                emit({"type": "error", "msg": f"Erreur: {error_msg}"})

                if attempt < max_retries:
                    emit({"type": "info", "msg": f"Correction auto ({attempt + 2}/{max_retries + 1})..."})
                    fixed = fix_pine_code(current_code, error_msg)
                    if fixed and fixed != current_code:
                        current_code = fixed
                        emit({"type": "info", "msg": f"Code corrige ({len(fixed.splitlines())} lignes)"})
                        continue
                    else:
                        final_scr = screenshot_b64(page)
                        emit({
                            "type": "final",
                            "msg": f"Correction impossible: {error_msg}",
                            "screenshot": final_scr,
                            "success": False,
                        })
                        return
                else:
                    final_scr = screenshot_b64(page)
                    emit({
                        "type": "final",
                        "msg": f"Echec apres {max_retries + 1} tentatives: {error_msg}",
                        "screenshot": final_scr,
                        "success": False,
                    })
                    return

            # Si pas d'erreur DOM, verifier via Vision
            scr = screenshot_b64(page)
            error_check = vision_decide(
                scr,
                "Analyse cette capture TradingView APRES compilation d'un script Pine Script.\n"
                "Y a-t-il des ERREURS visibles (texte rouge, messages d'erreur, 'Error', 'Line X:') ?\n"
                "Y a-t-il un INDICATEUR visible sur le graphique (nouvelles lignes, signaux) ?\n"
                "SI ERREUR : {\"action\":\"done\",\"success\":false,\"message\":\"ERREUR: [texte exact de l'erreur]\"}\n"
                "SI SUCCES ou PAS D'ERREUR VISIBLE : {\"action\":\"done\",\"success\":true,\"message\":\"Script applique\"}",
                vision_history,
            )

            if error_check.get("success", False):
                emit({"type": "success", "msg": "Script compile et applique avec succes !"})
                # Session sauvegardee via le profil persistant
                final_scr = screenshot_b64(page)
                emit({
                    "type": "final",
                    "msg": error_check.get("message", "Indicateur compile"),
                    "screenshot": final_scr,
                    "success": True,
                })
                return
            else:
                error_msg = error_check.get("message", "Erreur inconnue")
                emit({"type": "error", "msg": f"Erreur Vision: {error_msg}"})

                if attempt < max_retries:
                    emit({"type": "info", "msg": f"Correction auto ({attempt + 2}/{max_retries + 1})..."})
                    fixed = fix_pine_code(current_code, error_msg)
                    if fixed and fixed != current_code:
                        current_code = fixed
                        emit({"type": "info", "msg": f"Code corrige ({len(fixed.splitlines())} lignes)"})
                    else:
                        final_scr = screenshot_b64(page)
                        emit({
                            "type": "final",
                            "msg": f"Correction impossible: {error_msg}",
                            "screenshot": final_scr,
                            "success": False,
                        })
                        return
                else:
                    final_scr = screenshot_b64(page)
                    emit({
                        "type": "final",
                        "msg": f"Echec: {error_msg}",
                        "screenshot": final_scr,
                        "success": False,
                    })
                    return

    except Exception as e:
        emit({"type": "error", "msg": f"Erreur: {e}"})
        scr = None
        try:
            if browser:
                scr = screenshot_b64(page)
        except Exception:
            pass
        emit({"type": "final", "msg": f"Erreur: {e}", "screenshot": scr, "success": False})
    finally:
        try:
            if context:
                context.close()
            if pw:
                pw.stop()
        except Exception:
            pass


def login_only():
    """Mode login : ouvre TradingView, attend que l'utilisateur se connecte,
    et sauvegarde la session dans le profil persistant."""
    from playwright.sync_api import sync_playwright

    pw = None
    context = None
    try:
        emit({"type": "info", "msg": "Mode connexion — ouverture du navigateur..."})
        pw = sync_playwright().start()

        os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
        context = pw.chromium.launch_persistent_context(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=False,
            channel="msedge",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--disable-popup-blocking",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
            ),
            locale="fr-FR",
            ignore_https_errors=True,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Anti-detection sur la page principale ET tous les popups (OAuth Google, etc.)
        page.add_init_script(ANTI_DETECT_JS)

        def _on_popup(new_page):
            try:
                new_page.add_init_script(ANTI_DETECT_JS)
                emit({"type": "info", "msg": "Anti-detection injecte dans popup OAuth"})
            except Exception:
                pass

        context.on("page", _on_popup)

        # Accepter cookies d'abord
        page.goto("https://www.tradingview.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        for sel in ["button:has-text('Accept all')", "button:has-text('Accepter tout')"]:
            try:
                page.click(sel, timeout=2000)
                time.sleep(1)
                break
            except Exception:
                continue

        # Naviguer vers la page de connexion
        page.goto("https://www.tradingview.com/accounts/signin/", wait_until="domcontentloaded", timeout=15000)
        time.sleep(3)

        scr = screenshot_b64(page)
        emit({"type": "browser", "msg": "Page de connexion TradingView", "screenshot": scr})
        emit({"type": "info", "msg": "Connectez-vous dans le navigateur (Google ou email/mot de passe)..."})
        emit({"type": "info", "msg": "Le navigateur reste ouvert 120 secondes."})

        # Attendre que l'utilisateur se connecte (max 120s)
        for i in range(60):
            time.sleep(2)

            # Gerer les popups OAuth (Google, Apple, etc.)
            if len(context.pages) > 1:
                emit({"type": "info", "msg": "Popup OAuth detecte — completez la connexion..."})
                for _ in range(60):
                    if len(context.pages) <= 1:
                        emit({"type": "info", "msg": "Popup ferme"})
                        break
                    time.sleep(1)
                time.sleep(3)

            # Verifier redirection apres login
            current_url = page.url
            if "/chart" in current_url or (
                "/accounts/" not in current_url
                and "tradingview.com" in current_url
            ):
                emit({"type": "success", "msg": "Connexion reussie !"})
                emit({"type": "success", "msg": "Session sauvegardee (profil persistant)"})
                emit({"type": "final", "msg": "Connexion sauvegardee", "success": True})
                return

            if check_logged_in(page):
                emit({"type": "success", "msg": "Connexion detectee !"})
                emit({"type": "final", "msg": "Connexion sauvegardee", "success": True})
                return

        emit({"type": "final", "msg": "Timeout (120s) — reessayez", "success": False})

    except Exception as e:
        emit({"type": "final", "msg": f"Erreur: {e}", "success": False})
    finally:
        # Fermer proprement — les cookies sont sauvegardes dans le profil persistant
        try:
            if context:
                time.sleep(1)  # Laisser le temps de flusher les cookies
                context.close()
            if pw:
                pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--login":
        login_only()
    else:
        main()
