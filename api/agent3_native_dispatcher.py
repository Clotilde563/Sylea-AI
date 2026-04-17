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

logger = logging.getLogger("agent3.dispatcher")


class Agent3ActionDispatcher:
    """Execute les tool_use recus par l'AgenticLoop.

    Contract (ActionExecutor protocol) :
        async def execute(action_type: str, action_input: dict) -> dict
    Retourne : {"content": str, "is_error": bool, "raw": Any}
    """

    # Actions supportees nativement. Le reste remonte une erreur pedagogique au LLM.
    SUPPORTED: set[str] = {
        # Read-only / network
        "SEARCH",
        "X_SEARCH",
        "WEB_FETCH",
        # Memoire
        "MEMORY",
        "MEMORY_SEARCH",
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
        "COMPUTER_USE",
        # Delegation a un sous-agent (non destructif, mais meta-outil special)
        "SPAWN_AGENT",
        # Planification / tracker (non destructif, in-memory)
        "TODO_WRITE",
    }

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
        if action_type not in self.SUPPORTED:
            return self._not_implemented(action_type)

        try:
            if action_type == "SEARCH":
                return await self._search(action_input)
            if action_type == "X_SEARCH":
                return await self._x_search(action_input)
            if action_type == "WEB_FETCH":
                return await self._web_fetch(action_input)
            if action_type == "MEMORY":
                return self._memory_save(action_input)
            if action_type == "MEMORY_SEARCH":
                return self._memory_search(action_input)
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
                return self._file_create(action_input)
            if action_type == "EMAIL":
                return self._email(action_input)
            if action_type == "GMAIL_SEND":
                return self._gmail_send(action_input)
            if action_type == "CALENDAR_EVENT":
                return self._calendar_event(action_input)
            if action_type == "DRIVE_SAVE":
                return self._drive_save(action_input)
            if action_type == "CRON":
                return self._cron(action_input)
            if action_type == "COMPUTER_USE":
                return await self._computer_use(action_input)
            if action_type == "SPAWN_AGENT":
                return await self._spawn_agent(action_input)
            if action_type == "TODO_WRITE":
                return self._todo_write(action_input)
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
        max_results = int(inp.get("max_results") or 5)

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
        if not url:
            return {"content": "Parametre 'url' manquant.", "is_error": True, "raw": {}}
        if not url.startswith(("http://", "https://")):
            return {
                "content": f"URL invalide (doit commencer par http:// ou https://): {url}",
                "is_error": True,
                "raw": {"url": url},
            }
        # httpx async — reutilise la dependance du projet.
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "Syléa-Agent3/1.0"})
                r.raise_for_status()
                # Priorite au texte sur HTML. On cap a 8k caracteres.
                text = r.text[:8000]
                return {
                    "content": text,
                    "is_error": False,
                    "raw": {"url": url, "status": r.status_code, "size": len(r.text)},
                }
        except httpx.HTTPStatusError as e:
            return {
                "content": f"HTTP {e.response.status_code} pour {url}",
                "is_error": True,
                "raw": {"url": url, "status": e.response.status_code},
            }
        except Exception as e:
            return {
                "content": f"Erreur reseau : {type(e).__name__} {e}",
                "is_error": True,
                "raw": {"url": url, "error": str(e)},
            }

    def _memory_save(self, inp: dict) -> dict:
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
        # Reuse du helper existant dans le router.
        from api.routers.agent3_openclaw import _save_memory
        _save_memory(self.db, self.user_id, key, value, "native")
        return {
            "content": f"Memorise : {key} = {value[:80]}{'...' if len(value) > 80 else ''}",
            "is_error": False,
            "raw": {"key": key},
        }

    def _memory_search(self, inp: dict) -> dict:
        if not self.user_id:
            return {
                "content": "Memoire indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }
        query = (inp.get("query") or "").strip()
        if not query:
            return {"content": "Parametre 'query' manquant.", "is_error": True, "raw": {}}

        # Requete SQL simple (LIKE) sur key et value. Peut etre remplace par
        # une recherche semantique plus tard.
        rows = self.db.conn.execute(
            "SELECT key, value, category, updated_at FROM agent3_memory "
            "WHERE auth_user_id = ? AND (key LIKE ? OR value LIKE ?) "
            "ORDER BY updated_at DESC LIMIT 20",
            (self.user_id, f"%{query}%", f"%{query}%"),
        ).fetchall()
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
        from api.routers.agent3_openclaw import _generate_pdf
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
        ici — si besoin, route vers le handler legacy dans agent3_openclaw.py)."""
        from pathlib import Path as _P
        filename = (inp.get("filename") or inp.get("path") or "").strip()
        if not filename:
            return {"content": "Parametre 'filename' requis.", "is_error": True, "raw": {}}

        ws_base = _P(__file__).resolve().parent.parent / "data" / "workspace"
        try:
            # Resolve en restant dans le workspace (anti-traversal).
            resolved = (ws_base / filename).resolve()
            if not str(resolved).startswith(str(ws_base.resolve())):
                return {
                    "content": f"Chemin hors workspace refuse : {filename}",
                    "is_error": True,
                    "raw": {"filename": filename},
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

    async def _calendar_list(self, inp: dict) -> dict:
        if not self.user_id:
            return {
                "content": "Calendar indisponible : utilisateur non authentifie.",
                "is_error": True,
                "raw": {},
            }
        try:
            from api.routers.integrations import _get_integration
            integ = _get_integration(self.db, self.user_id, "google_calendar")
        except Exception as e:
            return {
                "content": f"Integration Google Calendar indisponible : {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }
        token = (integ or {}).get("access_token", "")
        if not token or len(token) < 20:
            return {
                "content": "Google Calendar non connecte. Configure l'integration avant.",
                "is_error": True,
                "raw": {},
            }

        import httpx
        from datetime import datetime, timezone
        days = int(inp.get("days") or 7)
        time_min = datetime.now(timezone.utc).isoformat()
        params = f"timeMin={time_min}&singleEvents=true&orderBy=startTime&maxResults={min(days * 3, 20)}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}",
                    headers={"Authorization": f"Bearer {token}"},
                )
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
        try:
            from api.routers.integrations import _get_integration
            integ = _get_integration(self.db, self.user_id, "gmail")
        except Exception as e:
            return {
                "content": f"Integration Gmail indisponible : {e}",
                "is_error": True,
                "raw": {"error": str(e)},
            }
        token = (integ or {}).get("access_token", "")
        if not token or len(token) < 20:
            return {
                "content": "Gmail non connecte. Configure l'integration avant.",
                "is_error": True,
                "raw": {},
            }

        import httpx
        query = (inp.get("query") or "is:unread").strip()
        limit = min(int(inp.get("limit") or 10), 20)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://www.googleapis.com/gmail/v1/users/me/messages?q={query}&maxResults={limit}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if r.status_code != 200:
                    return {
                        "content": f"Gmail API {r.status_code}",
                        "is_error": True,
                        "raw": {"status": r.status_code},
                    }
                msg_ids = [m["id"] for m in r.json().get("messages", [])[:limit]]
                emails: list[dict] = []
                for mid in msg_ids:
                    d = await client.get(
                        f"https://www.googleapis.com/gmail/v1/users/me/messages/{mid}"
                        "?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if d.status_code == 200:
                        payload = d.json()
                        headers = {h["name"]: h["value"] for h in payload.get("payload", {}).get("headers", [])}
                        emails.append({
                            "subject": headers.get("Subject", ""),
                            "from": headers.get("From", ""),
                            "date": headers.get("Date", ""),
                            "snippet": payload.get("snippet", "")[:200],
                        })
            if not emails:
                return {"content": f"Aucun email pour '{query}'.", "is_error": False, "raw": {"emails": []}}
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

    def _file_create(self, inp: dict) -> dict:
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
                from api.routers.agent3_openclaw import (
                    get_workspace_folder_name, WORKSPACE_BASE,
                )
                obj_name = get_workspace_folder_name(self.db, self.user_id)
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
            from api.routers.agent3_openclaw import _save_file_create_fallback
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

    def _email(self, inp: dict) -> dict:
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
            from api.routers.agent3_openclaw import _send_email_smtp
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

        # Fallback Gmail API
        try:
            from api.routers.integrations import _get_integration
            integ = _get_integration(self.db, self.user_id, "gmail")
            token = integ.get("access_token", "") if integ else ""
            if token and len(token) > 20:
                import httpx, base64
                from email.mime.text import MIMEText
                mime = MIMEText(body, "html" if html_flag else "plain", "utf-8")
                mime["To"] = to
                mime["Subject"] = subject
                raw_b = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
                r = httpx.post(
                    "https://www.googleapis.com/gmail/v1/users/me/messages/send",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"raw": raw_b}, timeout=15,
                )
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
        return {
            "content": f"Email non envoye. SMTP indisponible ({smtp_err}) et Gmail non connecte.",
            "is_error": True,
            "raw": {"smtp_error": smtp_err},
        }

    def _gmail_send(self, inp: dict) -> dict:
        """Envoie un email via Gmail API (OAuth)."""
        to = (inp.get("to") or "").strip()
        subject = (inp.get("subject") or "").strip()
        body = inp.get("body") or ""
        if not to or not subject or not body:
            return {
                "content": "Champs requis : 'to', 'subject', 'body'.",
                "is_error": True, "raw": {},
            }
        if not self.user_id:
            return {
                "content": "GMAIL_SEND indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        try:
            from api.routers.integrations import _get_integration
            integ = _get_integration(self.db, self.user_id, "gmail")
            token = integ.get("access_token", "") if integ else ""
            if not token or len(token) <= 20:
                return {
                    "content": "Gmail non connecte. Connecte-toi via Integrations.",
                    "is_error": True, "raw": {},
                }
            import httpx, base64
            from email.mime.text import MIMEText
            mime = MIMEText(body, "plain", "utf-8")
            mime["To"] = to
            mime["Subject"] = subject
            raw_b = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
            r = httpx.post(
                "https://www.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"raw": raw_b}, timeout=15,
            )
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

    def _calendar_event(self, inp: dict) -> dict:
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
            from api.routers.integrations import _get_integration
            integ = _get_integration(self.db, self.user_id, "google_calendar")
            token = integ.get("access_token", "") if integ else ""
            if not token or len(token) <= 20:
                return {
                    "content": "Google Calendar non connecte. Connecte-toi via Integrations.",
                    "is_error": True, "raw": {},
                }
            import httpx
            body = {
                "summary": title,
                "start": {"dateTime": start, "timeZone": "Europe/Paris"},
                "end": {"dateTime": end, "timeZone": "Europe/Paris"},
                "description": description,
            }
            r = httpx.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body, timeout=10,
            )
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

    def _drive_save(self, inp: dict) -> dict:
        """Sauvegarde un fichier dans Google Drive."""
        filename = (inp.get("filename") or "document.txt").strip()
        content = inp.get("content") or ""
        if not content:
            return {"content": "Parametre 'content' vide.", "is_error": True, "raw": {}}
        if not self.user_id:
            return {
                "content": "DRIVE_SAVE indisponible : utilisateur non authentifie.",
                "is_error": True, "raw": {},
            }
        try:
            from api.routers.integrations import _get_integration
            integ = _get_integration(self.db, self.user_id, "google_drive")
            token = integ.get("access_token", "") if integ else ""
            if not token or len(token) <= 20:
                return {
                    "content": "Google Drive non connecte. Connecte-toi via Integrations.",
                    "is_error": True, "raw": {},
                }
            import httpx
            import json as _json
            boundary = "sylea_boundary"
            multipart_body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                + _json.dumps({"name": filename})
                + f"\r\n--{boundary}\r\nContent-Type: text/plain\r\n\r\n"
                + content
                + f"\r\n--{boundary}--"
            )
            r = httpx.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                content=multipart_body.encode("utf-8"),
                timeout=20,
            )
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

    def _cron(self, inp: dict) -> dict:
        """Programme une tache recurrente dans la table agent3_cron."""
        import uuid
        from datetime import datetime, timezone
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
        try:
            # S'assure que la table existe (schema identique a legacy).
            self.db.conn.execute(
                "CREATE TABLE IF NOT EXISTS agent3_cron ("
                "id TEXT PRIMARY KEY, auth_user_id TEXT, label TEXT, "
                "instruction TEXT, cron_expr TEXT, enabled INTEGER DEFAULT 1, "
                "created_at TEXT)"
            )
            cron_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            self.db.conn.execute(
                "INSERT INTO agent3_cron (id, auth_user_id, label, instruction, cron_expr, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (cron_id, self.user_id, label, instruction, cron_expr, now),
            )
            self.db.conn.commit()
            return {
                "content": f"Tache '{label}' programmee ({cron_expr}). Elle s'executera selon le planning.",
                "is_error": False,
                "raw": {
                    "cron_id": cron_id, "label": label,
                    "cron_expr": cron_expr, "instruction": instruction[:200],
                },
            }
        except Exception as e:
            logger.exception(f"CRON insert failed: {e}")
            return {
                "content": f"Erreur programmation cron : {type(e).__name__} {e}",
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
            session = get_session(self.user_id or "default", api_key)
            steps = 0
            final_text = ""
            cost_usd = 0.0
            last_action = ""
            error_msg = ""
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
                model="claude-haiku-4-5-20250929",
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


__all__ = ["Agent3ActionDispatcher"]
