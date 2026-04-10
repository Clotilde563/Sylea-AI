"""
Application FastAPI principale — Syléa.AI Web GUI.

Orchestre :
  - CORS pour le frontend React (Vite sur :5173)
  - Inclusion des routers : profil, dilemme, historique
  - Connexion DB par requête (request-scoped, thread-safe)

Lancement :
  uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Assurer l'encodage UTF-8 sur Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Charger .env si présent
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from api.dependencies import get_optional_user
from api.routers import profil, dilemme, historique, evenement, bilan, objectifs, service_client
from api.routers.agent_companion import router as agent_companion_router
from api.routers.agent_assistant import router as agent_assistant_router
from api.routers.agent3_openclaw import router as agent3_router
from api.routers.coaching import router as coaching_router
from api.routers.network import router as network_router
from api.routers.workspace import router as workspace_router
from api.routers.scenarios import router as scenarios_router
from api.auth.router import router as auth_router
from api.routers.integrations import router as integrations_router
from api.routers.notifications import router as notifications_router
from api.routers.shared_workspaces import router as shared_workspaces_router
from api.schemas import HealthOut


# ── Initialisation tables Agent 3 au démarrage ────────────────────────────────
def _init_agent3_tables():
    """Crée les tables Agent 3 (cron, memory, files, preferences, tasks) au démarrage."""
    try:
        from sylea.core.storage.database import DatabaseManager
        from api.routers.agent3_openclaw import _ensure_agent3_tables
        db = DatabaseManager()
        db.connect()
        try:
            _ensure_agent3_tables(db)
        finally:
            db.disconnect()
    except Exception:
        pass  # DB not available yet or import error — tables will be created on first use

_init_agent3_tables()

# Start background cron scheduler
from api.scheduler import scheduler as cron_scheduler
cron_scheduler.start()


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Syléa.AI API",
    version="1.0.0",
    description="API REST pour l'application Syléa.AI — Votre assistant de vie augmenté.",
)

# CORS : autoriser le frontend React (dev + production)
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost:1420",
    "https://sylea-ai.vercel.app",   # Production frontend
    "https://*.vercel.app",          # Preview deployments
    "tauri://localhost",
    "https://tauri.localhost",
]

extra_origins = os.environ.get("CORS_ORIGINS", "")
if extra_origins:
    origins.extend(extra_origins.split(","))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(profil.router)
app.include_router(dilemme.router)
app.include_router(historique.router)
app.include_router(evenement.router)
app.include_router(bilan.router)
app.include_router(objectifs.router)
app.include_router(service_client.router)
app.include_router(agent_companion_router)
app.include_router(agent_assistant_router)
app.include_router(agent3_router)
app.include_router(coaching_router)
app.include_router(network_router)
app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(scenarios_router)
app.include_router(integrations_router)
app.include_router(notifications_router)
app.include_router(shared_workspaces_router)


# ── Routes utilitaires ────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthOut, tags=["system"])
def health_check():
    """Liveness check — retourne 200 si l'API est opérationnelle."""
    return HealthOut(status="ok", version="1.0.0")


# ── WebSocket pour le desktop ─────────────────────────────────────────────────

@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket, token: str = Query(default="")):
    """WebSocket pour l'app desktop Syléa Agent — accepte toutes les origines."""
    from api.websocket import ws_manager
    from api.auth.security import decode_token

    # Accepter la connexion AVANT la validation du token
    # (sinon le CORS middleware bloque)
    if not token:
        await websocket.accept()
        await websocket.close(code=4001, reason="Token manquant")
        return

    user_id = decode_token(token)
    if not user_id:
        await websocket.accept()
        await websocket.close(code=4001, reason="Token invalide")
        return

    await ws_manager.connect(websocket, user_id)
    print(f"[WS] User {user_id} connected successfully")
    try:
        # Send a welcome message to confirm connection
        await websocket.send_json({"type": "connected", "message": "Desktop connecte"})
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        print(f"[WS] User {user_id} disconnected")
        ws_manager.disconnect(websocket, user_id)
    except Exception as e:
        print(f"[WS] Error for user {user_id}: {e}")
        ws_manager.disconnect(websocket, user_id)


@app.get("/api/desktop/status", tags=["desktop"])
async def desktop_status(user_id: str | None = Depends(get_optional_user)):
    """Vérifie si l'app desktop est connectée pour cet utilisateur."""
    from api.websocket import ws_manager
    return {"connected": ws_manager.is_connected(user_id) if user_id else False}


@app.get("/", include_in_schema=False)
def root():
    """Redirect info vers le frontend."""
    return JSONResponse(
        content={
            "message": "Syléa.AI API — ouvrez http://localhost:5173 pour l'interface graphique.",
            "docs": "/docs",
            "health": "/api/health",
        }
    )
# reload trigger
