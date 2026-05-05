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

import asyncio
import os
import sys

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Assurer l'encodage UTF-8 sur Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Playwright (BrowserAgent) necessite ProactorEventLoop sur Windows
# pour pouvoir spawner son process node.js via asyncio.subprocess_exec.
# Sans ca : NotImplementedError dans _make_subprocess_transport.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
from api.auth.router import router as auth_router
from api.routers.integrations import router as integrations_router
from api.routers.notifications import router as notifications_router
from api.routers.shared_workspaces import router as shared_workspaces_router
from api.routers.credentials_vault import router as credentials_vault_router
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

# Start background cron scheduler — opt-in via env var pour eviter les fuites
# de cout quand personne n'utilise l'app. Defaut OFF (protege contre les
# appels Anthropic silencieux toutes les 60s).
_scheduler_enabled = os.environ.get("SYLEA_SCHEDULER_ENABLED", "false").strip().lower()
if _scheduler_enabled in ("1", "true", "yes", "on"):
    from api.scheduler import scheduler as cron_scheduler
    cron_scheduler.start()
    print("[main] Scheduler cron ACTIVE (SYLEA_SCHEDULER_ENABLED=true)")
else:
    print("[main] Scheduler cron INACTIF (set SYLEA_SCHEDULER_ENABLED=true pour activer)")


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Syléa.AI API",
    version="1.0.0",
    description="API REST pour l'application Syléa.AI — Votre assistant de vie augmenté.",
)


@app.on_event("shutdown")
async def _close_agent3_http_pool():
    """Ferme proprement le pool httpx partage au shutdown."""
    try:
        from api.agent3_http import close_http_client
        await close_http_client()
    except Exception:
        pass

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
app.include_router(integrations_router)
app.include_router(notifications_router)
app.include_router(shared_workspaces_router)
app.include_router(credentials_vault_router)


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


# ── Etat d'activation des agents (web -> desktop sync) ──────────────────────
#
# Les agents sont activables/desactivables depuis l'onglet "Mes agents Syléa"
# du frontend web. Cet etat est stocke en localStorage cote web. Pour que
# l'app desktop reflete ce qui se passe sur le web, on ajoute un endpoint
# leger qui :
#   - recoit un POST avec {agent2: bool, agent3: bool} depuis le web,
#   - stocke en memoire (par user_id),
#   - broadcast l'etat a toutes les sessions desktop de cet user via WS.
#
# Pas de persistance en DB necessaire : c'est juste un canal de sync entre
# 2 sessions du meme user. Au reload de l'app desktop, elle peut faire un
# GET sur le meme endpoint pour recuperer le snapshot courant.
_agents_activation_state: dict[str, dict[str, bool]] = {}


@app.post("/api/desktop/agents-activation", tags=["desktop"])
async def set_agents_activation(
    payload: dict,
    user_id: str = Depends(get_optional_user),
):
    """Le web frontend declare quels agents sont actuellement actives.
    L'etat est broadcaste a toutes les sessions desktop du meme user via WS."""
    if not user_id:
        return {"ok": False, "error": "auth_required"}
    from api.websocket import ws_manager
    # Sanitise : ne garde que agent1/agent2/agent3 boolean
    next_state = {
        "agent1": bool(payload.get("agent1", False)),
        "agent2": bool(payload.get("agent2", False)),
        "agent3": bool(payload.get("agent3", False)),
    }
    _agents_activation_state[user_id] = next_state
    # Broadcast aux sessions desktop
    await ws_manager.send_to_user(user_id, {
        "type": "agents_activation",
        "active": next_state,
    })
    return {"ok": True, "active": next_state}


@app.get("/api/desktop/agents-activation", tags=["desktop"])
async def get_agents_activation(user_id: str = Depends(get_optional_user)):
    """Retourne l'etat d'activation des agents pour l'user courant.
    Utilise par l'app desktop au boot pour afficher le bon etat initial."""
    if not user_id:
        return {"active": {"agent1": False, "agent2": False, "agent3": False}}
    return {"active": _agents_activation_state.get(user_id, {"agent1": False, "agent2": False, "agent3": False})}


# ── Ecoute active : web -> desktop bridge ──────────────────────────────────
#
# La feature "Ecoute active" (cours univ/prepa) vit dans l'app desktop
# (cpal natif Rust, recording 4h+, wake lock, faster-whisper local). Le
# bouton sur le web (Agent 2) n'est qu'un trigger : on broadcast un event
# WS au desktop pour qu'il ouvre la fenetre EcouteActive.

@app.post("/api/desktop/start-lecture", tags=["desktop"])
async def start_lecture(user_id: str = Depends(get_optional_user)):
    """Web frontend declenche une session d'ecoute active sur l'app desktop."""
    if not user_id:
        return {"ok": False, "error": "auth_required"}
    from api.websocket import ws_manager
    if not ws_manager.is_connected(user_id):
        return {"ok": False, "error": "desktop_not_connected"}
    await ws_manager.send_to_user(user_id, {"type": "start_lecture"})
    return {"ok": True}


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
