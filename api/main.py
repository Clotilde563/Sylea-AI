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

import sys

from fastapi import FastAPI
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

from api.routers import profil, dilemme, historique, evenement, bilan, objectifs, service_client
from api.schemas import HealthOut


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Syléa.AI API",
    version="1.0.0",
    description="API REST pour l'application Syléa.AI — Votre assistant de vie augmenté.",
)

# CORS : autoriser le frontend React (Vite dev sur :5173, prod sur même origine)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
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


# ── Routes utilitaires ────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthOut, tags=["system"])
def health_check():
    """Liveness check — retourne 200 si l'API est opérationnelle."""
    return HealthOut(status="ok", version="1.0.0")


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
