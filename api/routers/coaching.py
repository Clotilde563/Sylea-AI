"""
Router Coaching Proactif Vocal — Sylea.AI.

Sessions de coaching planifiees :
  - Lundi matin : motivation pour la semaine
  - Dimanche soir : revue de la semaine
  - Mensuel : bilan complet
  - Annuel : retrospective + projections

Chaque session genere du contenu IA puis du TTS (OpenAI).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from api.context_helper import build_full_user_context_async
from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coaching", tags=["coaching"])

# ── Audio directory ───────────────────────────────────────────────────────────

COACHING_AUDIO_DIR = Path("data/coaching_audio")
COACHING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# ── Pydantic schemas ─────────────────────────────────────────────────────────

class CoachingPreferencesIn(BaseModel):
    monday_enabled: Optional[int] = None
    monday_time: Optional[str] = None
    sunday_enabled: Optional[int] = None
    sunday_time: Optional[str] = None
    monthly_enabled: Optional[int] = None
    monthly_day: Optional[int] = None
    yearly_enabled: Optional[int] = None


class CoachingPreferencesOut(BaseModel):
    monday_enabled: int = 1
    monday_time: str = "08:00"
    sunday_enabled: int = 1
    sunday_time: str = "19:00"
    monthly_enabled: int = 1
    monthly_day: int = 1
    yearly_enabled: int = 1


class CoachingSessionOut(BaseModel):
    id: str
    session_type: str
    status: str
    summary: Optional[str] = None
    key_insights: Optional[list] = None
    trajectory_data: Optional[dict] = None
    audio_url: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class StartSessionIn(BaseModel):
    session_type: str = Field(..., pattern="^(monday_motivation|sunday_review|monthly_recap|yearly_recap)$")


class CompleteSessionIn(BaseModel):
    notes: str = ""


# ── Database table creation ──────────────────────────────────────────────────

def _ensure_coaching_tables(db: DatabaseManager) -> None:
    """Create coaching tables if they don't exist."""
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS coaching_preferences (
            auth_user_id TEXT PRIMARY KEY,
            monday_enabled INTEGER DEFAULT 1,
            monday_time TEXT DEFAULT '08:00',
            sunday_enabled INTEGER DEFAULT 1,
            sunday_time TEXT DEFAULT '19:00',
            monthly_enabled INTEGER DEFAULT 1,
            monthly_day INTEGER DEFAULT 1,
            yearly_enabled INTEGER DEFAULT 1,
            updated_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS coaching_sessions (
            id TEXT PRIMARY KEY,
            auth_user_id TEXT,
            session_type TEXT,
            status TEXT DEFAULT 'pending',
            summary TEXT,
            key_insights_json TEXT,
            trajectory_data_json TEXT,
            audio_url TEXT,
            started_at TEXT,
            completed_at TEXT
        )
    """)
    db.conn.commit()


# ── AI content generation ────────────────────────────────────────────────────

async def _fallback_claude_chat(system_prompt: str, messages: list[dict], model: str = "claude-sonnet-4-6", max_tokens: int = 2000) -> str:
    """Direct Claude API call for coaching content generation."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return ""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
            )
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Claude coaching API failed: {e}")
        return ""


def _build_coaching_system_prompt(session_type: str, user_name: str) -> str:
    """Build system prompt for coaching session."""
    type_labels = {
        "monday_motivation": "briefing motivationnel du lundi",
        "sunday_review": "revue du dimanche",
        "monthly_recap": "bilan mensuel",
        "yearly_recap": "retrospective annuelle",
    }
    label = type_labels.get(session_type, session_type)
    return (
        f"Tu es le coach Sylea, un mentor bienveillant mais exigeant. "
        f"Tu fais un {label} pour {user_name}. "
        f"Tu parles a la deuxieme personne du singulier (tu/toi). "
        f"Ton ton est energique, concret et positif. "
        f"Tu donnes des conseils actionnables, pas des platitudes. "
        f"Reponds en francais."
    )


def _build_coaching_user_prompt(session_type: str, user_context: str, extra_data: str = "") -> str:
    """Build user prompt based on session type."""
    prompts = {
        "monday_motivation": (
            "Genere un script de motivation de 2 minutes pour lundi matin. "
            "Rappelle les objectifs de la semaine, les sous-objectifs en cours, "
            "et donne 3 actions concretes pour aujourd'hui. "
            "Sois energisant et precis. "
            "Structure : salutation -> rappel objectif -> 3 actions -> phrase de cloture motivante."
        ),
        "sunday_review": (
            "Genere une revue de la semaine ecoulee. "
            "Analyse les decisions prises, les taches accomplies, les changements de probabilite. "
            "Donne un bilan honnete (points forts et axes d'amelioration). "
            "Propose un plan d'action pour la semaine suivante avec 3 priorites. "
            "Structure : bilan -> points forts -> axes d'amelioration -> plan semaine prochaine."
        ),
        "monthly_recap": (
            "Genere un bilan mensuel complet. "
            "Analyse les tendances du mois : evolution de la probabilite, decisions marquantes, "
            "progression des sous-objectifs, bilans quotidiens. "
            "Identifie les patterns (positifs et negatifs). "
            "Donne 5 recommandations concretes pour le mois suivant. "
            "Structure : resume du mois -> tendances -> patterns -> recommandations."
        ),
        "yearly_recap": (
            "Genere une retrospective annuelle complete. "
            "Analyse toute l'annee : evolution globale, decisions cles, moments forts et difficiles. "
            "Genere 3 scenarios realistes pour l'annee prochaine, calibres a partir des "
            "tendances reellement observees dans le profil et l'historique : "
            "1) Optimiste — si les leviers positifs identifies sont actionnes pleinement, "
            "2) Attendu — projection du rythme actuel sans changement majeur, "
            "3) Pessimiste — si les freins identifies persistent ou s'aggravent. "
            "Pour chaque scenario, estime la probabilite et decris les consequences concretes. "
            "Tu es libre de l'amplitude entre les scenarios — adapte-la aux leviers reels "
            "observes (pas de fourchette imposee).\n\n"
            "Reponds avec une section JSON a la fin au format : "
            '```json\n{"trajectory_data": {"optimistic": {"probability": X, "description": "..."}, '
            '"expected": {"probability": Y, "description": "..."}, '
            '"pessimistic": {"probability": Z, "description": "..."}}}\n```'
        ),
    }
    prompt = prompts.get(session_type, "Genere un coaching personnalise.")
    return f"{prompt}\n\nCONTEXTE UTILISATEUR :\n{user_context}\n{extra_data}"


async def _load_weekly_data_async(user_id: str, profil_id: str) -> str:
    """Async sibling : load past week data for sunday review.

    Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async — compat
    SQLite + PG.
    """
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    factory = _gsf()

    try:
        async with factory() as session:
            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT question, probabilite_avant, probabilite_apres, cree_le "
                        "FROM decisions WHERE user_id = :pid AND cree_le >= :cutoff "
                        "ORDER BY cree_le DESC"
                    ),
                    {"pid": profil_id, "cutoff": week_ago},
                )
                rows = result.mappings().all()
                if rows:
                    lines.append("\nDECISIONS CETTE SEMAINE :")
                    for r in rows:
                        pa = r["probabilite_apres"]
                        pb = r["probabilite_avant"]
                        impact = (pa - pb) if pa is not None and pb is not None else 0
                        lines.append(f"  - {r['question']} (impact: {impact:+.2f}%)")
            except Exception:
                pass

            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT date, niveau_sante, niveau_stress, niveau_energie, "
                        "niveau_bonheur, description FROM bilans_quotidiens "
                        "WHERE user_id = :pid AND cree_le >= :cutoff ORDER BY date DESC"
                    ),
                    {"pid": profil_id, "cutoff": week_ago},
                )
                rows = result.mappings().all()
                if rows:
                    lines.append("\nBILANS CETTE SEMAINE :")
                    for r in rows:
                        lines.append(
                            f"  - {r['date']}: sante={r['niveau_sante']}, "
                            f"stress={r['niveau_stress']}, energie={r['niveau_energie']}, "
                            f"bonheur={r['niveau_bonheur']}"
                        )
                        if r['description']:
                            lines.append(f"    Note: {str(r['description'])[:100]}")
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(lines)


async def _load_monthly_data_async(user_id: str, profil_id: str) -> str:
    """Async sibling : load past month aggregate stats.

    Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async — compat
    SQLite + PG.
    """
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    month_ago = (now - timedelta(days=30)).isoformat()
    factory = _gsf()

    try:
        async with factory() as session:
            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT COUNT(*) FROM decisions "
                        "WHERE user_id = :pid AND cree_le >= :cutoff"
                    ),
                    {"pid": profil_id, "cutoff": month_ago},
                )
                count = result.scalar() or 0
                lines.append(f"\nSTATISTIQUES DU MOIS : {count} decisions prises")
            except Exception:
                pass

            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT AVG(niveau_sante) AS s, AVG(niveau_stress) AS st, "
                        "AVG(niveau_energie) AS e, AVG(niveau_bonheur) AS b "
                        "FROM bilans_quotidiens WHERE user_id = :pid AND cree_le >= :cutoff"
                    ),
                    {"pid": profil_id, "cutoff": month_ago},
                )
                row = result.mappings().first()
                if row and row["s"] is not None:
                    lines.append(
                        f"  Moyennes bien-etre : sante={row['s']:.1f}, stress={row['st']:.1f}, "
                        f"energie={row['e']:.1f}, bonheur={row['b']:.1f}"
                    )
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(lines)


async def _load_yearly_data_async(user_id: str, profil_id: str) -> str:
    """Async sibling : load past year stats + sub-objectives progression.

    Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async — compat
    SQLite + PG.
    """
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    year_ago = (now - timedelta(days=365)).isoformat()
    factory = _gsf()

    try:
        async with factory() as session:
            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT COUNT(*) FROM decisions "
                        "WHERE user_id = :pid AND cree_le >= :cutoff"
                    ),
                    {"pid": profil_id, "cutoff": year_ago},
                )
                count = result.scalar() or 0
                lines.append(f"\nSTATISTIQUES ANNUELLES : {count} decisions prises")
            except Exception:
                pass

            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT date, niveau_sante, niveau_stress, niveau_energie, niveau_bonheur "
                        "FROM bilans_quotidiens WHERE user_id = :pid AND cree_le >= :cutoff "
                        "ORDER BY date"
                    ),
                    {"pid": profil_id, "cutoff": year_ago},
                )
                rows = result.mappings().all()
                if rows:
                    lines.append(f"  {len(rows)} bilans quotidiens enregistres")
                    first = rows[0]
                    last = rows[-1]
                    lines.append(
                        f"  Debut d'annee ({first['date']}): sante={first['niveau_sante']}, "
                        f"stress={first['niveau_stress']}, energie={first['niveau_energie']}, "
                        f"bonheur={first['niveau_bonheur']}"
                    )
                    lines.append(
                        f"  Aujourd'hui ({last['date']}): sante={last['niveau_sante']}, "
                        f"stress={last['niveau_stress']}, energie={last['niveau_energie']}, "
                        f"bonheur={last['niveau_bonheur']}"
                    )
            except Exception:
                pass

            try:
                result = await session.execute(
                    _sa_text(
                        "SELECT titre, progression FROM sous_objectifs "
                        "WHERE user_id = :pid ORDER BY ordre"
                    ),
                    {"pid": profil_id},
                )
                rows = result.mappings().all()
                if rows:
                    lines.append("\nPROGRESSION SOUS-OBJECTIFS :")
                    for r in rows:
                        prog = r["progression"] or 0
                        lines.append(f"  - {r['titre']}: {prog:.0f}%")
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(lines)


# ── TTS generation ────────────────────────────────────────────────────────────

async def _generate_tts_file(text: str, session_id: str, voice: str = "onyx") -> str:
    """Generate TTS audio file using OpenAI and return the file path."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return ""
    try:
        import httpx
        # Truncate to ~4000 chars for TTS (API limit)
        tts_text = text[:4000] if len(text) > 4000 else text
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "tts-1",
                    "voice": voice,
                    "input": tts_text,
                    "response_format": "mp3",
                },
                timeout=60,
            )
            if resp.status_code == 200:
                filename = f"{session_id}.mp3"
                filepath = COACHING_AUDIO_DIR / filename
                filepath.write_bytes(resp.content)
                return f"/api/coaching/audio/{filename}"
    except Exception as e:
        logger.warning(f"TTS generation failed: {e}")
    return ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/preferences", response_model=CoachingPreferencesOut)
async def get_preferences(
    db: DatabaseManager = Depends(get_db),  # garde pour _ensure_coaching_tables
    user_id: str | None = Depends(get_optional_user),
):
    """Get coaching schedule preferences.

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    NOTE : table `coaching_preferences` non encore dans le schema ORM —
    fallback gracieux si absente (retourne default).
    """
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT monday_enabled, monday_time, sunday_enabled, sunday_time, "
                    "monthly_enabled, monthly_day, yearly_enabled "
                    "FROM coaching_preferences WHERE auth_user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = result.mappings().first()
        except Exception:
            return CoachingPreferencesOut()  # table absente → default

    if not row:
        return CoachingPreferencesOut()

    return CoachingPreferencesOut(
        monday_enabled=row["monday_enabled"],
        monday_time=row["monday_time"],
        sunday_enabled=row["sunday_enabled"],
        sunday_time=row["sunday_time"],
        monthly_enabled=row["monthly_enabled"],
        monthly_day=row["monthly_day"],
        yearly_enabled=row["yearly_enabled"],
    )


@router.put("/preferences", response_model=CoachingPreferencesOut)
async def update_preferences(
    data: CoachingPreferencesIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Update coaching schedule preferences.

    Migration PG (2026-05-13) : upsert via SQLAlchemy text() async.
    SECURITE : noms de colonnes en whitelist statique pour eviter
    SQL injection (jamais derive de l'input user).
    """
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    now = datetime.now(timezone.utc).isoformat()
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()

    async with factory() as session:
        try:
            # Check existing
            result = await session.execute(
                text("SELECT 1 FROM coaching_preferences WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            existing = result.first()

            if existing:
                # UPDATE : whitelist statique des colonnes autorisees
                FIELDS = ["monday_enabled", "monday_time", "sunday_enabled",
                          "sunday_time", "monthly_enabled", "monthly_day",
                          "yearly_enabled"]
                set_clauses = []
                params: dict = {"uid": user_id, "updated_at": now}
                for field in FIELDS:
                    val = getattr(data, field)
                    if val is not None:
                        set_clauses.append(f"{field} = :{field}")
                        params[field] = val
                if set_clauses:
                    set_clauses.append("updated_at = :updated_at")
                    await session.execute(
                        text(
                            f"UPDATE coaching_preferences SET {', '.join(set_clauses)} "
                            f"WHERE auth_user_id = :uid"
                        ),
                        params,
                    )
            else:
                await session.execute(
                    text(
                        "INSERT INTO coaching_preferences "
                        "(auth_user_id, monday_enabled, monday_time, sunday_enabled, "
                        "sunday_time, monthly_enabled, monthly_day, yearly_enabled, updated_at) "
                        "VALUES (:uid, :me, :mt, :se, :st, :mone, :mond, :ye, :updated_at)"
                    ),
                    {
                        "uid": user_id,
                        "me": data.monday_enabled if data.monday_enabled is not None else 1,
                        "mt": data.monday_time or "08:00",
                        "se": data.sunday_enabled if data.sunday_enabled is not None else 1,
                        "st": data.sunday_time or "19:00",
                        "mone": data.monthly_enabled if data.monthly_enabled is not None else 1,
                        "mond": data.monthly_day if data.monthly_day is not None else 1,
                        "ye": data.yearly_enabled if data.yearly_enabled is not None else 1,
                        "updated_at": now,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return await get_preferences(db=db, user_id=user_id)


@router.get("/sessions", response_model=List[CoachingSessionOut])
async def list_sessions(
    db: DatabaseManager = Depends(get_db),  # garde pour _ensure_coaching_tables
    user_id: str | None = Depends(get_optional_user),
):
    """List past coaching sessions (limit 20).

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, session_type, status, summary, key_insights_json, "
                    "trajectory_data_json, audio_url, started_at, completed_at "
                    "FROM coaching_sessions WHERE auth_user_id = :uid "
                    "ORDER BY started_at DESC LIMIT 20"
                ),
                {"uid": user_id},
            )
            rows = result.mappings().all()
        except Exception:
            return []

    results = []
    for r in rows:
        insights = None
        trajectory = None
        try:
            if r["key_insights_json"]:
                insights = json.loads(r["key_insights_json"])
        except Exception:
            pass
        try:
            if r["trajectory_data_json"]:
                trajectory = json.loads(r["trajectory_data_json"])
        except Exception:
            pass
        results.append(CoachingSessionOut(
            id=r["id"],
            session_type=r["session_type"],
            status=r["status"],
            summary=r["summary"],
            key_insights=insights,
            trajectory_data=trajectory,
            audio_url=r["audio_url"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
        ))
    return results


@router.get("/sessions/pending")
async def check_pending_session(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Check if any coaching session is due right now based on preferences.

    Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async.
    """
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()

    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT monday_enabled, monday_time, sunday_enabled, sunday_time, "
                "monthly_enabled, monthly_day, yearly_enabled "
                "FROM coaching_preferences WHERE auth_user_id = :uid"
            ),
            {"uid": user_id},
        )
        prefs_row = result.mappings().first()

        prefs = (
            (prefs_row["monday_enabled"], prefs_row["monday_time"],
             prefs_row["sunday_enabled"], prefs_row["sunday_time"],
             prefs_row["monthly_enabled"], prefs_row["monthly_day"],
             prefs_row["yearly_enabled"])
            if prefs_row else (1, "08:00", 1, "19:00", 1, 1, 1)
        )

        now = datetime.now()
        day_of_week = now.weekday()  # 0=Monday, 6=Sunday
        current_time = now.strftime("%H:%M")
        day_of_month = now.day
        month = now.month

        pending = []

        async def _check_done(session_type: str, like_pattern: str) -> bool:
            r = await session.execute(
                text(
                    "SELECT 1 FROM coaching_sessions WHERE auth_user_id = :uid "
                    "AND session_type = :stype AND started_at LIKE :pat"
                ),
                {"uid": user_id, "stype": session_type, "pat": like_pattern},
            )
            return r.first() is not None

        # Monday motivation
        if day_of_week == 0 and prefs[0] == 1 and current_time >= prefs[1]:
            today = now.strftime("%Y-%m-%d")
            if not await _check_done("monday_motivation", f"{today}%"):
                pending.append("monday_motivation")

        # Sunday review
        if day_of_week == 6 and prefs[2] == 1 and current_time >= prefs[3]:
            today = now.strftime("%Y-%m-%d")
            if not await _check_done("sunday_review", f"{today}%"):
                pending.append("sunday_review")

        # Monthly recap
        if day_of_month == prefs[5] and prefs[4] == 1:
            month_str = now.strftime("%Y-%m")
            if not await _check_done("monthly_recap", f"{month_str}%"):
                pending.append("monthly_recap")

        # Yearly recap (January 1st)
        if month == 1 and day_of_month == 1 and prefs[6] == 1:
            year_str = now.strftime("%Y")
            if not await _check_done("yearly_recap", f"{year_str}%"):
                pending.append("yearly_recap")

    return {"pending": pending, "count": len(pending)}


@router.post("/sessions/start", response_model=CoachingSessionOut)
async def start_session(
    data: StartSessionIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Start a coaching session and generate AI content."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    # Load user profile
    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(404, "Profil introuvable")
    profil = repo.charger(auth_user_id=user_id)

    # Build context
    user_context = await build_full_user_context_async(
        db=db, user_id=user_id, profil=profil,
        include_collected_info=True, include_decisions=True,
        include_sous_objectifs=True, max_decisions=20,
    )

    # Load extra data based on session type.
    # Migration PG (2026-05-13) : utilise les async siblings.
    extra_data = ""
    if data.session_type == "sunday_review":
        extra_data = await _load_weekly_data_async(user_id, profil.id)
    elif data.session_type == "monthly_recap":
        extra_data = await _load_monthly_data_async(user_id, profil.id)
    elif data.session_type == "yearly_recap":
        extra_data = await _load_yearly_data_async(user_id, profil.id)

    # Generate AI content
    system_prompt = _build_coaching_system_prompt(data.session_type, profil.nom)
    user_prompt = _build_coaching_user_prompt(data.session_type, user_context, extra_data)

    content = await _fallback_claude_chat(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=2000,
    )

    if not content:
        content = (
            f"Session de coaching {data.session_type} pour {profil.nom}. "
            "Le service IA est temporairement indisponible. "
            "Reessayez dans quelques instants."
        )

    # Extract trajectory data for yearly recap
    trajectory_data = None
    if data.session_type == "yearly_recap" and "```json" in content:
        try:
            json_match = content.split("```json")[1].split("```")[0].strip()
            parsed = json.loads(json_match)
            trajectory_data = parsed.get("trajectory_data", parsed)
            # Remove JSON block from summary
            content = content.split("```json")[0].strip()
        except Exception:
            pass

    # Extract key insights (first 5 bullet points or numbered items)
    key_insights = []
    for line in content.split("\n"):
        line = line.strip()
        if (line.startswith("- ") or line.startswith("* ") or
                (len(line) > 2 and line[0].isdigit() and line[1] in ".)")):
            key_insights.append(line.lstrip("-*0123456789.) ").strip())
            if len(key_insights) >= 5:
                break

    # Save session (Migration PG : INSERT via SQLAlchemy text() async)
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as _session:
        try:
            await _session.execute(
                text(
                    "INSERT INTO coaching_sessions "
                    "(id, auth_user_id, session_type, status, summary, key_insights_json, "
                    "trajectory_data_json, started_at) "
                    "VALUES (:id, :uid, :stype, 'active', :summary, :insights, :traj, :started_at)"
                ),
                {
                    "id": session_id,
                    "uid": user_id,
                    "stype": data.session_type,
                    "summary": content,
                    "insights": (json.dumps(key_insights, ensure_ascii=False)
                                 if key_insights else None),
                    "traj": (json.dumps(trajectory_data, ensure_ascii=False)
                             if trajectory_data else None),
                    "started_at": now,
                },
            )
            await _session.commit()
        except Exception:
            await _session.rollback()
            raise

    return CoachingSessionOut(
        id=session_id,
        session_type=data.session_type,
        status="active",
        summary=content,
        key_insights=key_insights or None,
        trajectory_data=trajectory_data,
        started_at=now,
    )


@router.post("/sessions/{session_id}/tts")
async def generate_session_tts(
    session_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Generate TTS audio for a coaching session.

    Migration PG (2026-05-13) : SELECT + UPDATE via SQLAlchemy text() async.
    """
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    from sqlalchemy import text as _sql_text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as _session:
        result = await _session.execute(
            _sql_text(
                "SELECT summary FROM coaching_sessions "
                "WHERE id = :sid AND auth_user_id = :uid"
            ),
            {"sid": session_id, "uid": user_id},
        )
        row = result.mappings().first()
    if not row:
        raise HTTPException(404, "Session introuvable")

    tts_text = row["summary"] or ""
    if not tts_text:
        raise HTTPException(400, "Pas de contenu a convertir en audio")

    audio_url = await _generate_tts_file(tts_text, session_id)
    if not audio_url:
        raise HTTPException(500, "Echec de la generation TTS")

    async with factory() as _session2:
        try:
            await _session2.execute(
                _sql_text(
                    "UPDATE coaching_sessions SET audio_url = :url WHERE id = :sid"
                ),
                {"url": audio_url, "sid": session_id},
            )
            await _session2.commit()
        except Exception:
            await _session2.rollback()
            raise

    return {"audio_url": audio_url}


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve a coaching audio file."""
    filepath = COACHING_AUDIO_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Fichier audio introuvable")
    return FileResponse(str(filepath), media_type="audio/mpeg")


@router.post("/sessions/{session_id}/complete", response_model=CoachingSessionOut)
async def complete_session(
    session_id: str,
    data: CompleteSessionIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Mark a coaching session as completed with optional user notes.

    Migration PG (2026-05-13) : SELECT + UPDATE via SQLAlchemy text() async,
    dans une seule transaction.
    """
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    now = datetime.now(timezone.utc).isoformat()

    async with factory() as _session:
        try:
            result = await _session.execute(
                text(
                    "SELECT id, session_type, status, summary, key_insights_json, "
                    "trajectory_data_json, audio_url, started_at "
                    "FROM coaching_sessions WHERE id = :sid AND auth_user_id = :uid"
                ),
                {"sid": session_id, "uid": user_id},
            )
            row = result.mappings().first()
            if not row:
                raise HTTPException(404, "Session introuvable")

            # Append user notes to summary if provided
            summary = row["summary"] or ""
            if data.notes:
                summary += f"\n\n--- Notes de l'utilisateur ---\n{data.notes}"

            await _session.execute(
                text(
                    "UPDATE coaching_sessions SET status = 'completed', "
                    "summary = :summary, completed_at = :completed_at WHERE id = :sid"
                ),
                {"summary": summary, "completed_at": now, "sid": session_id},
            )
            await _session.commit()
        except HTTPException:
            await _session.rollback()
            raise
        except Exception:
            await _session.rollback()
            raise

    insights = None
    trajectory = None
    try:
        if row["key_insights_json"]:
            insights = json.loads(row["key_insights_json"])
    except Exception:
        pass
    try:
        if row["trajectory_data_json"]:
            trajectory = json.loads(row["trajectory_data_json"])
    except Exception:
        pass

    return CoachingSessionOut(
        id=session_id,
        session_type=row["session_type"],
        status="completed",
        summary=summary,
        key_insights=insights,
        trajectory_data=trajectory,
        audio_url=row["audio_url"],
        started_at=row["started_at"],
        completed_at=now,
    )
