"""
Agent 3 — Dispatcher d'actions pour la boucle agentique native.

Pont entre les `tool_use` du LLM (via AgenticLoop) et les primitives existantes
(openclaw_web_search, _save_memory, etc.).

Ce dispatcher commence avec un sous-ensemble d'actions "safe" (lectures / memoire)
et grandit progressivement. Les actions non encore portees remontent un
`is_error=True` explicite au LLM pour qu'il sache qu'il doit choisir une autre voie.

Actions actuellement supportees nativement :
  - SEARCH      (web search via OpenClaw DuckDuckGo)
  - X_SEARCH    (X/Twitter via xAI Grok)
  - WEB_FETCH   (recuperer une URL)
  - MEMORY      (sauvegarder dans la memoire long-terme)
  - MEMORY_SEARCH (chercher dans la memoire)

Actions destructives (EMAIL, GMAIL_SEND, COMPUTER_USE, FILE_CREATE, ...) ne sont
PAS encore routees ici : elles continuent a passer par le parser legacy
`[ACTION:X]` avec la politique de confirmation. Les ajouter ici requiert
d'extraire les handlers de agent3_openclaw.py en fonctions standalone
(refactor a faire en phase 2).
"""

from __future__ import annotations

import logging
from typing import Any

from sylea.core.storage.database import DatabaseManager
from api.agent3_security import (
    validate_external_url,
    check_rate_limit,
    audit_log_action_async,
    is_destructive,
    ensure_within_base,
    friendly_http_error,
    friendly_exception_message,
)

logger = logging.getLogger("agent3.dispatcher")

# Caps en dur pour limiter l'abus par un LLM en boucle.
_MAX_QUERY_LEN = 2000
_MAX_BODY_CHARS = 100_000  # body email / file / drive
_COMPUTER_USE_TIMEOUT_S = 10 * 60  # cap dur sur la session Computer Use


class Agent3ActionDispatcher:
    """Execute les tool_use recus par l'AgenticLoop.

    Contract (ActionExecutor protocol) :
        async def execute(action_type: str, action_input: dict) -> dict
    Retourne : {"content": str, "is_error": bool, "raw": Any}
    """

    # Actions supportees nativement. Le reste remonte une erreur pedagogique au LLM.
    # Note : les tools dynamiques `skill_*` et `clawhub_*` sont supportes via
    # prefix-matching dans execute() — pas listes ici.
    SUPPORTED: set[str] = {
        # Read-only / network
        "SEARCH",
        "X_SEARCH",
        "WEB_FETCH",
        "BROWSER",       # Phase 14I : Playwright headless (pages JS-heavy)
        "SCREENSHOT",    # Phase 14I : capture PNG d'une URL
        # Memoire
        "MEMORY",
        "MEMORY_SEARCH",
        "SEMANTIC_SEARCH",    # RAG : recherche semantique top-k dans les docs ingeres
        "PYTHON_EXEC",        # Sandbox Python (data analysis, calculs)
        "DEEP_RESEARCH",      # Sous-agent de recherche profonde multi-tours
        "VISION_ANALYZE",     # Analyse d'une image uploadee via Claude Vision
        # Generation locale (pas d'effet externe)
        "PDF",
        "CODE",
        "CANVAS",
        # Read-only avec auth externe
        "FILE_READ",
        "CALENDAR_LIST",
        "GMAIL_READ",
        # Destructives (necessitent confirmation via AgenticLoop.DESTRUCTIVE_ACTIONS)
        "FILE_CREATE",
        "EMAIL",
        "GMAIL_SEND",
        "CALENDAR_EVENT",
        "DRIVE_SAVE",
        "CRON",
        "REMINDER",
        "COMPUTER_USE",
        # Phase 14L : generation media native (OpenAI DALL-E + TTS direct,
        # bypass Gateway pour eviter dependance sur skills externes type ai-image
        # qui requierent leurs propres cles API).
        "IMAGE_GEN",
        "TTS_GEN",
        # Delegation a un sous-agent (non destructif, mais meta-outil special)
        "SPAWN_AGENT",
        "OPENCLAW_SESSION",  # Phase 14J : session OpenClaw avec acces complet aux tools
        # Planification / tracker (non destructif, in-memory)
        "TODO_WRITE",
        # Phase 4 : meta-tools ClawHub
        # CLAWHUB_SEARCH : recherche dans le registre (read-only)
        # CLAWHUB_INSTALL : telecharge et installe un skill tiers (destructive)
        # CLAWHUB_PUBLISH : publie un skill (destructive, actions utilisateur)
        "CLAWHUB_SEARCH",
        "CLAWHUB_INSTALL",
        "CLAWHUB_PUBLISH",
    }

    # Phase 4 : prefixes de tools dispatches dynamiquement (non listes dans SUPPORTED)
    _DYNAMIC_SKILL_PREFIX = "SKILL_"

    # Phase 5 : set des noms Anthropic des 38 outils OpenClaw directs.
    # Init lazy (a l'import de api.openclaw_tool_schemas) pour eviter circular.
    _OPENCLAW_DIRECT_TOOL_NAMES: set[str] | None = None

    @classmethod
    def _get_openclaw_direct_names(cls) -> set[str]:
        if cls._OPENCLAW_DIRECT_TOOL_NAMES is None:
            try:
                from api.openclaw_tool_schemas import all_anthropic_tool_names
                cls._OPENCLAW_DIRECT_TOOL_NAMES = all_anthropic_tool_names()
            except Exception as e:
                logger.warning(f"Cannot load OpenClaw direct tool names: {e}")
                cls._OPENCLAW_DIRECT_TOOL_NAMES = set()
        return cls._OPENCLAW_DIRECT_TOOL_NAMES

    async def _user_daily_cap_usd(self) -> float:
        """Retourne le cap USD/jour pour ce user (prefs ou defaut global).

        Migration PG : converti en async pour appeler _get_user_preferences_async.
        """
        from api.openclaw_bridge import DEFAULT_DAILY_COST_CAP_USD
        if not self.user_id:
            return DEFAULT_DAILY_COST_CAP_USD
        try:
            # Resolution dynamique (evite import circulaire).
            from api.routers.agent3_openclaw import _get_user_preferences_async
            prefs = await _get_user_preferences_async(self.user_id)
            cap = prefs.get("external_cost_cap_usd_per_day")
            if isinstance(cap, (int, float)) and cap >= 0:
                return float(cap)
        except Exception:
            pass
        return DEFAULT_DAILY_COST_CAP_USD

    def __init__(
        self,
        db: DatabaseManager,
        user_id: str | None,
        session_key: str | None,
    ):
        self.db = db
        self.user_id = user_id or ""
        self.session_key = session_key

    async def execute(self, action_type: str, action_input: dict) -> dict:
        """Route un tool_use vers sa primitive. Ne leve jamais d'exception
        (toutes les erreurs sont retournees via is_error=True)."""
        result = await self._execute_inner(action_type, action_input)
        # Audit log best-effort pour les actions destructives.
        if is_destructive(action_type):
            await audit_log_action_async(
                self.user_id or None,
                action_type,
                action_input if isinstance(action_input, dict) else {},
                success=not bool(result.get("is_error")),
                error_message=(
                    str(result.get("content", ""))[:500]
                    if result.get("is_error") else ""
                ),
            )
        return result

    async def _execute_inner(self, action_type: str, action_input: dict) -> dict:
        """Dispatch reel. execute() ajoute l'audit log autour."""
        # Rate-limit par (user, action) — applique aux actions listees dans
        # DEFAULT_LIMITS. Pour les autres (skill_*, clawhub_*) on ne limite pas
        # ici (au besoin, ajouter une cle dans DEFAULT_LIMITS).
        from api.agent3_security import DEFAULT_LIMITS as _LIMITS
        if action_type in _LIMITS:
            ok, retry = check_rate_limit(self.user_id or None, action_type)
            if not ok:
                retry_s = int(retry) + 1
                human_action = {
                    "WEB_FETCH": "consulter une page web",
                    "SEARCH": "lancer une recherche",
                    "X_SEARCH": "chercher sur X",
                    "EMAIL": "envoyer un email",
                    "GMAIL_SEND": "envoyer un email",
                    "CALENDAR_EVENT": "creer un evenement",
                    "DRIVE_SAVE": "sauvegarder sur Drive",
                    "CRON": "programmer une tache",
                    "COMPUTER_USE": "utiliser Computer Use",
                }.get(action_type, action_type.lower())
                return {
                    "content": (
                        f"Tu as fait beaucoup de demandes pour {human_action}. "
                        f"Reessaie dans {retry_s} seconde{'s' if retry_s > 1 else ''}."
                    ),
                    "is_error": True,
                    "raw": {
                        "rate_limited": True,
                        "retry_after_s": retry,
                        "action": action_type,
                    },
                }

        # Phase 4 : tools dynamiques `skill_*` — dispatch vers le skill executor.
        if action_type.startswith(self._DYNAMIC_SKILL_PREFIX):
            try:
                from api.agent3_skills.skill_executor import dispatch_skill_invocation
                return await dispatch_skill_invocation(
                    tool_name=action_type.lower(),
                    tool_input=action_input,
                    auth_user_id=self.user_id,
                    db=self.db,
                )
            except TypeError:
                # Fallback backward-compat si dispatch_skill_invocation n'a pas
                # encore recu le parametre auth_user_id ou db.
                from api.agent3_skills.skill_executor import dispatch_skill_invocation
                try:
                    return await dispatch_skill_invocation(
                        tool_name=action_type.lower(),
                        tool_input=action_input,
                        auth_user_id=self.user_id,
                    )
                except TypeError:
                    return await dispatch_skill_invocation(
                        tool_name=action_type.lower(),
                        tool_input=action_input,
                    )
            except Exception as e:
                logger.exception(f"Skill dispatcher crashed on {action_type}: {e}")
                return {
                    "content": f"Erreur skill `{action_type}`: {str(e)[:300]}",
                    "is_error": True,
                    "raw": {"exception": type(e).__name__},
                }

        # Phase 4 : meta-tools ClawHub — dispatch vers clawhub_meta_tools.
        # Chaque appel est logge dans agent3_clawhub_events pour historique
        # d'auto-extension (visible par l'utilisateur dans l'UI /outils).
        if action_type in {"CLAWHUB_SEARCH", "CLAWHUB_INSTALL", "CLAWHUB_PUBLISH"}:
            result: dict = {}
            try:
                from api.agent3_skills.clawhub_meta_tools import dispatch_clawhub_meta_tool
                result = await dispatch_clawhub_meta_tool(
                    tool_name=action_type.lower(),
                    tool_input=action_input,
                    auth_user_id=self.user_id,
                )
            except Exception as e:
                logger.exception(f"Meta-tool dispatcher crashed on {action_type}: {e}")
                result = {
                    "content": f"Erreur meta-tool `{action_type}`: {str(e)[:300]}",
                    "is_error": True,
                    "raw": {"exception": type(e).__name__},
                }

            # Log dans agent3_clawhub_events (best-effort, n'interrompt pas le flux).
            try:
                from api.routers.agent3_openclaw import _log_clawhub_event_async

                event_map = {
                    "CLAWHUB_SEARCH": "auto_search",
                    "CLAWHUB_INSTALL": "auto_install",
                    "CLAWHUB_PUBLISH": "auto_publish",
                }
                event_type = event_map.get(action_type, "auto_unknown")

                # Slug : pour INSTALL/PUBLISH c'est action_input.slug,
                # pour SEARCH on logue la query tronquee en guise de slug.
                slug_value = (
                    str(action_input.get("slug") or "")
                    or str(action_input.get("query") or "")
                )[:100]

                # Trigger context : task courante si dispo, sinon tool_input condense.
                trigger_parts = []
                if action_input.get("query"):
                    trigger_parts.append(f"query={action_input['query']}")
                if action_input.get("name"):
                    trigger_parts.append(f"name={action_input['name']}")
                if action_input.get("description"):
                    trigger_parts.append(f"desc={action_input['description'][:80]}")
                trigger_context = " | ".join(trigger_parts)[:500]

                success = not bool(result.get("is_error"))
                error_message = ""
                if not success:
                    error_message = str(result.get("content", ""))[:500]

                if self.user_id:
                    await _log_clawhub_event_async(
                        self.user_id,
                        event_type,
                        slug_value or "(none)",
                        trigger_context=trigger_context,
                        success=success,
                        error_message=error_message,
                    )
            except Exception as log_exc:
                logger.debug(f"Failed to log clawhub event: {log_exc}")

            return result

        # Phase 5 : outils OpenClaw directs (38 tools) — routes vers Gateway.
        # IMPORTANT : priorite au handler natif (SUPPORTED). Si action_type est
        # dans SUPPORTED, on prend le natif. Sinon, si le nom lowercase matche
        # un outil OpenClaw expose, on route vers le Gateway.
        if action_type not in self.SUPPORTED:
            _openclaw_names = self._get_openclaw_direct_names()
            _action_lower = action_type.lower()
            if _action_lower in _openclaw_names:
                return await self._openclaw_direct(_action_lower, action_input)
            return self._not_implemented(action_type)

        try:
            if action_type == "SEARCH":
                return await self._search(action_input)
            if action_type == "X_SEARCH":
                return await self._x_search(action_input)
            if action_type == "WEB_FETCH":
                return await self._web_fetch(action_input)
            if action_type == "BROWSER":
                return await self._browser(action_input)
            if action_type == "SCREENSHOT":
                # Raccourci : SCREENSHOT = BROWSER avec action='screenshot'.
                inp_screen = dict(action_input)
                inp_screen["action"] = "screenshot"
                return await self._browser(inp_screen)
            if action_type == "MEMORY":
                return await self._memory_save(action_input)
            if action_type == "MEMORY_SEARCH":
                return await self._memory_search(action_input)
            if action_type == "SEMANTIC_SEARCH":
                return await self._semantic_search(action_input)
            if action_type == "PYTHON_EXEC":
                return await self._python_exec(action_input)
            if action_type == "DEEP_RESEARCH":
                return await self._deep_research(action_input)
            if action_type == "VISION_ANALYZE":
                return await self._vision_analyze(action_input)
            if action_type == "PDF":
                return self._pdf(action_input)
            if action_type == "CODE":
                return self._code(action_input)
            if action_type == "CANVAS":
                return self._canvas(action_input)
            if action_type == "FILE_READ":
                return self._file_read(action_input)
            if action_type == "CALENDAR_LIST":
                return await self._calendar_list(action_input)
            if action_type == "GMAIL_READ":
                return await self._gmail_read(action_input)
            if action_type == "FILE_CREATE":
                return await self._file_create(action_input)
            if action_type == "EMAIL":
                return await self._email(action_input)
            if action_type == "GMAIL_SEND":
                return await self._gmail_send(action_input)
            if action_type == "CALENDAR_EVENT":
                return await self._calendar_event(action_input)
            if action_type == "DRIVE_SAVE":
                return await self._drive_save(action_input)
            if action_type == "CRON":
                return await self._cron(action_input)
            if action_type == "REMINDER":
                return await self._reminder(action_input)
            if action_type == "COMPUTER_USE":
                return await self._computer_use(action_input)
            if action_type == "SPAWN_AGENT":
                return await self._spawn_agent(action_input)
            if action_type == "OPENCLAW_SESSION":
                return await self._openclaw_session(action_input)
            if action_type == "TODO_WRITE":
                return self._todo_write(action_input)
            if action_type == "IMAGE_GEN":
                return await self._image_gen(action_input)
            if action_type == "TTS_GEN":
                return await self._tts_gen(action_input)
        except Exception as e:
            logger.exception(f"Dispatcher crashed on {action_type}: {e}")
            return {
                "content": f"Erreur technique lors de l'execution de {action_type}: {str(e)[:300]}",
                "is_error": True,
                "raw": {"exception": type(e).__name__},
            }

        return self._not_implemented(action_type)

    # ── Handlers individuels ────────────────────────────────────────────────

    async def _search(self, inp: dict) -> dict:
        from api.openclaw_bridge import openclaw_web_search

        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' manquant.", "is_error": True, "raw": {}}
        if len(query) > _MAX_QUERY_LEN:
            return {
                "content": f"Query trop longue ({len(query)} chars, max {_MAX_QUERY_LEN}).",
                "is_error": True, "raw": {},
            }
        max_results = min(max(int(inp.get("max_results") or 5), 1), 20)

        resp = await openclaw_web_search(
            query=query, session_key=self.session_key, max_results=max_results,
        )
        if resp.error:
            return {
                "content": f"Recherche echouee : {resp.error}",
                "is_error": True,
                "raw": {"error": resp.error},
            }
        content = resp.content or "(aucun resultat)"
        return {
            "content": content[:4000],  # cap pour economiser les tokens
            "is_error": False,
            "raw": {"query": query, "full_content_len": len(content)},
        }

    async def _x_search(self, inp: dict) -> dict:
        from api.openclaw_bridge import openclaw_x_search

        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' manquant.", "is_error": True, "raw": {}}
        if len(query) > _MAX_QUERY_LEN:
            return {
                "content": f"Query trop longue ({len(query)} chars, max {_MAX_QUERY_LEN}).",
                "is_error": True, "raw": {},
            }

        raw = await openclaw_x_search(query=query, session_key=self.session_key)
        # openclaw_x_search retourne un dict (pas OpenClawResponse).
        if raw.get("error"):
            return {
                "content": f"Recherche X echouee : {raw['error']}",
                "is_error": True,
                "raw": {"error": raw["error"]},
            }
        results = raw.get("results", []) or raw.get("posts", [])
        if not results:
            return {"content": "Aucun post trouve.", "is_error": False, "raw": raw}
        # Synthese texte des 10 premiers posts
        lines = []
        for p in results[:10]:
            author = p.get("author") or p.get("user", "?")
            text = (p.get("text") or p.get("content", ""))[:200]
            lines.append(f"@{author}: {text}")
        content = "\n".join(lines)
        return {"content": content, "is_error": False, "raw": raw}

    async def _web_fetch(self, inp: dict) -> dict:
        url = (inp.get("url") or "").strip()
        ok, err = validate_external_url(url)
        if not ok:
            return {
                "content": f"URL refusee : {err}",
                "is_error": True,
                "raw": {"url": url, "reason": err},
            }
        # httpx async via pool partage (evite le cout TCP/TLS/DNS a chaque call).
        import httpx
        from api.agent3_http import get_http_client
        try:
            client = get_http_client()
            # follow_redirects=False (deja la valeur par defaut du pool) :
            # empeche qu'une URL publique redirige vers une cible interne
            # (attaque SSRF via redirect). On gere manuellement jusqu'a 3 hops,
            # chacun revalide par validate_external_url().
            current = url
            last_status = 0
            for _ in range(4):  # 1 initial + 3 redirects max
                r = await client.get(current, timeout=30.0)
                last_status = r.status_code
                if r.status_code in (301, 302, 303, 307, 308):
                    nxt = r.headers.get("location", "").strip()
                    if not nxt:
                        break
                    # Resolution relative -> absolue
                    from urllib.parse import urljoin
                    current = urljoin(current, nxt)
                    ok2, err2 = validate_external_url(current)
                    if not ok2:
                        return {
                            "content": f"Redirection refusee : {err2}",
                            "is_error": True,
                            "raw": {"url": url, "blocked_redirect": current, "reason": err2},
                        }
                    continue
                r.raise_for_status()
                full_text = r.text
                text = full_text[:8000]
                # Auto-ingest dans le RAG si le contenu est long (> 8k chars)
                # et que l'user est authentifie. Permet ensuite de retrouver
                # le contenu complet via SEMANTIC_SEARCH.
                ingested = None
                if self.user_id and len(full_text) > 8000:
                    try:
                        from api.rag import ingest_text
                        ingested = await ingest_text(
                            self.db, self.user_id, full_text,
                            source_type="web_fetch",
                            source_ref=current,
                            scope="global",
                            metadata={"status": r.status_code, "total_chars": len(full_text)},
                        )
                    except Exception as _ie:
                        logger.debug(f"RAG ingest web_fetch failed: {_ie}")
                rag_note = ""
                if ingested and ingested.get("ingested_chunks", 0) > 0:
                    rag_note = (
                        f"\n\n[...Contenu complet ({len(full_text)} chars) ingere dans la "
                        f"memoire semantique ({ingested['ingested_chunks']} chunks). "
                        "Utilise SEMANTIC_SEARCH pour retrouver des passages precis.]"
                    )
                return {
                    "content": text + rag_note,
                    "is_error": False,
                    "raw": {
                        "url": current, "status": r.status_code, "size": len(full_text),
                        "rag_ingested": ingested,
                    },
                }
            return {
                "content": f"Trop de redirections depuis {url} (dernier status {last_status}).",
                "is_error": True,
                "raw": {"url": url, "status": last_status},
            }
        except httpx.HTTPStatusError as e:
            return {
                "content": friendly_http_error(e.response.status_code, context=url),
                "is_error": True,
                "raw": {"url": url, "status": e.response.status_code},
            }
        except httpx.TimeoutException:
            return {
                "content": f"Le serveur {url} met trop de temps a repondre.",
                "is_error": True,
                "raw": {"url": url, "error": "timeout"},
            }
        except httpx.HTTPError as e:
            return {
                "content": friendly_exception_message(e, fallback=f"Erreur reseau sur {url}"),
                "is_error": True,
                "raw": {"url": url, "error": str(e)},
            }
        except Exception as e:
            return {
                "content": friendly_exception_message(e, fallback="Erreur inattendue lors de la consultation."),
                "is_error": True,
                "raw": {"url": url, "error": str(e)},
            }

    async def _browser(self, inp: dict) -> dict:
        """Phase 14I : tool BROWSER natif via Playwright Chromium headless.

        Actions :
          - read       : retourne le texte rendu apres execution JS
          - screenshot : retourne un PNG (sauve sur disque + URL servable)
          - html       : retourne le DOM brut (post-render)
          - eval       : evalue un JS et retourne le resultat (sandboxed dans la page)
        """
        url = (inp.get("url") or "").strip()
        ok, err = validate_external_url(url)
        if not ok:
            return {
                "content": f"URL refusee : {err}",
                "is_error": True,
                "raw": {"url": url, "reason": err},
            }
        action = (inp.get("action") or "read").strip().lower()
        if action not in ("read", "screenshot", "html", "eval"):
            return {
                "content": f"Action inconnue : {action} (read|screenshot|html|eval)",
                "is_error": True, "raw": {},
            }
        timeout_ms = max(2000, min(int(inp.get("timeout_ms") or 15000), 60000))
        wait_for = (inp.get("wait_for") or "").strip()
        script = (inp.get("script") or "").strip()

        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError:
            return {
                "content": "Playwright non installe. pip install playwright + python -m playwright install chromium.",
                "is_error": True,
                "raw": {"url": url, "error": "playwright_missing"},
            }

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36 SyleaBrowser/1.0"
                        ),
                        viewport={"width": 1280, "height": 800},
                    )
                    page = await context.new_page()
                    await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    if wait_for:
                        try:
                            await page.wait_for_selector(wait_for, timeout=min(timeout_ms, 8000))
                        except Exception:
                            pass

                    if action == "read":
                        # innerText capture le texte rendu (apres JS), sans tags HTML.
                        text = await page.evaluate("() => document.body.innerText")
                        text = (text or "")[:8000]
                        title = await page.title()
                        return {
                            "content": f"Page : {title}\nURL : {page.url}\n\n{text}",
                            "is_error": False,
                            "raw": {"url": page.url, "title": title, "size": len(text)},
                        }
                    if action == "html":
                        html = await page.content()
                        html = (html or "")[:30000]
                        return {
                            "content": html,
                            "is_error": False,
                            "raw": {"url": page.url, "size": len(html)},
                        }
                    if action == "eval":
                        if not script:
                            return {"content": "Champ 'script' requis pour action='eval'.", "is_error": True, "raw": {}}
                        result = await page.evaluate(script)
                        return {
                            "content": str(result)[:8000],
                            "is_error": False,
                            "raw": {"url": page.url, "type": type(result).__name__},
                        }
                    if action == "screenshot":
                        full_page = bool(inp.get("full_page", False))
                        png_bytes = await page.screenshot(full_page=full_page, type="png")
                        # Sauvegarde sur disque pour servir au frontend
                        import uuid as _u
                        from pathlib import Path as _P
                        ws_base = _P(__file__).resolve().parent.parent / "data" / "sandbox_figures"
                        run_id = _u.uuid4().hex[:12]
                        out_dir = ws_base / run_id
                        out_dir.mkdir(parents=True, exist_ok=True)
                        out_path = out_dir / "screenshot.png"
                        out_path.write_bytes(png_bytes)
                        rel_url = f"/api/agent3/sandbox-figures/{run_id}/screenshot.png"
                        return {
                            "content": (
                                f"Screenshot capture : {len(png_bytes)} bytes PNG.\n"
                                f"URL : {rel_url}\n"
                                f"![Screenshot]({rel_url})"
                            ),
                            "is_error": False,
                            "raw": {
                                "url": page.url,
                                "size": len(png_bytes),
                                "image_url": rel_url,
                                "full_page": full_page,
                            },
                        }
                finally:
                    await browser.close()
        except Exception as e:
            return {
                "content": friendly_exception_message(e, fallback=f"Erreur browser sur {url}"),
                "is_error": True,
                "raw": {"url": url, "error": str(e)[:300]},
            }

    async def _memory_save(self, inp: dict) -> dict:
        if not self.user_id:
            return {
                "content": "Memoire indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }
        key = (inp.get("key") or "").strip()
        value = (inp.get("value") or "").strip()
        if not key or not value:
            return {
                "content": "Parametres 'key' et 'value' requis.",
                "is_error": True,
                "raw": {},
            }
        # Reuse du helper existant dans le router (version async).
        from api.routers.agent3_openclaw import _save_memory_async
        await _save_memory_async(self.user_id, key, value, "native")
        return {
            "content": f"Memorise : {key} = {value[:80]}{'...' if len(value) > 80 else ''}",
            "is_error": False,
            "raw": {"key": key},
        }

    async def _semantic_search(self, inp: dict) -> dict:
        """Recherche semantique top-k dans les docs deja ingeres (web, fichiers, memory)."""
        if not self.user_id:
            return {
                "content": "Recherche semantique indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' requis.", "is_error": True, "raw": {}}
        top_k = min(max(int(inp.get("top_k") or 5), 1), 20)
        scope = inp.get("scope")
        source_types = inp.get("source_types")
        if source_types and not isinstance(source_types, list):
            source_types = [source_types]

        try:
            from api.rag import semantic_search
            logger.info(
                f"[SEMANTIC_SEARCH] user={self.user_id} query={query!r} "
                f"top_k={top_k} scope={scope} source_types={source_types}"
            )
            results = await semantic_search(
                self.db, self.user_id, query,
                top_k=top_k, scope=scope, source_types=source_types,
            )
            logger.info(f"[SEMANTIC_SEARCH] -> {len(results)} hits")
        except Exception as e:
            logger.exception(f"semantic_search failed: {e}")
            return {
                "content": f"Erreur recherche semantique : {type(e).__name__}",
                "is_error": True, "raw": {"error": str(e)},
            }

        if not results:
            return {
                "content": f"Aucun resultat pour '{query}' dans la memoire semantique.",
                "is_error": False,
                "raw": {"query": query, "count": 0},
            }

        lines = [f"## {len(results)} resultats semantiques pour '{query}'\n"]
        for i, r in enumerate(results, 1):
            src = r["source_type"]
            ref = r["source_ref"] or ""
            lines.append(
                f"\n### [{i}] (score {r['score']:.2f}) — {src}"
                + (f" — `{ref[:80]}`" if ref else "")
            )
            lines.append(r["content"][:500])

        return {
            "content": "\n".join(lines),
            "is_error": False,
            "raw": {"query": query, "count": len(results), "results": results},
        }

    async def _python_exec(self, inp: dict) -> dict:
        """Execute du code Python dans un sandbox isole (matplotlib supporte)."""
        code = (inp.get("code") or "").strip()
        if not code:
            return {"content": "Parametre 'code' requis.", "is_error": True, "raw": {}}
        if len(code) > 50000:
            return {
                "content": f"Code trop long ({len(code)} chars, max 50000).",
                "is_error": True, "raw": {},
            }
        try:
            from api.python_sandbox import run_python_sandbox
            result = await run_python_sandbox(
                code, user_id=self.user_id, timeout_s=30.0,
            )
        except Exception as e:
            logger.exception(f"python_sandbox crashed: {e}")
            return {
                "content": f"Erreur sandbox : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

        # Format lisible pour le LLM
        lines = []
        if result["stdout"]:
            lines.append("### STDOUT\n```\n" + result["stdout"][:3000] + "\n```")
        if result["stderr"]:
            lines.append("### STDERR\n```\n" + result["stderr"][:1500] + "\n```")
        if result.get("figures"):
            lines.append(f"\n**{len(result['figures'])} figure(s) matplotlib generee(s)** : "
                         + ", ".join(result["figures"]))
        if result.get("error"):
            lines.append(f"\n**Erreur** : {result['error']}")
        if not lines:
            lines.append("(Aucun output)")

        return {
            "content": "\n".join(lines),
            "is_error": bool(result.get("exit_code", 0)) or bool(result.get("error")),
            "raw": result,
        }

    async def _vision_analyze(self, inp: dict) -> dict:
        """Analyse une image deja uploadee via Claude Vision."""
        if not self.user_id:
            return {
                "content": "Analyse vision indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        file_id = (inp.get("file_id") or "").strip()
        prompt = (inp.get("prompt") or "").strip()
        if not file_id:
            return {"content": "Parametre 'file_id' requis.", "is_error": True, "raw": {}}
        if not prompt:
            return {"content": "Parametre 'prompt' requis.", "is_error": True, "raw": {}}
        if len(prompt) > 2000:
            return {
                "content": f"Prompt trop long ({len(prompt)} chars, max 2000).",
                "is_error": True, "raw": {},
            }

        # Resoudre le path via agent3_files + verifier appartenance user (async).
        try:
            from sqlalchemy import text as _sa_text
            from api.database import get_session_factory as _gsf
            factory = _gsf()
            async with factory() as session:
                result = await session.execute(
                    _sa_text(
                        "SELECT filepath, filetype, filename FROM agent3_files "
                        "WHERE id = :fid AND auth_user_id = :uid"
                    ),
                    {"fid": file_id, "uid": self.user_id},
                )
                row = result.first()
        except Exception as e:
            return {
                "content": f"Erreur DB : {type(e).__name__}",
                "is_error": True, "raw": {"error": str(e)},
            }
        if not row:
            return {
                "content": f"Fichier {file_id} introuvable ou n'appartient pas a l'utilisateur.",
                "is_error": True, "raw": {},
            }
        filepath, filetype, filename = row[0], row[1], row[2]
        if not (filetype or "").startswith("image/"):
            return {
                "content": f"Le fichier {filename} n'est pas une image ({filetype}).",
                "is_error": True, "raw": {"filetype": filetype},
            }

        # Delegue a _analyze_image_with_vision (import lazy)
        try:
            from api.routers.agent3_openclaw import _analyze_image_with_vision
            description = await _analyze_image_with_vision(filepath, prompt)
        except Exception as e:
            logger.exception(f"vision_analyze crashed: {e}")
            return {
                "content": f"Erreur analyse vision : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

        if description and description.startswith("["):
            # Message d'erreur wrappe dans [...]
            return {
                "content": description,
                "is_error": True,
                "raw": {"file_id": file_id, "filename": filename},
            }

        return {
            "content": f"## Analyse de {filename}\n\n{description}",
            "is_error": False,
            "raw": {
                "file_id": file_id,
                "filename": filename,
                "prompt": prompt,
                "description_length": len(description or ""),
            },
        }

    async def _deep_research(self, inp: dict) -> dict:
        """Lance un sous-agent dedie recherche profonde multi-tours."""
        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' requis.", "is_error": True, "raw": {}}
        max_iterations = min(max(int(inp.get("max_iterations") or 10), 3), 25)
        budget_usd = min(max(float(inp.get("budget_usd") or 0.50), 0.10), 2.00)

        try:
            from api.deep_research import run_deep_research
            report = await run_deep_research(
                query=query,
                max_iterations=max_iterations,
                budget_usd=budget_usd,
                db=self.db,
                user_id=self.user_id,
                session_key=self.session_key,
            )
        except Exception as e:
            logger.exception(f"deep_research crashed: {e}")
            return {
                "content": f"Erreur deep research : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

        return {
            "content": report.get("markdown") or "(Rapport vide)",
            "is_error": False,
            "raw": {
                "query": query,
                "iterations_used": report.get("iterations_used"),
                "sources_consulted": report.get("sources_consulted", []),
                "cost_usd": report.get("cost_usd", 0.0),
            },
        }

    async def _memory_search(self, inp: dict) -> dict:
        if not self.user_id:
            return {
                "content": "Memoire indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }
        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' manquant.", "is_error": True, "raw": {}}
        if len(query) > _MAX_QUERY_LEN:
            return {
                "content": f"Query trop longue ({len(query)} chars, max {_MAX_QUERY_LEN}).",
                "is_error": True, "raw": {},
            }
        # Echappe les wildcards SQL LIKE pour eviter le pathological matching.
        def _escape_like(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        # Phase 14E : matching multi-token (OR sur chaque mot >= 3 chars).
        import re as _re
        tokens = [t for t in _re.split(r"[\s,;:./]+", query.lower()) if len(t) >= 3]
        _STOP = {"des", "les", "une", "mes", "tes", "ses", "tous", "tout",
                 "the", "and", "for", "with", "que", "qui", "quoi", "quel",
                 "quels", "quelles", "this", "that", "have", "from"}
        tokens = [t for t in tokens if t not in _STOP]
        if not tokens:
            tokens = [query.lower()]  # fallback : phrase entiere

        # SQLAlchemy text() avec parametres nommes (compat PG + SQLite).
        like_clauses = []
        params: dict = {"uid": self.user_id}
        for i, tok in enumerate(tokens[:8]):
            esc = _escape_like(tok)
            k_param = f"k{i}"
            v_param = f"v{i}"
            like_clauses.append(
                f"(key LIKE :{k_param} ESCAPE '\\' OR value LIKE :{v_param} ESCAPE '\\')"
            )
            params[k_param] = f"%{esc}%"
            params[v_param] = f"%{esc}%"
        sql = (
            "SELECT key, value, category, updated_at FROM agent3_memory "
            f"WHERE auth_user_id = :uid AND ({' OR '.join(like_clauses)}) "
            "ORDER BY updated_at DESC LIMIT 20"
        )
        from sqlalchemy import text as _sa_text
        from api.database import get_session_factory as _gsf
        factory = _gsf()
        try:
            async with factory() as session:
                result = await session.execute(_sa_text(sql), params)
                rows = result.all()
        except Exception:
            rows = []
        if not rows:
            return {
                "content": f"Aucun souvenir trouve pour '{query}'.",
                "is_error": False,
                "raw": {"query": query, "count": 0},
            }
        lines = [f"- {r[0]}: {r[1][:200]}" for r in rows]
        return {
            "content": f"{len(rows)} souvenirs trouves :\n" + "\n".join(lines),
            "is_error": False,
            "raw": {"query": query, "count": len(rows)},
        }

    def _pdf(self, inp: dict) -> dict:
        from api.agent3_primitives import _generate_pdf
        title = (inp.get("title") or "").strip()
        sections = inp.get("sections") or []
        color = inp.get("color") or "#2563eb"
        if not title:
            return {"content": "Parametre 'title' requis.", "is_error": True, "raw": {}}
        if not isinstance(sections, list) or not sections:
            return {
                "content": "Parametre 'sections' requis (liste non vide de {heading, content}).",
                "is_error": True,
                "raw": {},
            }
        try:
            filename = _generate_pdf(title=title, sections=sections, accent_color=color)
        except Exception as e:
            return {
                "content": f"Echec generation PDF : {type(e).__name__} {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }
        return {
            "content": f"PDF genere : {filename} (disponible via /api/agent3/pdf/{filename}).",
            "is_error": False,
            "raw": {"filename": filename, "url": f"/api/agent3/pdf/{filename}"},
        }

    def _code(self, inp: dict) -> dict:
        # Generation de code = pur passthrough (pas d'execution).
        content = inp.get("content") or ""
        language = inp.get("language") or "python"
        if not content.strip():
            return {"content": "Parametre 'content' vide.", "is_error": True, "raw": {}}
        # Le LLM n'a pas vraiment besoin du retour, mais on lui confirme.
        return {
            "content": f"Bloc de code {language} affiche ({len(content)} chars).",
            "is_error": False,
            "raw": {"language": language, "content": content},
        }

    def _canvas(self, inp: dict) -> dict:
        title = inp.get("title") or ""
        content = inp.get("content") or ""
        if not title or not content:
            return {
                "content": "Parametres 'title' et 'content' requis.",
                "is_error": True,
                "raw": {},
            }
        return {
            "content": f"Canvas '{title}' rendu ({len(content)} chars).",
            "is_error": False,
            "raw": {"title": title, "content": content},
        }

    def _file_read(self, inp: dict) -> dict:
        """Lit un fichier dans le workspace serveur uniquement (pas de desktop websocket
        ici — si besoin, route vers le handler legacy dans agent3_openclaw.py).

        Si le path direct ne resoud rien (le LLM passe souvent juste `notes.md`
        alors que le fichier est dans un sous-dossier), on tente un scan
        recursif limite et on retourne le 1er match exact.
        """
        from pathlib import Path as _P
        filename = (inp.get("filename") or inp.get("path") or "").strip()
        if not filename:
            return {"content": "Parametre 'filename' requis.", "is_error": True, "raw": {}}

        ws_base = _P(__file__).resolve().parent.parent / "data" / "workspace"
        try:
            # Path traversal robuste via relative_to (leve ValueError si echappement).
            resolved = ensure_within_base(ws_base / filename, ws_base)
            if resolved is None:
                return {
                    "content": f"Chemin hors workspace refuse : {filename}",
                    "is_error": True,
                    "raw": {"filename": filename},
                }
            # Phase 14H : si le path direct n'existe pas ET que filename est un
            # nom simple (pas de "/"), on tente un scan recursif dans le
            # workspace pour aider l'agent (qui passe souvent juste le basename
            # sans connaitre l'arborescence).
            if (not resolved.exists() or not resolved.is_file()) and "/" not in filename and "\\" not in filename:
                matches: list[_P] = []
                try:
                    # rglob pour recursive, limite a 100 resultats pour eviter d'exploser.
                    target_lower = filename.lower()
                    for cand in ws_base.rglob(filename):
                        if cand.is_file():
                            matches.append(cand)
                        if len(matches) >= 5:
                            break
                    # Match insensitive si rglob exact n'a rien donne
                    if not matches:
                        for cand in ws_base.rglob("*"):
                            if cand.is_file() and cand.name.lower() == target_lower:
                                matches.append(cand)
                                if len(matches) >= 5:
                                    break
                except Exception:
                    pass
                if len(matches) == 1:
                    resolved = matches[0]
                elif len(matches) > 1:
                    rels = [str(m.relative_to(ws_base)) for m in matches]
                    return {
                        "content": (
                            f"Plusieurs fichiers nommes '{filename}' trouves. "
                            f"Specifie le chemin parmi : {', '.join(rels)}"
                        ),
                        "is_error": True,
                        "raw": {"matches": rels},
                    }
            if not resolved.exists() or not resolved.is_file():
                return {
                    "content": f"Fichier introuvable : {filename}",
                    "is_error": True,
                    "raw": {"filename": filename},
                }
            content = resolved.read_text(encoding="utf-8", errors="replace")
            # Cap 32k pour preserver les tokens.
            truncated = content[:32000]
            return {
                "content": truncated,
                "is_error": False,
                "raw": {
                    "filename": filename,
                    "size": len(content),
                    "truncated": len(content) > 32000,
                },
            }
        except Exception as e:
            return {
                "content": f"Erreur lecture : {type(e).__name__} {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }

    async def _get_google_token(self, provider: str) -> str | None:
        """Fetch le token Google pour le user courant. Retourne None si indisponible.

        Le refresh effectif est declenche a la volee par _google_get() en cas de 401.
        """
        try:
            from api.agent3_primitives import _get_integration
            integ = _get_integration(self.db, self.user_id, provider)
        except Exception as e:
            logger.warning(f"_get_integration({provider}) failed: {e}")
            return None
        token = (integ or {}).get("access_token", "")
        if not token or len(token) < 20:
            return None
        return token

    # Retry policy pour les transients cote Google API (503/504/timeout).
    # Pas de retry sur 4xx (erreur client, pas transitoire) ni sur 401 (gere
    # par le refresh token). Backoff exponentiel : 1s, 2s, 4s.
    _GOOGLE_RETRY_STATUS: tuple[int, ...] = (502, 503, 504)
    _GOOGLE_MAX_RETRIES: int = 2

    async def _google_request(
        self,
        method: str,
        provider: str,
        url: str,
        *,
        timeout: float = 15.0,
        json_body: Any = None,
        content: bytes | None = None,
        extra_headers: dict | None = None,
    ) -> Any:
        """Appel Google API avec refresh auto sur 401 + retry sur transients.

        Retourne httpx.Response ou None (si integration absente / refresh echec).
        Retry automatique max 2 fois sur 502/503/504 et TimeoutException, avec
        backoff exponentiel (1s, 2s). Les 4xx (hors 401) ne sont pas retry.
        """
        import asyncio as _aio
        import httpx
        from api.agent3_http import get_http_client
        token = await self._get_google_token(provider)
        if not token:
            return None

        def _headers(t: str) -> dict:
            h = {"Authorization": f"Bearer {t}"}
            if extra_headers:
                h.update(extra_headers)
            return h

        client = get_http_client()
        attempt = 0
        while True:
            kwargs: dict[str, Any] = {
                "headers": _headers(token),
                "timeout": timeout,
            }
            if json_body is not None:
                kwargs["json"] = json_body
            if content is not None:
                kwargs["content"] = content
            try:
                r = await client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                if attempt >= self._GOOGLE_MAX_RETRIES:
                    raise
                backoff = 2 ** attempt  # 1, 2, 4
                logger.info(f"Google {provider} timeout, retry {attempt + 1} in {backoff}s")
                await _aio.sleep(backoff)
                attempt += 1
                continue

            # Refresh token sur 401, une seule fois (pas compte comme retry)
            if r.status_code == 401 and attempt == 0:
                try:
                    from api.agent3_primitives import _refresh_google_token
                    new_token = await _refresh_google_token(self.db, self.user_id, provider)
                except Exception as e:
                    logger.warning(f"refresh {provider} failed: {e}")
                    new_token = None
                if new_token:
                    token = new_token
                    attempt += 1  # consomme le slot pour eviter boucle infinie
                    continue

            # Retry sur 502/503/504
            if r.status_code in self._GOOGLE_RETRY_STATUS and attempt < self._GOOGLE_MAX_RETRIES:
                backoff = 2 ** attempt
                logger.info(
                    f"Google {provider} status {r.status_code}, retry {attempt + 1} in {backoff}s"
                )
                await _aio.sleep(backoff)
                attempt += 1
                continue

            return r

    async def _google_get(self, provider: str, url: str, *, timeout: float = 10.0) -> Any:
        return await self._google_request("GET", provider, url, timeout=timeout)

    async def _calendar_list(self, inp: dict) -> dict:
        if not self.user_id:
            return {
                "content": "Calendar indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }

        from datetime import datetime, timezone
        from urllib.parse import quote_plus as _q
        days = max(1, min(int(inp.get("days") or 7), 30))
        # Google Calendar API exige RFC3339 ISO 8601 avec timezone explicite.
        # Le `+` de `+00:00` doit etre URL-encoded (sinon interprete comme
        # espace) -> 400 Bad Request. On encode toute la query string.
        time_min = datetime.now(timezone.utc).isoformat()
        params = (
            f"timeMin={_q(time_min)}"
            f"&singleEvents=true&orderBy=startTime"
            f"&maxResults={min(days * 3, 20)}"
        )
        try:
            r = await self._google_get(
                "google_calendar",
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}",
            )
            if r is None:
                return {
                    "content": "Google Calendar non connecte. Configure l'integration avant.",
                    "is_error": True, "raw": {},
                }
            if r.status_code != 200:
                return {
                    "content": f"Calendar API {r.status_code} : {r.text[:200]}",
                    "is_error": True,
                    "raw": {"status": r.status_code},
                }
            items = r.json().get("items", [])
            events = [
                {
                    "title": e.get("summary", ""),
                    "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", ""),
                    "location": e.get("location", ""),
                }
                for e in items[:20]
            ]
            if not events:
                return {"content": "Aucun evenement a venir.", "is_error": False, "raw": {"events": []}}
            lines = [f"- {e['start']} — {e['title']}" + (f" ({e['location']})" if e['location'] else "") for e in events]
            return {
                "content": f"{len(events)} evenements :\n" + "\n".join(lines),
                "is_error": False,
                "raw": {"events": events},
            }
        except Exception as e:
            return {
                "content": f"Erreur Calendar : {type(e).__name__} {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }

    async def _gmail_read(self, inp: dict) -> dict:
        if not self.user_id:
            return {
                "content": "Gmail indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }

        import asyncio as _aio
        from urllib.parse import quote_plus
        query = (inp.get("query") or "is:unread").strip()
        if len(query) > _MAX_QUERY_LEN:
            return {
                "content": f"Query Gmail trop longue (> {_MAX_QUERY_LEN} chars).",
                "is_error": True, "raw": {},
            }
        limit = min(max(int(inp.get("limit") or 10), 1), 20)
        try:
            r = await self._google_get(
                "gmail",
                f"https://www.googleapis.com/gmail/v1/users/me/messages"
                f"?q={quote_plus(query)}&maxResults={limit}",
            )
            if r is None:
                return {
                    "content": "Gmail non connecte. Configure l'integration avant.",
                    "is_error": True, "raw": {},
                }
            if r.status_code != 200:
                return {
                    "content": f"Gmail API {r.status_code}",
                    "is_error": True,
                    "raw": {"status": r.status_code},
                }
            msg_ids = [m["id"] for m in r.json().get("messages", [])[:limit]]
            if not msg_ids:
                return {"content": f"Aucun email pour '{query}'.", "is_error": False, "raw": {"emails": []}}

            # Fetch parallele (corrige N+1) via asyncio.gather.
            detail_url = (
                "https://www.googleapis.com/gmail/v1/users/me/messages/{mid}"
                "?format=metadata&metadataHeaders=Subject"
                "&metadataHeaders=From&metadataHeaders=Date"
            )
            detail_coros = [
                self._google_get("gmail", detail_url.format(mid=mid)) for mid in msg_ids
            ]
            details = await _aio.gather(*detail_coros, return_exceptions=True)

            emails: list[dict] = []
            for d in details:
                if isinstance(d, Exception) or d is None or d.status_code != 200:
                    continue
                payload = d.json()
                headers_map = {
                    h["name"]: h["value"]
                    for h in payload.get("payload", {}).get("headers", [])
                }
                emails.append({
                    "subject": headers_map.get("Subject", ""),
                    "from": headers_map.get("From", ""),
                    "date": headers_map.get("Date", ""),
                    "snippet": payload.get("snippet", "")[:200],
                })
            if not emails:
                return {"content": f"Aucun email lisible pour '{query}'.", "is_error": False, "raw": {"emails": []}}
            lines = [f"- [{e['date'][:16]}] {e['from']} — {e['subject']}" for e in emails]
            return {
                "content": f"{len(emails)} emails :\n" + "\n".join(lines),
                "is_error": False,
                "raw": {"emails": emails},
            }
        except Exception as e:
            return {
                "content": f"Erreur Gmail : {type(e).__name__} {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }

    # ── Destructives (passent par le gate de confirmation de AgenticLoop) ──

    async def _file_create(self, inp: dict) -> dict:
        """Cree un fichier dans le workspace utilisateur."""
        from pathlib import Path
        filename = (inp.get("filename") or "").strip()
        content = inp.get("content") or ""
        if not filename:
            return {"content": "Parametre 'filename' manquant.", "is_error": True, "raw": {}}
        if not content:
            return {"content": "Parametre 'content' vide.", "is_error": True, "raw": {}}
        try:
            if self.user_id:
                from api.agent3_primitives import (
                    get_workspace_folder_name, WORKSPACE_BASE,
                )
                obj_name = await get_workspace_folder_name_async(self.user_id)
                project_dir = WORKSPACE_BASE / obj_name
                project_dir.mkdir(parents=True, exist_ok=True)
                safe_name = Path(filename).name or "fichier.txt"
                filepath = project_dir / safe_name
                counter = 1
                while filepath.exists():
                    stem = Path(safe_name).stem
                    suffix = Path(safe_name).suffix or ".txt"
                    filepath = project_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
                filepath.write_text(content, encoding="utf-8")
                size = len(content.encode("utf-8"))
                return {
                    "content": f"Fichier '{filepath.name}' cree dans le workspace ({size} octets).",
                    "is_error": False,
                    "raw": {
                        "workspace_path": f"{obj_name}/{filepath.name}",
                        "full_path": str(filepath),
                        "size": size,
                        "saved": True,
                    },
                }
            # Fallback anonyme -> fichier temporaire telechargeable
            from api.agent3_primitives import _save_file_create_fallback
            fb = _save_file_create_fallback(filename, content)
            return {
                "content": f"Fichier '{fb['stored_filename']}' pret ({fb['size']} octets). "
                           f"Telechargeable : {fb['download_url']}",
                "is_error": False,
                "raw": {"fallback": True, **fb},
            }
        except Exception as e:
            logger.exception(f"FILE_CREATE failed: {e}")
            return {
                "content": f"Erreur ecriture fichier : {type(e).__name__} {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }

    async def _email(self, inp: dict) -> dict:
        """Envoie un email via SMTP (fallback Gmail API si OAuth dispo)."""
        to = (inp.get("to") or "").strip()
        subject = (inp.get("subject") or "").strip()
        body = inp.get("body") or ""
        html_flag = bool(inp.get("html", False))
        if not to or not subject or not body:
            return {
                "content": "Champs requis : 'to', 'subject', 'body'.",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "Envoi email indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        # Tentative SMTP
        try:
            from api.agent3_primitives import _send_email_smtp
            res = _send_email_smtp(self.db, self.user_id, to, subject, body, html=html_flag)
            if res.get("ok"):
                return {
                    "content": f"Email envoye a {to} via SMTP.",
                    "is_error": False,
                    "raw": {"method": "smtp", "to": to, **res},
                }
            smtp_err = res.get("error", "SMTP non configure")
        except Exception as e:
            smtp_err = f"{type(e).__name__}: {e}"

        # Fallback Gmail API (avec refresh auto)
        try:
            import base64
            from email.mime.text import MIMEText
            mime = MIMEText(body, "html" if html_flag else "plain", "utf-8")
            mime["To"] = to
            mime["Subject"] = subject
            raw_b = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
            r = await self._google_request(
                "POST", "gmail",
                "https://www.googleapis.com/gmail/v1/users/me/messages/send",
                json_body={"raw": raw_b},
            )
            if r is None:
                return {
                    "content": f"Email non envoye. SMTP indisponible ({smtp_err}) et Gmail non connecte.",
                    "is_error": True,
                    "raw": {"smtp_error": smtp_err},
                }
            if r.status_code == 200:
                return {
                    "content": f"Email envoye a {to} via Gmail API.",
                    "is_error": False,
                    "raw": {"method": "gmail_api", "to": to, "status": r.status_code},
                }
            return {
                "content": f"Gmail API erreur {r.status_code}. SMTP : {smtp_err}",
                "is_error": True,
                "raw": {"method": "gmail_api", "status": r.status_code, "smtp_error": smtp_err},
            }
        except Exception as e:
            return {
                "content": f"Email non envoye. SMTP : {smtp_err}. Gmail : {type(e).__name__} {e}.",
                "is_error": True,
                "raw": {"smtp_error": smtp_err, "gmail_error": str(e)},
            }

    async def _gmail_send(self, inp: dict) -> dict:
        """Envoie un email via Gmail API (OAuth)."""
        to = (inp.get("to") or "").strip()
        subject = (inp.get("subject") or "").strip()
        body = inp.get("body") or ""
        if not to or not subject or not body:
            return {
                "content": "Champs requis : 'to', 'subject', 'body'.",
                "is_error": True, "raw": {},
            }
        if len(body) > _MAX_BODY_CHARS:
            return {
                "content": f"Body trop long (> {_MAX_BODY_CHARS} chars).",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "GMAIL_SEND indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        try:
            import base64
            from email.mime.text import MIMEText
            mime = MIMEText(body, "plain", "utf-8")
            mime["To"] = to
            mime["Subject"] = subject
            raw_b = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
            r = await self._google_request(
                "POST", "gmail",
                "https://www.googleapis.com/gmail/v1/users/me/messages/send",
                json_body={"raw": raw_b},
            )
            if r is None:
                return {
                    "content": "Gmail non connecte. Connecte-toi via Integrations.",
                    "is_error": True, "raw": {},
                }
            if r.status_code == 200:
                return {
                    "content": f"Email envoye a {to} via Gmail.",
                    "is_error": False,
                    "raw": {"to": to, "status": 200},
                }
            return {
                "content": f"Gmail API erreur {r.status_code} : {r.text[:200]}",
                "is_error": True,
                "raw": {"status": r.status_code, "body": r.text[:500]},
            }
        except Exception as e:
            return {
                "content": f"Erreur Gmail : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _calendar_event(self, inp: dict) -> dict:
        """Cree un evenement Google Calendar."""
        title = (inp.get("title") or "").strip()
        start = (inp.get("start") or "").strip()
        end = (inp.get("end") or "").strip()
        description = inp.get("description") or ""
        if not title or not start or not end:
            return {
                "content": "Champs requis : 'title', 'start', 'end' (ISO 8601).",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "CALENDAR_EVENT indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        try:
            body = {
                "summary": title,
                "start": {"dateTime": start, "timeZone": "Europe/Paris"},
                "end": {"dateTime": end, "timeZone": "Europe/Paris"},
                "description": description,
            }
            r = await self._google_request(
                "POST", "google_calendar",
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                json_body=body,
            )
            if r is None:
                return {
                    "content": "Google Calendar non connecte. Connecte-toi via Integrations.",
                    "is_error": True, "raw": {},
                }
            if r.status_code in (200, 201):
                link = r.json().get("htmlLink", "")
                return {
                    "content": f"Evenement '{title}' cree dans Google Calendar. Lien : {link}",
                    "is_error": False,
                    "raw": {"created": True, "event_link": link, "start": start, "end": end},
                }
            return {
                "content": f"Calendar API erreur {r.status_code} : {r.text[:200]}",
                "is_error": True,
                "raw": {"status": r.status_code, "body": r.text[:500]},
            }
        except Exception as e:
            return {
                "content": f"Erreur Calendar : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _drive_save(self, inp: dict) -> dict:
        """Sauvegarde un fichier dans Google Drive."""
        filename = (inp.get("filename") or "document.txt").strip()
        content = inp.get("content") or ""
        if not content:
            return {"content": "Parametre 'content' vide.", "is_error": True, "raw": {}}
        if len(content) > _MAX_BODY_CHARS:
            return {
                "content": f"Content trop long (> {_MAX_BODY_CHARS} chars).",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "DRIVE_SAVE indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        try:
            import json as _json
            boundary = "sylea_boundary"
            multipart_body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                + _json.dumps({"name": filename})
                + f"\r\n--{boundary}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"
                + content
                + f"\r\n--{boundary}--"
            )
            r = await self._google_request(
                "POST", "google_drive",
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                content=multipart_body.encode("utf-8"),
                extra_headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                timeout=20.0,
            )
            if r is None:
                return {
                    "content": "Google Drive non connecte. Connecte-toi via Integrations.",
                    "is_error": True, "raw": {},
                }
            if r.status_code in (200, 201):
                file_id = r.json().get("id", "")
                return {
                    "content": f"Fichier '{filename}' sauvegarde dans Google Drive (id={file_id}).",
                    "is_error": False,
                    "raw": {"saved": True, "file_id": file_id, "filename": filename},
                }
            return {
                "content": f"Drive API erreur {r.status_code} : {r.text[:200]}",
                "is_error": True,
                "raw": {"status": r.status_code, "body": r.text[:500]},
            }
        except Exception as e:
            return {
                "content": f"Erreur Drive : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    def _get_fresh_db(self):
        """Ouvre une connexion DB fraiche pour les ecritures critiques.

        Necessaire car le `self.db` peut etre la connexion request-scoped qui a
        ete fermee par get_db.finally avant qu'une action suspendue ne reprenne
        (flow chat/native -> awaiting_confirmation -> chat/native/resume).
        """
        from sylea.core.storage.database import DatabaseManager
        d = DatabaseManager()
        d.connect()
        return d

    async def _cron(self, inp: dict) -> dict:
        """Programme une tache recurrente dans la table agent3_cron (version async).

        Delegue a `_cron_async` plus bas (qui partage le pool async PG/SQLite).
        """
        return await self._cron_async(inp)

    async def _reminder(self, inp: dict) -> dict:
        """Programme un rappel ponctuel (one-shot) dans la table agent_reminders.

        Inputs (au moins UN parmi les 2 modes) :
          - Mode delta : `delay_minutes` (int) — ex 120 pour "dans 2h"
          - Mode absolu : `reminder_date` (YYYY-MM-DD) + `reminder_time` (HH:MM)
        Toujours requis : `message` (le texte du rappel).
        """
        from datetime import datetime, timedelta, timezone
        message = (inp.get("message") or inp.get("text") or "").strip()
        if not message:
            return {
                "content": "Champ 'message' requis : que dois-je te rappeler ?",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "REMINDER indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }

        # Calcul de la date+heure cible
        delay_minutes = inp.get("delay_minutes")
        rdate = (inp.get("reminder_date") or "").strip()
        rtime = (inp.get("reminder_time") or "").strip()

        if delay_minutes is not None:
            try:
                delay = int(delay_minutes)
            except (ValueError, TypeError):
                return {
                    "content": "delay_minutes doit etre un entier (minutes)",
                    "is_error": True, "raw": {},
                }
            target = datetime.now(timezone.utc) + timedelta(minutes=delay)
            # Stocke en local (le scheduler matchera sur date+heure locales)
            target_local = target.astimezone()
            rdate = target_local.strftime("%Y-%m-%d")
            rtime = target_local.strftime("%H:%M")
        elif not (rdate and rtime):
            return {
                "content": "Fournis soit `delay_minutes` (ex 120 pour 2h) soit `reminder_date`+`reminder_time`.",
                "is_error": True, "raw": {},
            }

        # Async DB via SQLAlchemy text() — compat SQLite + PostgreSQL.
        from sqlalchemy import text as _sa_text
        from api.database import get_session_factory as _gsf
        factory = _gsf()
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with factory() as session:
                try:
                    # DDL idempotent (sera no-op si table existe deja).
                    await session.execute(_sa_text(
                        "CREATE TABLE IF NOT EXISTS agent_reminders ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, "
                        "agent_id TEXT DEFAULT 'agent3', reminder_time TEXT NOT NULL, "
                        "reminder_date TEXT NOT NULL, message TEXT NOT NULL, "
                        "completed INTEGER DEFAULT 0, created_at TEXT NOT NULL)"
                    ))
                    result = await session.execute(
                        _sa_text(
                            "INSERT INTO agent_reminders "
                            "(user_id, agent_id, reminder_time, reminder_date, "
                            " message, completed, created_at) "
                            "VALUES (:uid, 'agent3', :rtime, :rdate, :msg, 0, :now)"
                        ),
                        {
                            "uid": self.user_id, "rtime": rtime, "rdate": rdate,
                            "msg": message, "now": now_iso,
                        },
                    )
                    await session.commit()
                    reminder_id = getattr(result, "lastrowid", None) or 0
                except Exception:
                    await session.rollback()
                    raise
            return {
                "content": f"Rappel programme pour {rdate} a {rtime} : \"{message[:80]}\"",
                "is_error": False,
                "raw": {
                    "reminder_id": reminder_id,
                    "reminder_date": rdate,
                    "reminder_time": rtime,
                    "message": message[:200],
                },
            }
        except Exception as e:
            logger.exception(f"REMINDER insert failed: {e}")
            return {
                "content": f"Erreur programmation rappel : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _computer_use(self, inp: dict) -> dict:
        """Delegue une tache au moteur Anthropic Computer Use (navigation autonome).

        Consomme l'async-generator ComputerUseSession.run() jusqu'a completion
        et retourne un resume consolide. Les etapes intermediaires sont perdues
        pour le LLM (pas de streaming vers lui), mais le frontend reste a jour
        via l'event `tool_result.raw` (steps, cost). Cette action est destructive
        ET couteuse : elle n'est exécutée qu'après confirmation utilisateur via
        l'AgenticLoop.
        """
        import os
        prompt = (inp.get("prompt") or inp.get("task") or "").strip()
        if not prompt:
            return {
                "content": "Champ 'prompt' requis : décris la tâche à accomplir via Computer Use.",
                "is_error": True, "raw": {},
            }
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {
                "content": "Computer Use indisponible : ANTHROPIC_API_KEY non configurée.",
                "is_error": True, "raw": {},
            }
        try:
            from api.computer_use import get_session
            import asyncio as _aio
            session = get_session(self.user_id or "default", api_key)
            steps = 0
            final_text = ""
            cost_usd = 0.0
            last_action = ""
            error_msg = ""

            async def _consume():
                nonlocal steps, final_text, cost_usd, last_action, error_msg
                async for event in session.run(prompt):
                    etype = event.get("type", "")
                    if etype == "step":
                        steps = event.get("current", steps)
                    elif etype == "action":
                        last_action = event.get("action", "?")
                    elif etype == "cost_update":
                        cost_usd = event.get("estimated_usd", cost_usd)
                    elif etype == "complete":
                        final_text = event.get("text", "") or final_text
                    elif etype == "error":
                        error_msg = event.get("message", "") or error_msg

            try:
                await _aio.wait_for(_consume(), timeout=_COMPUTER_USE_TIMEOUT_S)
            except _aio.TimeoutError:
                return {
                    "content": (
                        f"Computer Use interrompu : timeout apres "
                        f"{_COMPUTER_USE_TIMEOUT_S}s. Decoupe la tache en etapes plus courtes."
                    ),
                    "is_error": True,
                    "raw": {
                        "timeout": True,
                        "steps": steps,
                        "cost_usd": round(cost_usd, 4),
                        "last_action": last_action,
                    },
                }

            if error_msg and not final_text:
                return {
                    "content": f"Computer Use a échoué : {error_msg[:500]}",
                    "is_error": True,
                    "raw": {"steps": steps, "cost_usd": round(cost_usd, 4), "last_action": last_action},
                }
            summary = final_text or f"Computer Use terminé en {steps} étape(s) sans texte de sortie."
            return {
                "content": summary[:4000],
                "is_error": False,
                "raw": {
                    "steps": steps,
                    "cost_usd": round(cost_usd, 4),
                    "last_action": last_action,
                    "full_text_len": len(final_text),
                },
            }
        except Exception as e:
            logger.exception(f"COMPUTER_USE crashed: {e}")
            return {
                "content": f"Erreur Computer Use : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _openclaw_session(self, inp: dict) -> dict:
        """Spawne un sous-agent ClawHub avec acces COMPLET aux outils OpenClaw
        (read+write+exec) pour explorer un projet ou executer une tache complexe.

        Inputs :
          - prompt (str, requis) : description de la mission
          - max_turns (int, opt) : 1-15, defaut 8

        Le sous-agent dispose de :
          - SEARCH, WEB_FETCH, BROWSER, FILE_READ
          - PYTHON_EXEC (sandbox), CODE, PDF, CANVAS
          - MEMORY*, CALENDAR_LIST, GMAIL_READ
          - Plus tous les tools OpenClaw via clawhub si CLAWHUB_SEARCH/INSTALL/CALL.

        Note securite : pas d'actions destructives sur le compte parent (FILE_CREATE,
        EMAIL, GMAIL_SEND etc. sont exclus pour eviter les abus en cascade).
        """
        import os
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {
                "content": "OPENCLAW_SESSION indisponible : ANTHROPIC_API_KEY non configuree.",
                "is_error": True, "raw": {},
            }
        prompt = (inp.get("prompt") or inp.get("task") or inp.get("description") or "").strip()
        if not prompt:
            return {
                "content": "Champ 'prompt' requis : decris la mission de la session OpenClaw.",
                "is_error": True, "raw": {},
            }
        max_turns = min(max(int(inp.get("max_turns") or 8), 1), 15)

        try:
            from anthropic import AsyncAnthropic
            from api.agent3_native_tools import AgenticLoop, build_tool_schemas

            # Toolbox elargie : on garde tout le read-only + recherche/exec mais on
            # exclut les actions destructives sur les ressources externes (email,
            # calendar event, drive_save) pour respecter le perimetre "exploration".
            session_actions = {
                "SEARCH", "X_SEARCH", "WEB_FETCH", "BROWSER", "SCREENSHOT",
                "MEMORY", "MEMORY_SEARCH", "SEMANTIC_SEARCH",
                "PYTHON_EXEC", "DEEP_RESEARCH",
                "FILE_READ", "CALENDAR_LIST", "GMAIL_READ",
                "PDF", "CODE", "CANVAS", "VISION_ANALYZE",
                "CLAWHUB_SEARCH", "CLAWHUB_INSTALL",  # exploration meta-tools
            }
            session_tools = build_tool_schemas(enabled_actions=session_actions)
            session_executor = Agent3ActionDispatcher(
                db=self.db, user_id=self.user_id, session_key=self.session_key,
            )
            session_client = AsyncAnthropic(api_key=api_key)
            session_system = (
                "Tu es une session OpenClaw autonome de SYLEA. Tu disposes de "
                "tous les outils OpenClaw d'exploration (recherche, web, browser, "
                "screenshot, file read, calendar, gmail read, sandbox Python, "
                "ClawHub, deep research, vision).\n"
                f"Mission : {prompt}\n"
                "Etapes : explore, analyse, synthetise. Produis un rapport final "
                "structure (sections claires, faits sources, prochaines etapes "
                "actionables). Pas de meta-commentaire."
            )
            session_loop = AgenticLoop(
                client=session_client,
                system_prompt=session_system,
                tools=session_tools,
                executor=session_executor,
                model="claude-sonnet-4-6",  # Sonnet pour exploration plus complexe que SPAWN_AGENT
                max_turns=max_turns,
                max_tokens=3000,
                input_usd_per_mtok=3.0,
                output_usd_per_mtok=15.0,
                cache_tools=True,
            )

            turns_used = 0
            actions_ran: list[str] = []
            async for event in session_loop.run(prompt):
                if event.type == "turn_start":
                    turns_used = event.data.get("turn", turns_used)
                elif event.type == "tool_use":
                    actions_ran.append(event.data.get("action_type", "?"))

            final_text = ""
            if session_loop.result and session_loop.result.final_text:
                final_text = session_loop.result.final_text
            if not final_text:
                final_text = "(Session OpenClaw terminee sans rapport textuel.)"

            return {
                "content": final_text[:6000],
                "is_error": False,
                "raw": {
                    "session_type": "openclaw_full_tools",
                    "prompt": prompt[:200],
                    "turns_used": turns_used,
                    "actions_ran": actions_ran,
                    "tools_enabled": len(session_actions),
                    "session_cost_usd": round(
                        (session_loop.result.total_input_tokens if session_loop.result else 0) * 3.0 / 1_000_000.0
                        + (session_loop.result.total_output_tokens if session_loop.result else 0) * 15.0 / 1_000_000.0,
                        4,
                    ),
                },
            }
        except Exception as e:
            logger.exception(f"OPENCLAW_SESSION crashed: {e}")
            return {
                "content": f"Erreur session OpenClaw : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _spawn_agent(self, inp: dict) -> dict:
        """Delegue une sous-tache (ou plusieurs en parallele) a des AgenticLoop enfants.

        Deux modes :
          1) Single (backward-compat) : {description, task, max_turns?}
             -> execute une sous-tache.
          2) Parallel : {tasks: [{description, task, max_turns?}, ...]}
             -> execute toutes les taches EN PARALLELE via asyncio.gather,
                agrege les resultats dans un seul tool_result (ROI x N sans
                multiplier la latence totale).

        Perimetre enfant (inchange) : lecture seule + generation locale.
        Pas de SPAWN_AGENT ni d'actions destructives (anti-recursion, secu).
        """
        import os
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {
                "content": "SPAWN_AGENT indisponible : ANTHROPIC_API_KEY non configuree.",
                "is_error": True, "raw": {},
            }

        tasks_list = inp.get("tasks")
        if isinstance(tasks_list, list) and tasks_list:
            # Mode parallele
            return await self._spawn_agents_parallel(tasks_list, api_key)

        # Mode single (compat)
        description = (inp.get("description") or "").strip()
        task = (inp.get("task") or "").strip()
        max_turns = min(max(int(inp.get("max_turns") or 5), 1), 10)
        if not description or not task:
            return {
                "content": "Champs 'description' et 'task' requis pour SPAWN_AGENT.",
                "is_error": True, "raw": {},
            }
        res = await self._spawn_single_agent(description, task, max_turns, api_key)
        return res

    async def _spawn_single_agent(
        self, description: str, task: str, max_turns: int, api_key: str,
    ) -> dict:
        """Execute un seul sous-agent et retourne son resultat au format tool_result."""
        try:
            from anthropic import AsyncAnthropic
            from api.agent3_native_tools import AgenticLoop, build_tool_schemas

            child_actions = {
                "SEARCH", "X_SEARCH", "WEB_FETCH",
                "MEMORY", "MEMORY_SEARCH",
                "FILE_READ", "CALENDAR_LIST", "GMAIL_READ",
                "PDF", "CODE", "CANVAS",
            }
            child_tools = build_tool_schemas(enabled_actions=child_actions)
            child_executor = Agent3ActionDispatcher(
                db=self.db, user_id=self.user_id, session_key=self.session_key,
            )
            child_client = AsyncAnthropic(api_key=api_key)
            child_system = (
                f"Tu es un sous-agent autonome de SYLEA, specialise : '{description}'.\n"
                "Tu as acces a des outils de lecture (recherche web, memoire, lecture "
                "fichiers, lecture calendrier/email). Tu n'as PAS acces aux actions "
                "destructives. Tu ne peux PAS spawn d'autres agents.\n"
                "Ta mission : accomplir la tache decrite, puis produire un RESUME "
                "textuel synthetique (3-10 phrases max) que l'agent parent utilisera "
                "directement. Sois precis, factuel, actionnable. Pas de meta-commentaire."
            )
            # Sous-agent : Haiku 4.5 par defaut (3x moins cher que Sonnet, et
            # les taches de sous-agent sont par nature simples/ciblees).
            child_loop = AgenticLoop(
                client=child_client,
                system_prompt=child_system,
                tools=child_tools,
                executor=child_executor,
                model="claude-haiku-4-5-20251001",
                max_turns=max_turns,
                max_tokens=2048,
                input_usd_per_mtok=1.0,
                output_usd_per_mtok=5.0,
                cache_tools=True,
            )

            turns_used = 0
            actions_ran: list[str] = []
            async for event in child_loop.run(task):
                if event.type == "turn_start":
                    turns_used = event.data.get("turn", turns_used)
                elif event.type == "tool_use":
                    actions_ran.append(event.data.get("action_type", "?"))

            final_text = ""
            if child_loop.result and child_loop.result.final_text:
                final_text = child_loop.result.final_text
            if not final_text:
                final_text = "(Sous-agent termine sans reponse textuelle finale.)"

            return {
                "content": final_text[:4000],
                "is_error": False,
                "raw": {
                    "description": description,
                    "turns_used": turns_used,
                    "actions_ran": actions_ran,
                    "final_text_len": len(final_text),
                    "child_cost_usd": round(
                        (child_loop.result.total_input_tokens if child_loop.result else 0) * 1.0 / 1_000_000.0
                        + (child_loop.result.total_output_tokens if child_loop.result else 0) * 5.0 / 1_000_000.0,
                        4,
                    ),
                },
            }
        except Exception as e:
            logger.exception(f"SPAWN_AGENT (single) crashed: {e}")
            return {
                "content": f"Erreur sous-agent : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e), "description": description},
            }

    async def _spawn_agents_parallel(
        self, tasks_list: list[dict], api_key: str,
    ) -> dict:
        """Lance plusieurs sous-agents en parallele via asyncio.gather.

        Gain : N sous-agents s'executent en wall-clock-max(sous_agents) au lieu
        de somme(sous_agents). Couts identiques (on paie les meme tokens) mais
        latence divisee par N.
        """
        import asyncio
        coros = []
        descriptions: list[str] = []
        for item in tasks_list[:8]:  # cap a 8 pour ne pas exploser l'API rate-limit
            if not isinstance(item, dict):
                continue
            desc = (item.get("description") or "").strip()
            task = (item.get("task") or "").strip()
            mt = min(max(int(item.get("max_turns") or 5), 1), 10)
            if not desc or not task:
                continue
            descriptions.append(desc)
            coros.append(self._spawn_single_agent(desc, task, mt, api_key))

        if not coros:
            return {
                "content": "Aucune tache valide dans 'tasks' (chaque item doit avoir description + task).",
                "is_error": True, "raw": {},
            }

        results = await asyncio.gather(*coros, return_exceptions=True)

        # Agreger en un seul tool_result textuel structure.
        parts: list[str] = []
        total_cost = 0.0
        errors = 0
        for desc, res in zip(descriptions, results):
            if isinstance(res, Exception):
                parts.append(f"### {desc}\n[ERREUR] {type(res).__name__}: {res}")
                errors += 1
                continue
            if res.get("is_error"):
                parts.append(f"### {desc}\n[ERREUR] {res.get('content', '?')}")
                errors += 1
            else:
                parts.append(f"### {desc}\n{res.get('content', '')}")
                total_cost += float(res.get("raw", {}).get("child_cost_usd", 0.0) or 0.0)

        aggregated = "\n\n".join(parts)
        return {
            "content": aggregated[:8000],
            "is_error": errors == len(results),  # erreur seulement si TOUS echouent
            "raw": {
                "parallel": True,
                "count": len(results),
                "errors": errors,
                "total_child_cost_usd": round(total_cost, 4),
                "descriptions": descriptions,
            },
        }

    async def _image_gen(self, inp: dict) -> dict:
        """Generation d'image via OpenAI DALL-E 3 (utilise OPENAI_API_KEY).

        Bypass volontaire d'OpenClaw Gateway (qui peut router via skills tierces
        type ai-image necessitant SKILLS_VIDEO_API_KEY non configuree).

        Inputs :
          - prompt (str, requis) : description de l'image a generer
          - size (str, opt) : "1024x1024" (default), "1792x1024", "1024x1792"
          - quality (str, opt) : "standard" (default, ~$0.04) ou "hd" (~$0.08)

        Retourne le filename (servi via /api/agent3/image/<filename>) + cost_usd.
        """
        import os, base64, hashlib
        from datetime import datetime
        from pathlib import Path
        from api.routers.agent3_openclaw import IMAGE_DIR

        prompt = (inp.get("prompt") or "").strip()
        size = (inp.get("size") or "1024x1024").strip()
        quality = (inp.get("quality") or "standard").strip()
        if not prompt:
            return {
                "content": "Champ 'prompt' requis pour IMAGE_GEN.",
                "is_error": True, "raw": {},
            }
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            return {
                "content": "OPENAI_API_KEY non configuree — generation d'image indisponible.",
                "is_error": True, "raw": {},
            }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    json={
                        "model": "dall-e-3",
                        "prompt": prompt,
                        "n": 1,
                        "size": size,
                        "quality": quality,
                        "response_format": "b64_json",
                    },
                )
            if resp.status_code != 200:
                return {
                    "content": f"DALL-E erreur {resp.status_code} : {resp.text[:200]}",
                    "is_error": True, "raw": {"status": resp.status_code},
                }
            data = resp.json()
            b64 = data.get("data", [{}])[0].get("b64_json", "")
            if not b64:
                return {
                    "content": "DALL-E n'a pas retourne d'image (b64_json vide).",
                    "is_error": True, "raw": data,
                }
            img_bytes = base64.b64decode(b64)
            image_id = hashlib.md5(f"{prompt}-{datetime.now().isoformat()}".encode()).hexdigest()[:16]
            filename = f"{image_id}.png"
            filepath = IMAGE_DIR / filename
            filepath.write_bytes(img_bytes)
            cost_usd = 0.04 if quality == "standard" else 0.08
            return {
                "content": f"Image generee : {filename} ({len(img_bytes)} octets, cout ~{cost_usd}$).",
                "is_error": False,
                "raw": {
                    "filename": filename,
                    "image_url": f"/api/agent3/image/{filename}",
                    "size": size, "quality": quality,
                    "cost_usd": cost_usd,
                    "model": "dall-e-3",
                    "prompt": prompt[:200],
                },
            }
        except Exception as e:
            logger.exception(f"IMAGE_GEN crashed: {e}")
            return {
                "content": f"Erreur generation image : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _tts_gen(self, inp: dict) -> dict:
        """Synthese vocale via OpenAI TTS (utilise OPENAI_API_KEY).

        Inputs :
          - text (str, requis) : texte a vocaliser (max 4096 chars OpenAI)
          - voice (str, opt) : nova (default), alloy, echo, fable, onyx, shimmer
          - speed (float, opt) : 0.25 - 4.0 (default 1.0)

        Retourne le filename audio (servi via /api/agent3/audio/<filename>) + cost_usd.
        """
        import os, hashlib
        from datetime import datetime
        from pathlib import Path
        text = (inp.get("text") or inp.get("input") or "").strip()
        voice = (inp.get("voice") or "nova").strip().lower()
        speed = float(inp.get("speed") or 1.0)
        if not text:
            return {
                "content": "Champ 'text' requis pour TTS_GEN.",
                "is_error": True, "raw": {},
            }
        if voice not in ("nova", "alloy", "echo", "fable", "onyx", "shimmer"):
            voice = "nova"
        text = text[:4096]
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            return {
                "content": "OPENAI_API_KEY non configuree — TTS indisponible.",
                "is_error": True, "raw": {},
            }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={"model": "tts-1", "input": text, "voice": voice, "response_format": "mp3", "speed": speed},
                )
            if resp.status_code != 200:
                return {
                    "content": f"OpenAI TTS erreur {resp.status_code} : {resp.text[:200]}",
                    "is_error": True, "raw": {"status": resp.status_code},
                }
            audio_bytes = resp.content
            audio_id = hashlib.md5(f"{text[:50]}-{datetime.now().isoformat()}".encode()).hexdigest()[:16]
            filename = f"{audio_id}.mp3"
            audio_dir = Path(__file__).resolve().parent.parent / "data" / "agent3_audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            filepath = audio_dir / filename
            filepath.write_bytes(audio_bytes)
            # OpenAI TTS : $15 / 1M chars
            cost_usd = round(len(text) * 15.0 / 1_000_000.0, 6)
            return {
                "content": f"Audio genere : {filename} ({len(audio_bytes)} octets, voix {voice}, cout ~{cost_usd}$).",
                "is_error": False,
                "raw": {
                    "filename": filename,
                    "audio_url": f"/api/agent3/audio/{filename}",
                    "voice": voice, "speed": speed,
                    "cost_usd": cost_usd,
                    "model": "tts-1",
                    "char_count": len(text),
                },
            }
        except Exception as e:
            logger.exception(f"TTS_GEN crashed: {e}")
            return {
                "content": f"Erreur TTS : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    def _todo_write(self, inp: dict) -> dict:
        """Cree ou met a jour un TodoTracker par utilisateur (in-memory)."""
        from api.agent3_todo_tracker import get_todo_tracker

        mode = (inp.get("mode") or "").strip().lower()
        if mode not in {"create", "start", "complete", "fail", "skip", "list"}:
            return {
                "content": "Parametre 'mode' invalide. Attendu : create|start|complete|fail|skip|list.",
                "is_error": True, "raw": {},
            }

        uid = self.user_id or "anon"
        tracker = get_todo_tracker(uid, create=(mode == "create"))
        if tracker is None:
            return {
                "content": "Aucun tracker actif. Utilise mode='create' pour en initialiser un.",
                "is_error": True, "raw": {},
            }

        try:
            if mode == "create":
                items = inp.get("items") or []
                if not isinstance(items, list) or not items:
                    return {"content": "'items' doit etre une liste non vide.", "is_error": True, "raw": {}}
                created = tracker.create_batch(items)
                return {
                    "content": f"{len(created)} todos cree(s).",
                    "is_error": False,
                    "raw": {"snapshot": tracker.to_sse_snapshot()},
                }

            if mode == "list":
                return {
                    "content": f"Etat : {tracker.get_summary()['counts']}.",
                    "is_error": False,
                    "raw": {"snapshot": tracker.to_sse_snapshot()},
                }

            item_id = (inp.get("item_id") or "").strip()
            if not item_id:
                return {"content": "'item_id' requis pour cette operation.", "is_error": True, "raw": {}}

            if mode == "start":
                tr = tracker.start(item_id)
            elif mode == "complete":
                tr = tracker.complete(item_id, inp.get("result", ""))
            elif mode == "fail":
                tr = tracker.fail(item_id, inp.get("error", ""))
            elif mode == "skip":
                tr = tracker.skip(item_id, inp.get("result", ""))
            else:
                tr = None

            if tr is None:
                return {
                    "content": f"Transition '{mode}' impossible pour {item_id} (item inconnu ou statut incompatible).",
                    "is_error": True, "raw": {"snapshot": tracker.to_sse_snapshot()},
                }
            return {
                "content": f"Todo {item_id} -> {tr.new_status}.",
                "is_error": False,
                "raw": {"transition": tr.to_sse_data(), "snapshot": tracker.to_sse_snapshot()},
            }
        except Exception as e:
            logger.exception(f"TODO_WRITE failed: {e}")
            return {
                "content": f"Erreur tracker : {type(e).__name__} {e}",
                "is_error": True, "raw": {},
            }

    async def _openclaw_direct(
        self, anthropic_name: str, inp: dict,
    ) -> dict:
        """Route un tool_use OpenClaw direct (browser, exec, fs_read, ...) vers le Gateway.

        Le LLM invoque `browser`, `exec`, `image_generate`, etc. avec `{action?, args?}`.
        Le dispatcher convertit le nom Anthropic en nom OpenClaw (ex: `fs_read` -> `read`)
        et appelle `openclaw_invoke_tool(tool_name, action, args, session_key)`.

        Retry + circuit breaker sont geres par openclaw_bridge.openclaw_invoke_tool.
        Cost cap : si le cout projete depasse la limite journaliere du user, on
        bloque AVANT l'appel.
        """
        from api.openclaw_bridge import (
            openclaw_invoke_tool, check_daily_cost_cap, record_daily_cost,
            DEFAULT_DAILY_COST_CAP_USD,
        )
        from api.openclaw_tool_schemas import (
            openclaw_name_from_anthropic, estimate_tool_cost_usd,
        )
        oc_name = openclaw_name_from_anthropic(anthropic_name)
        action = str(inp.get("action", "default") or "default")
        raw_args = inp.get("args")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}

        # ── Multi-user direct provider short-circuit ────────────────
        # Pour les 6 providers web search (perplexity, brave, tavily, exa,
        # firecrawl, x_search), si l'user a sa propre cle dans le Credential
        # Vault, on by-pass OpenClaw Gateway et on appelle directement l'API
        # tierce avec la cle user. Garantit l'isolation multi-tenant (chaque
        # user utilise SA cle, sans sync file partage).
        try:
            from api.web_providers import PROVIDER_MAP, has_user_key_for, invoke_provider
            if (
                anthropic_name in PROVIDER_MAP
                and self.user_id
                and await has_user_key_for(self.db, self.user_id, anthropic_name)
            ):
                result = await invoke_provider(
                    self.db, self.user_id, anthropic_name, args,
                )
                if result.get("ok"):
                    # Track cost reel
                    cost_usd = float(result.get("cost_usd") or 0.0)
                    if cost_usd > 0 and self.user_id:
                        try:
                            from api.openclaw_bridge import record_daily_cost
                            record_daily_cost(self.user_id, cost_usd)
                        except Exception:
                            pass
                    # Serialise results pour le LLM
                    import json as _json
                    return {
                        "content": _json.dumps({
                            "provider": result.get("provider"),
                            "query": result.get("query") or result.get("url"),
                            "answer": result.get("answer", ""),
                            "results": result.get("results", []),
                            "markdown": result.get("markdown", ""),
                            "direct_vault_key": True,  # flag pour audit
                        }, ensure_ascii=False)[:8000],
                        "is_error": False,
                        "raw": {
                            "direct_provider": result.get("provider"),
                            "cost_usd": cost_usd,
                            "count": len(result.get("results", [])),
                        },
                    }
                # Erreur direct-provider : fallback vers OpenClaw Gateway (best-effort).
                logger.info(
                    f"Direct provider {anthropic_name} failed ({result.get('error')}), "
                    "fallback OpenClaw Gateway"
                )
        except Exception as _direct_err:
            logger.debug(f"direct provider path failed: {_direct_err}")

        # ── Cost cap pre-check ───────────────────────────────────────
        # Estime le cout via pricing statique (le vrai cost_usd ne sera
        # connu qu'apres l'appel — on utilise l'estimation haute pour decider).
        projected_cost = estimate_tool_cost_usd(anthropic_name)
        if projected_cost > 0 and self.user_id:
            cap = await self._user_daily_cap_usd()
            allowed, current, pct = check_daily_cost_cap(
                self.user_id, projected_cost, cap,
            )
            if not allowed:
                return {
                    "content": (
                        f"Budget quotidien atteint ({current:.4f}$ / {cap}$). "
                        f"L'appel a '{anthropic_name}' (cout estime {projected_cost:.4f}$) "
                        "depasserait la limite. Reessaie demain ou augmente ton cap "
                        "(preferences `external_cost_cap_usd_per_day`)."
                    ),
                    "is_error": True,
                    "raw": {
                        "cost_cap_exceeded": True,
                        "cap_usd": cap,
                        "current_usd": round(current, 5),
                        "projected_usd": round(projected_cost, 5),
                        "pct": round(pct, 1),
                    },
                }

        try:
            resp = await openclaw_invoke_tool(
                tool_name=oc_name,
                action=action,
                args=args,
                session_key=self.session_key,
            )
        except Exception as e:
            logger.exception(f"OpenClaw invoke {oc_name} crashed: {e}")
            from api.agent3_security import friendly_openclaw_tool_error
            # On tente le mapping par tool (plus precis), avec fallback
            # sur le message d'exception generique.
            friendly = friendly_openclaw_tool_error(
                anthropic_name, str(e),
                fallback=friendly_exception_message(
                    e, fallback=f"Echec de l'outil OpenClaw '{oc_name}'.",
                ),
            )
            return {
                "content": friendly,
                "is_error": True,
                "raw": {"tool": oc_name, "error": str(e), "friendly": friendly},
            }

        if not resp.get("success"):
            raw_err = str(resp.get("error", "?"))
            # Traduit l'erreur brute en message FR user-friendly par tool.
            from api.agent3_security import friendly_openclaw_tool_error
            friendly = friendly_openclaw_tool_error(anthropic_name, raw_err)
            return {
                "content": friendly,
                "is_error": True,
                "raw": {"tool": oc_name, "error": raw_err, "friendly": friendly},
            }

        result = resp.get("result")
        # Tool result shaping : extraire les champs cles par groupe de tools.
        # Retourne (content_for_llm, action_card) ou card est un dict optionnel
        # pour un event SSE `action_done` cote frontend (lien cliquable, image, ...).
        from api.openclaw_result_shaping import shape_openclaw_result
        content_shaped, action_card = shape_openclaw_result(anthropic_name, result)

        # Track le cout externe (USD) du tool pour ce user.
        # Priorite au cost_usd retourne par le Gateway, sinon estimation statique.
        try:
            from api.openclaw_tool_schemas import estimate_tool_cost_usd
            from api.openclaw_bridge import record_external_cost
            cost = estimate_tool_cost_usd(anthropic_name, result)
            record_external_cost(self.user_id or "anon", anthropic_name, cost)
            # Cumul journalier (pour le cost cap).
            if cost > 0 and self.user_id:
                record_daily_cost(self.user_id, cost)
        except Exception as _cost_err:
            logger.debug(f"cost tracking failed for {anthropic_name}: {_cost_err}")
            cost = 0.0

        raw_payload: dict[str, Any] = {
            "tool": oc_name,
            "anthropic_name": anthropic_name,
            "action": action,
            "result": result,
            "cost_usd": round(cost, 5),
        }
        if action_card is not None:
            # Enrichit la card avec le cout (si non nul et pas deja present).
            if cost > 0 and action_card.get("cost_usd") is None:
                action_card["cost_usd"] = round(cost, 5)
            raw_payload["action_card"] = action_card

        return {
            "content": content_shaped,
            "is_error": False,
            "raw": raw_payload,
        }

    def _not_implemented(self, action_type: str) -> dict:
        return {
            "content": (
                f"L'outil '{action_type.lower()}' n'est pas encore cable dans la "
                f"boucle agentique native. Actions disponibles : "
                f"{', '.join(sorted(self.SUPPORTED)).lower()}. "
                "Pour cette demande, termine avec une reponse textuelle a l'utilisateur "
                "expliquant la limite et propose une alternative."
            ),
            "is_error": True,
            "raw": {"action_type": action_type, "supported": sorted(self.SUPPORTED)},
        }

    # ═══════════════════════════════════════════════════════════════════════
    #  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
    # ═══════════════════════════════════════════════════════════════════════

    async def _vision_analyze_async(self, inp: dict) -> dict:
        """Version PG-compatible de _vision_analyze (SELECT via SQLAlchemy)."""
        if not self.user_id:
            return {
                "content": "Analyse vision indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        file_id = (inp.get("file_id") or "").strip()
        prompt = (inp.get("prompt") or "").strip()
        if not file_id:
            return {"content": "Parametre 'file_id' requis.", "is_error": True, "raw": {}}
        if not prompt:
            return {"content": "Parametre 'prompt' requis.", "is_error": True, "raw": {}}
        if len(prompt) > 2000:
            return {
                "content": f"Prompt trop long ({len(prompt)} chars, max 2000).",
                "is_error": True, "raw": {},
            }

        # Resoudre le path via agent3_files + verifier appartenance user
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        try:
            async with factory() as session:
                result = await session.execute(
                    text(
                        "SELECT filepath, filetype, filename FROM agent3_files "
                        "WHERE id = :id AND auth_user_id = :uid"
                    ),
                    {"id": file_id, "uid": self.user_id},
                )
                row = result.first()
        except Exception as e:
            return {
                "content": f"Erreur DB : {type(e).__name__}",
                "is_error": True, "raw": {"error": str(e)},
            }
        if not row:
            return {
                "content": f"Fichier {file_id} introuvable ou n'appartient pas a l'utilisateur.",
                "is_error": True, "raw": {},
            }
        filepath, filetype, filename = row[0], row[1], row[2]
        if not (filetype or "").startswith("image/"):
            return {
                "content": f"Le fichier {filename} n'est pas une image ({filetype}).",
                "is_error": True, "raw": {"filetype": filetype},
            }

        try:
            from api.routers.agent3_openclaw import _analyze_image_with_vision
            description = await _analyze_image_with_vision(filepath, prompt)
        except Exception as e:
            logger.exception(f"vision_analyze_async crashed: {e}")
            return {
                "content": f"Erreur analyse vision : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

        if description and description.startswith("["):
            return {
                "content": description,
                "is_error": True,
                "raw": {"file_id": file_id, "filename": filename},
            }

        return {
            "content": f"## Analyse de {filename}\n\n{description}",
            "is_error": False,
            "raw": {
                "file_id": file_id,
                "filename": filename,
                "prompt": prompt,
                "description_length": len(description or ""),
            },
        }

    async def _memory_search_async(self, inp: dict) -> dict:
        """Version PG-compatible de _memory_search (multi-token LIKE OR).

        Reprend la logique de tokenisation FR/EN + stopwords du legacy mais
        execute la requete via SQLAlchemy text() (parametres nommes).
        """
        if not self.user_id:
            return {
                "content": "Memoire indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }
        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' manquant.", "is_error": True, "raw": {}}
        if len(query) > _MAX_QUERY_LEN:
            return {
                "content": f"Query trop longue ({len(query)} chars, max {_MAX_QUERY_LEN}).",
                "is_error": True, "raw": {},
            }

        def _escape_like(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        import re as _re
        tokens = [t for t in _re.split(r"[\s,;:./]+", query.lower()) if len(t) >= 3]
        _STOP = {"des", "les", "une", "mes", "tes", "ses", "tous", "tout",
                 "the", "and", "for", "with", "que", "qui", "quoi", "quel",
                 "quels", "quelles", "this", "that", "have", "from"}
        tokens = [t for t in tokens if t not in _STOP]
        if not tokens:
            tokens = [query.lower()]

        # Construit la clause OR avec parametres nommes (:k0, :v0, :k1, :v1, ...)
        like_clauses: list[str] = []
        params: dict[str, Any] = {"uid": self.user_id}
        for i, tok in enumerate(tokens[:8]):
            esc = _escape_like(tok)
            like_clauses.append(
                f"(key LIKE :k{i} ESCAPE '\\' OR value LIKE :v{i} ESCAPE '\\')"
            )
            params[f"k{i}"] = f"%{esc}%"
            params[f"v{i}"] = f"%{esc}%"
        sql = (
            "SELECT key, value, category, updated_at FROM agent3_memory "
            f"WHERE auth_user_id = :uid AND ({' OR '.join(like_clauses)}) "
            "ORDER BY updated_at DESC LIMIT 20"
        )

        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        try:
            async with factory() as session:
                result = await session.execute(text(sql), params)
                rows = result.mappings().all()
        except Exception as e:
            logger.debug(f"_memory_search_async failed: {e}")
            return {
                "content": f"Erreur recherche memoire : {type(e).__name__}",
                "is_error": True, "raw": {"error": str(e)},
            }

        if not rows:
            return {
                "content": f"Aucun souvenir trouve pour '{query}'.",
                "is_error": False,
                "raw": {"query": query, "count": 0},
            }
        lines = [f"- {r['key']}: {(r['value'] or '')[:200]}" for r in rows]
        return {
            "content": f"{len(rows)} souvenirs trouves :\n" + "\n".join(lines),
            "is_error": False,
            "raw": {"query": query, "count": len(rows)},
        }

    async def _cron_async(self, inp: dict) -> dict:
        """Version PG-compatible de _cron (CREATE TABLE + INSERT via SQLAlchemy).

        Ne s'appuie plus sur DatabaseManager : utilise get_session_factory().
        """
        import uuid
        from datetime import datetime, timezone
        from sqlalchemy import text
        from api.database import get_session_factory

        label = (inp.get("label") or "Tache Sylea").strip()
        instruction = (inp.get("instruction") or "").strip()
        cron_expr = (inp.get("cron_expr") or inp.get("schedule") or "0 9 * * *").strip()
        if not instruction:
            return {
                "content": "Champ 'instruction' requis : quoi executer a chaque tick.",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "CRON indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }

        cron_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        factory = get_session_factory()
        try:
            async with factory() as session:
                try:
                    await session.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS agent3_cron ("
                            "id TEXT PRIMARY KEY, auth_user_id TEXT, label TEXT, "
                            "instruction TEXT, cron_expr TEXT, enabled INTEGER DEFAULT 1, "
                            "created_at TEXT)"
                        )
                    )
                    await session.execute(
                        text(
                            "INSERT INTO agent3_cron "
                            "(id, auth_user_id, label, instruction, cron_expr, "
                            " enabled, created_at) "
                            "VALUES (:id, :uid, :label, :instr, :expr, 1, :now)"
                        ),
                        {
                            "id": cron_id,
                            "uid": self.user_id,
                            "label": label,
                            "instr": instruction,
                            "expr": cron_expr,
                            "now": now,
                        },
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            return {
                "content": (
                    f"Tache '{label}' programmee ({cron_expr}). "
                    "Elle s'executera selon le planning."
                ),
                "is_error": False,
                "raw": {
                    "cron_id": cron_id, "label": label,
                    "cron_expr": cron_expr, "instruction": instruction[:200],
                },
            }
        except Exception as e:
            logger.exception(f"CRON async insert failed: {e}")
            return {
                "content": f"Erreur programmation cron : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }

    async def _reminder_async(self, inp: dict) -> dict:
        """Version PG-compatible de _reminder (CREATE TABLE + INSERT via SQLAlchemy)."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text
        from api.database import get_session_factory

        message = (inp.get("message") or inp.get("text") or "").strip()
        if not message:
            return {
                "content": "Champ 'message' requis : que dois-je te rappeler ?",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "REMINDER indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }

        delay_minutes = inp.get("delay_minutes")
        rdate = (inp.get("reminder_date") or "").strip()
        rtime = (inp.get("reminder_time") or "").strip()

        if delay_minutes is not None:
            try:
                delay = int(delay_minutes)
            except (ValueError, TypeError):
                return {
                    "content": "delay_minutes doit etre un entier (minutes)",
                    "is_error": True, "raw": {},
                }
            target = datetime.now(timezone.utc) + timedelta(minutes=delay)
            target_local = target.astimezone()
            rdate = target_local.strftime("%Y-%m-%d")
            rtime = target_local.strftime("%H:%M")
        elif not (rdate and rtime):
            return {
                "content": (
                    "Fournis soit `delay_minutes` (ex 120 pour 2h) "
                    "soit `reminder_date`+`reminder_time`."
                ),
                "is_error": True, "raw": {},
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        factory = get_session_factory()
        try:
            async with factory() as session:
                try:
                    await session.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS agent_reminders ("
                            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                            "user_id TEXT NOT NULL, "
                            "agent_id TEXT DEFAULT 'agent3', "
                            "reminder_time TEXT NOT NULL, "
                            "reminder_date TEXT NOT NULL, "
                            "message TEXT NOT NULL, "
                            "completed INTEGER DEFAULT 0, "
                            "created_at TEXT NOT NULL)"
                        )
                    )
                    result = await session.execute(
                        text(
                            "INSERT INTO agent_reminders "
                            "(user_id, agent_id, reminder_time, reminder_date, "
                            " message, completed, created_at) "
                            "VALUES (:uid, 'agent3', :rtime, :rdate, :msg, 0, :now)"
                        ),
                        {
                            "uid": self.user_id,
                            "rtime": rtime,
                            "rdate": rdate,
                            "msg": message,
                            "now": now_iso,
                        },
                    )
                    await session.commit()
                    # lastrowid : seulement disponible en SQLite ; en PG on n'a
                    # pas l'id (la table utilise AUTOINCREMENT/SERIAL).
                    reminder_id = getattr(result, "lastrowid", None)
                except Exception:
                    await session.rollback()
                    raise
            return {
                "content": (
                    f"Rappel programme pour {rdate} a {rtime} : \"{message[:80]}\""
                ),
                "is_error": False,
                "raw": {
                    "reminder_id": reminder_id,
                    "reminder_date": rdate,
                    "reminder_time": rtime,
                    "message": message[:200],
                },
            }
        except Exception as e:
            logger.exception(f"REMINDER async insert failed: {e}")
            return {
                "content": f"Erreur programmation rappel : {type(e).__name__} {e}",
                "is_error": True, "raw": {"error": str(e)},
            }


__all__ = ["Agent3ActionDispatcher"]
