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

import re
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, UploadFile, File, Form
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
from api.routers.pending import router as pending_router
from api.schemas import HealthOut


# ── Initialisation schema au démarrage (Alembic en PG, DDL en SQLite) ─────────
def _init_db_schema():
    """Initialise le schema DB au demarrage.

    - PostgreSQL prod : execute `alembic upgrade head` automatiquement.
    - SQLite dev      : execute les DDL idempotents (CREATE TABLE IF NOT EXISTS).

    Le choix est fait via DATABASE_URL (postgres / sqlite).
    """
    database_url = os.environ.get("DATABASE_URL", "")
    is_postgres = database_url.startswith(("postgres://", "postgresql://", "postgresql+"))

    if is_postgres:
        # PG prod : Alembic gere les migrations
        try:
            from alembic.config import Config
            from alembic import command
            alembic_cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
            alembic_cfg.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(alembic_cfg, "head")
            print("[main] Alembic: schema PostgreSQL synchronise (upgrade head)")
        except Exception as e:
            print(f"[main] Alembic upgrade failed: {e}")
    else:
        # SQLite dev : DDL idempotents
        try:
            from sylea.core.storage.database import DatabaseManager
            from api.routers.agent3_openclaw import _ensure_agent3_tables
            db = DatabaseManager()
            db.connect()
            try:
                _ensure_agent3_tables(db)
            finally:
                db.disconnect()
            print("[main] SQLite: tables Agent 3 initialisees (DDL idempotent)")
        except Exception:
            pass  # DB not available yet or import error — tables will be created on first use

_init_db_schema()

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
app.include_router(pending_router)


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


# ── Sprint 2 : Transcription incrementale (faster-whisper local) ────────────
#
# Le desktop POST chaque chunk WAV (30s, 16kHz mono PCM 16-bit) ici. On le
# sauvegarde dans un dossier temporaire user-scoped, on le passe au service
# transcription (faster-whisper "small" par defaut, override via env var
# FASTER_WHISPER_MODEL=medium pour prod prepa), et on retourne le texte +
# la langue detectee + duree.

@app.post("/api/lecture/transcribe-chunk", tags=["lecture"])
async def transcribe_chunk(
    audio: UploadFile = File(...),
    session_id: str | None = Form(None),
    chunk_index: int | None = Form(None),
    language: str | None = Form(None),  # override langue (ex: "en" pour cours d'anglais)
    user_id: str | None = Depends(get_optional_user),
):
    """Transcrit un chunk WAV envoye par l'app desktop. Retourne le texte
    + segments + langue detectee."""
    if not user_id:
        return {"ok": False, "error": "auth_required"}

    # Sauvegarde temporaire user-scoped (evite collisions entre users)
    import tempfile
    import uuid
    tmp_dir = Path(tempfile.gettempdir()) / "sylea-lecture" / user_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_session = (session_id or "anon")[:64].replace("/", "_").replace("\\", "_")
    tmp_path = tmp_dir / f"chunk_{safe_session}_{chunk_index or 0}_{uuid.uuid4().hex[:8]}.wav"

    try:
        content = await audio.read()
        tmp_path.write_bytes(content)
        print(f"[lecture] transcribe chunk {chunk_index} (session={session_id}, "
              f"size={len(content)} bytes, lang={language})")

        from api.transcription import get_transcriber
        result = get_transcriber().transcribe(tmp_path, language=language)

        text_preview = result["text"][:100] + ("..." if len(result["text"]) > 100 else "")
        print(f"[lecture]   -> ok, lang={result['language']}, "
              f"duration={result['duration_s']:.1f}s, text=\"{text_preview}\"")

        return {
            "ok": True,
            "session_id": session_id,
            "chunk_index": chunk_index,
            "text": result["text"],
            "language": result["language"],
            "language_probability": result["language_probability"],
            "duration_s": result["duration_s"],
            "segments": result["segments"],
        }
    except Exception as e:
        import traceback
        print(f"[lecture]   -> ERROR for chunk {chunk_index}: {e}")
        traceback.print_exc()
        return {"ok": False, "error": f"transcription_failed: {e}"}
    finally:
        # Cleanup : on garde pas l'audio sur le serveur (privacy)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# ── Sprint 3 : Generation de fiche + export Anki ────────────────────────────

@app.post("/api/lecture/generate-fiche", tags=["lecture"])
async def generate_fiche_endpoint(
    payload: dict,
    user_id: str | None = Depends(get_optional_user),
):
    """Genere une fiche markdown a partir d'un transcript.
    Body : { transcript, matiere?, titre?, formation?, language? }
    """
    if not user_id:
        return {"ok": False, "error": "auth_required"}
    transcript = (payload.get("transcript") or "").strip()
    if not transcript:
        return {"ok": False, "error": "transcript_required"}
    if len(transcript) > 200_000:
        return {"ok": False, "error": "transcript_too_long"}

    from api.fiche_generator import generate_fiche
    try:
        result = generate_fiche(
            transcript=transcript,
            matiere=payload.get("matiere"),
            titre=payload.get("titre"),
            formation=payload.get("formation"),
            language=payload.get("language"),
        )
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": f"fiche_generation_failed: {e}"}


@app.post("/api/lecture/generate-cards", tags=["lecture"])
async def generate_cards_endpoint(
    payload: dict,
    user_id: str | None = Depends(get_optional_user),
):
    """Genere des cartes Anki Q/A directement depuis le transcript brut
    via LLM. Bien plus pertinent que l'extraction heuristique de la fiche
    markdown (qui produit parfois des paires antinomiques).

    Body : {transcript, matiere, titre?, formation?}
    Retourne : {ok, cards: [{q, a}], used_llm: bool}
    """
    if not user_id:
        return {"ok": False, "error": "auth_required"}
    transcript = (payload.get("transcript") or "").strip()
    if not transcript:
        return {"ok": False, "error": "transcript_required"}
    if len(transcript) > 200_000:
        return {"ok": False, "error": "transcript_too_long"}

    from api.fiche_generator import generate_anki_cards
    try:
        result = generate_anki_cards(
            transcript=transcript,
            matiere=payload.get("matiere") or "autre",
            titre=payload.get("titre"),
            formation=payload.get("formation"),
        )
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": f"cards_generation_failed: {e}"}


@app.post("/api/lecture/render-html", tags=["lecture"])
async def render_fiche_html_endpoint(
    payload: dict,
    user_id: str | None = Depends(get_optional_user),
):
    """Rendu HTML standalone d'une fiche markdown (CSS embarque + KaTeX
    via CDN). Le desktop ecrit le resultat dans <session_dir>/fiche.html
    pour un double-clic propre dans Word/navigateur."""
    if not user_id:
        return {"ok": False, "error": "auth_required"}
    fiche_md = (payload.get("fiche_markdown") or "").strip()
    if not fiche_md:
        return {"ok": False, "error": "fiche_markdown_required"}
    try:
        from api.fiche_render import render_fiche_html
        html = render_fiche_html(
            fiche_markdown=fiche_md,
            titre=payload.get("titre") or "Cours",
            matiere=payload.get("matiere") or "autre",
            formation=payload.get("formation"),
            session_id=payload.get("session_id"),
            matiere_auto_detected=bool(payload.get("matiere_auto_detected")),
        )
        return {"ok": True, "html": html}
    except Exception as e:
        return {"ok": False, "error": f"html_render_failed: {e}"}


@app.post("/api/lecture/export-anki", tags=["lecture"])
async def export_anki_endpoint(
    payload: dict,
    user_id: str | None = Depends(get_optional_user),
):
    """Exporte un deck Anki .apkg.

    Body :
      - cards: [{q, a}]      → si fourni, utilise directement (LLM-generated)
      - sinon fiche_markdown → fallback heuristique extract_cards()
      - titre, matiere       → meta du deck
    Retourne le .apkg en base64 (le desktop l'ecrit via write_file_binary)."""
    if not user_id:
        return {"ok": False, "error": "auth_required"}
    titre = (payload.get("titre") or "Cours").strip()
    matiere = (payload.get("matiere") or "autre").strip()
    explicit_cards = payload.get("cards")
    fiche_md = (payload.get("fiche_markdown") or "").strip()

    if not explicit_cards and not fiche_md:
        return {"ok": False, "error": "cards_or_fiche_required"}

    # Sauve le .apkg dans tempdir/sylea-anki/<user_id>/
    import tempfile
    tmp_dir = Path(tempfile.gettempdir()) / "sylea-anki" / user_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\s-]", "_", titre)[:80].strip().replace(" ", "_") or "cours"
    out_path = tmp_dir / f"{matiere}_{safe_title}.apkg"

    from api.anki_export import build_apkg, build_apkg_from_cards
    try:
        if explicit_cards and isinstance(explicit_cards, list):
            # Sanitise + dedup
            tuples = [
                (str(c.get("q") or "").strip(), str(c.get("a") or "").strip())
                for c in explicit_cards
                if isinstance(c, dict) and c.get("q") and c.get("a")
            ]
            if not tuples:
                return {"ok": False, "error": "no_valid_cards"}
            result = build_apkg_from_cards(
                titre=titre, matiere=matiere, cards=tuples, output_path=out_path,
            )
        else:
            result = build_apkg(titre=titre, matiere=matiere,
                                fiche_markdown=fiche_md, output_path=out_path)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "apkg_build_failed")}
        # Retourne en base64 pour que le desktop puisse l'ecrire localement
        # via Tauri write_file_binary (evite de servir des download URLs).
        import base64
        data = out_path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return {
            "ok": True,
            "card_count": result["card_count"],
            "deck_name": result["deck_name"],
            "filename": out_path.name,
            "size_bytes": len(data),
            "data_base64": b64,
        }
    except Exception as e:
        return {"ok": False, "error": f"apkg_export_failed: {e}"}
    finally:
        # Cleanup
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass


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
