"""
Mock Gateway OpenClaw — serveur HTTP minimal pour les tests e2e.

Simule les endpoints clés du Gateway OpenClaw :
  - `GET  /health`          → 200 OK si "running"
  - `POST /tools/invoke`    → réponses canned selon le tool_name + scénario

Les scénarios de comportement sont contrôlables via une instance `GatewayState`
qu'on configure au début de chaque test :
  - `set_tool_response(tool, result)` : retour JSON du tool sur succès
  - `set_tool_failure(tool, status, body, retry_after=None)` : force un échec HTTP
  - `fail_n_times(tool, n, status)` : échoue N fois puis succès (test retry)
  - `set_timeout(tool, duration)` : délai réponse (test timeout)
  - `set_health_down()` / `set_health_up()` : contrôle du /health

Usage :
    from tests.e2e.mock_openclaw_gateway import MockGateway
    async with MockGateway() as mock:
        mock.state.set_tool_response("browser", {"url": "x", "screenshot_url": "/tmp/s.png"})
        # ... vos tests appellent openclaw_invoke_tool ...

Implémentation : FastAPI + uvicorn en thread (pas asyncio.create_task, qui
boucle avec pytest-asyncio). Chaque instance écoute sur un port aléatoire
pour permettre l'exécution en parallèle.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response


def _find_free_port() -> int:
    """Trouve un port TCP libre."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class ToolResponse:
    """Décrit comment le mock doit répondre pour un tool donné."""
    # Réponse par défaut (status 200 + JSON)
    success_result: dict[str, Any] | None = None
    # Ou forcer un échec
    failure_status: int | None = None
    failure_body: str = ""
    retry_after_seconds: float | None = None
    # Ou simuler un timeout (durée > client timeout)
    timeout_duration_s: float | None = None
    # Compteur pour "fail N times puis success"
    fail_remaining: int = 0
    fail_status: int = 503


@dataclass
class GatewayState:
    """État mutable du mock pendant un test."""
    is_healthy: bool = True
    tools: dict[str, ToolResponse] = field(default_factory=dict)
    # Historique des invocations reçues (pour assertions)
    received_invocations: list[dict[str, Any]] = field(default_factory=list)

    # ── Configuration scenarios ─────────────────────────────────────────
    def set_tool_response(self, tool_name: str, result: dict[str, Any]) -> None:
        self.tools[tool_name] = ToolResponse(success_result=result)

    def set_tool_failure(
        self, tool_name: str, status: int = 500, body: str = "error",
        retry_after: float | None = None,
    ) -> None:
        self.tools[tool_name] = ToolResponse(
            failure_status=status, failure_body=body, retry_after_seconds=retry_after,
        )

    def fail_n_times(
        self, tool_name: str, n: int, status: int = 503,
        then_result: dict[str, Any] | None = None,
    ) -> None:
        """Echoue N fois puis succès (teste les retries)."""
        self.tools[tool_name] = ToolResponse(
            success_result=then_result or {"ok": True},
            fail_remaining=n,
            fail_status=status,
        )

    def set_tool_timeout(self, tool_name: str, duration_s: float) -> None:
        self.tools[tool_name] = ToolResponse(timeout_duration_s=duration_s)

    def set_health_down(self) -> None:
        self.is_healthy = False

    def set_health_up(self) -> None:
        self.is_healthy = True

    def reset(self) -> None:
        self.is_healthy = True
        self.tools.clear()
        self.received_invocations.clear()


def _build_app(state: GatewayState) -> FastAPI:
    """Crée une instance FastAPI bound à l'état du mock."""
    app = FastAPI(title="Mock OpenClaw Gateway")

    @app.get("/health")
    async def health():
        if not state.is_healthy:
            raise HTTPException(status_code=503, detail="Gateway unhealthy (mock)")
        return {"ok": True, "status": "live", "mock": True}

    @app.post("/tools/invoke")
    async def invoke(request: Request):
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        tool_name = str(payload.get("tool", ""))
        action = str(payload.get("action", "default"))
        args = payload.get("args") or {}

        # Log de l'invocation pour les assertions
        state.received_invocations.append({
            "tool": tool_name, "action": action, "args": args,
            "ts": time.time(),
        })

        cfg = state.tools.get(tool_name)
        if cfg is None:
            # Pas configuré : on répond succès trivial par défaut
            return {"ok": True, "mock_default": True, "tool": tool_name}

        # Timeout simulé : on dort, le client va timeout avant
        if cfg.timeout_duration_s is not None:
            await asyncio.sleep(cfg.timeout_duration_s)
            return {"ok": True, "after_sleep": True}

        # Echec permanent forcé
        if cfg.failure_status is not None:
            headers: dict[str, str] = {}
            if cfg.retry_after_seconds is not None:
                headers["retry-after"] = str(cfg.retry_after_seconds)
            return Response(
                content=cfg.failure_body,
                status_code=cfg.failure_status,
                headers=headers,
            )

        # Scénario "fail N times puis success"
        if cfg.fail_remaining > 0:
            cfg.fail_remaining -= 1
            return Response(
                content=f"Transient failure (remaining={cfg.fail_remaining})",
                status_code=cfg.fail_status,
            )

        # Succès : retourne le result configuré
        return cfg.success_result or {"ok": True}

    return app


class MockGateway:
    """Context manager qui spawn un mock Gateway sur un port libre.

    Usage :
        async with MockGateway() as mock:
            mock.state.set_tool_response("browser", {"url": "https://x.com"})
            # Les appels via openclaw_invoke_tool iront vers mock.url
    """

    def __init__(self) -> None:
        self.state = GatewayState()
        self.port = _find_free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    async def __aenter__(self) -> "MockGateway":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    async def start(self) -> None:
        app = _build_app(self.state)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port,
            log_level="warning", access_log=False,
        )
        self._server = uvicorn.Server(config)
        # Lance uvicorn dans un thread pour ne pas bloquer l'event loop pytest.
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name=f"MockGateway-{self.port}",
        )
        self._thread.start()
        # Attend que le serveur soit prêt (max 3s)
        import httpx
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=0.3) as c:
                    r = await c.get(f"{self.url}/health")
                    if r.status_code in (200, 503):
                        return
            except Exception:
                pass
            await asyncio.sleep(0.05)
        raise RuntimeError(f"Mock gateway did not start on port {self.port}")

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            # Attend que le thread termine proprement (timeout safety 2s)
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
