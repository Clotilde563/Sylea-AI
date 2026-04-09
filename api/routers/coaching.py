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

from api.context_helper import build_full_user_context
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

async def _fallback_claude_chat(system_prompt: str, messages: list[dict], model: str = "claude-sonnet-4-20250514", max_tokens: int = 2000) -> str:
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
                system=system_prompt,
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
            "Genere 3 scenarios pour l'annee prochaine : "
            "1) Optimiste (si tout va bien, +20% effort), "
            "2) Attendu (rythme actuel), "
            "3) Pessimiste (si relachement, -20% effort). "
            "Pour chaque scenario, donne une probabilite estimee et les consequences. "
            "Reponds avec une section JSON a la fin au format : "
            '```json\n{"trajectory_data": {"optimistic": {"probability": X, "description": "..."}, '
            '"expected": {"probability": Y, "description": "..."}, '
            '"pessimistic": {"probability": Z, "description": "..."}}}\n```'
        ),
    }
    prompt = prompts.get(session_type, "Genere un coaching personnalise.")
    return f"{prompt}\n\nCONTEXTE UTILISATEUR :\n{user_context}\n{extra_data}"


def _load_weekly_data(db: DatabaseManager, user_id: str, profil_id: str) -> str:
    """Load data from the past week for sunday review."""
    lines = []
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()

    # Recent decisions
    try:
        rows = db.conn.execute(
            "SELECT question, probabilite_avant, probabilite_apres, cree_le FROM decisions "
            "WHERE user_id = ? AND cree_le >= ? ORDER BY cree_le DESC",
            (profil_id, week_ago),
        ).fetchall()
        if rows:
            lines.append("\nDECISIONS CETTE SEMAINE :")
            for r in rows:
                impact = (r[2] - r[1]) if r[2] is not None else 0
                lines.append(f"  - {r[0]} (impact: {impact:+.2f}%)")
    except Exception:
        pass

    # Recent bilans
    try:
        rows = db.conn.execute(
            "SELECT date, niveau_sante, niveau_stress, niveau_energie, niveau_bonheur, description "
            "FROM bilans_quotidiens WHERE user_id = ? AND cree_le >= ? ORDER BY date DESC",
            (profil_id, week_ago),
        ).fetchall()
        if rows:
            lines.append("\nBILANS CETTE SEMAINE :")
            for r in rows:
                lines.append(f"  - {r[0]}: sante={r[1]}, stress={r[2]}, energie={r[3]}, bonheur={r[4]}")
                if r[5]:
                    lines.append(f"    Note: {r[5][:100]}")
    except Exception:
        pass

    return "\n".join(lines)


def _load_monthly_data(db: DatabaseManager, user_id: str, profil_id: str) -> str:
    """Load data from the past month."""
    lines = []
    now = datetime.now(timezone.utc)
    month_ago = (now - timedelta(days=30)).isoformat()

    try:
        count = db.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE user_id = ? AND cree_le >= ?",
            (profil_id, month_ago),
        ).fetchone()[0]
        lines.append(f"\nSTATISTIQUES DU MOIS : {count} decisions prises")
    except Exception:
        pass

    try:
        rows = db.conn.execute(
            "SELECT AVG(niveau_sante), AVG(niveau_stress), AVG(niveau_energie), AVG(niveau_bonheur) "
            "FROM bilans_quotidiens WHERE user_id = ? AND cree_le >= ?",
            (profil_id, month_ago),
        ).fetchone()
        if rows and rows[0] is not None:
            lines.append(
                f"  Moyennes bien-etre : sante={rows[0]:.1f}, stress={rows[1]:.1f}, "
                f"energie={rows[2]:.1f}, bonheur={rows[3]:.1f}"
            )
    except Exception:
        pass

    return "\n".join(lines)


def _load_yearly_data(db: DatabaseManager, user_id: str, profil_id: str) -> str:
    """Load data from the past year."""
    lines = []
    now = datetime.now(timezone.utc)
    year_ago = (now - timedelta(days=365)).isoformat()

    try:
        count = db.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE user_id = ? AND cree_le >= ?",
            (profil_id, year_ago),
        ).fetchone()[0]
        lines.append(f"\nSTATISTIQUES ANNUELLES : {count} decisions prises")
    except Exception:
        pass

    try:
        rows = db.conn.execute(
            "SELECT date, niveau_sante, niveau_stress, niveau_energie, niveau_bonheur "
            "FROM bilans_quotidiens WHERE user_id = ? AND cree_le >= ? ORDER BY date",
            (profil_id, year_ago),
        ).fetchall()
        if rows:
            lines.append(f"  {len(rows)} bilans quotidiens enregistres")
            # First and last scores for trend
            first = rows[0]
            last = rows[-1]
            lines.append(f"  Debut d'annee ({first[0]}): sante={first[1]}, stress={first[2]}, energie={first[3]}, bonheur={first[4]}")
            lines.append(f"  Aujourd'hui ({last[0]}): sante={last[1]}, stress={last[2]}, energie={last[3]}, bonheur={last[4]}")
    except Exception:
        pass

    # Sub-objectives progression
    try:
        rows = db.conn.execute(
            "SELECT titre, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
            (profil_id,),
        ).fetchall()
        if rows:
            lines.append("\nPROGRESSION SOUS-OBJECTIFS :")
            for r in rows:
                lines.append(f"  - {r[0]}: {r[1]:.0f}%")
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
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Get coaching schedule preferences."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT monday_enabled, monday_time, sunday_enabled, sunday_time, "
        "monthly_enabled, monthly_day, yearly_enabled "
        "FROM coaching_preferences WHERE auth_user_id = ?",
        (user_id,),
    ).fetchone()

    if not row:
        return CoachingPreferencesOut()

    return CoachingPreferencesOut(
        monday_enabled=row[0],
        monday_time=row[1],
        sunday_enabled=row[2],
        sunday_time=row[3],
        monthly_enabled=row[4],
        monthly_day=row[5],
        yearly_enabled=row[6],
    )


@router.put("/preferences", response_model=CoachingPreferencesOut)
async def update_preferences(
    data: CoachingPreferencesIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Update coaching schedule preferences."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    now = datetime.now(timezone.utc).isoformat()

    # Upsert
    existing = db.conn.execute(
        "SELECT 1 FROM coaching_preferences WHERE auth_user_id = ?", (user_id,)
    ).fetchone()

    if existing:
        updates = []
        values = []
        for field in ["monday_enabled", "monday_time", "sunday_enabled", "sunday_time",
                      "monthly_enabled", "monthly_day", "yearly_enabled"]:
            val = getattr(data, field)
            if val is not None:
                updates.append(f"{field} = ?")
                values.append(val)
        if updates:
            updates.append("updated_at = ?")
            values.append(now)
            values.append(user_id)
            db.conn.execute(
                f"UPDATE coaching_preferences SET {', '.join(updates)} WHERE auth_user_id = ?",
                values,
            )
    else:
        db.conn.execute(
            "INSERT INTO coaching_preferences "
            "(auth_user_id, monday_enabled, monday_time, sunday_enabled, sunday_time, "
            "monthly_enabled, monthly_day, yearly_enabled, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                data.monday_enabled if data.monday_enabled is not None else 1,
                data.monday_time or "08:00",
                data.sunday_enabled if data.sunday_enabled is not None else 1,
                data.sunday_time or "19:00",
                data.monthly_enabled if data.monthly_enabled is not None else 1,
                data.monthly_day if data.monthly_day is not None else 1,
                data.yearly_enabled if data.yearly_enabled is not None else 1,
                now,
            ),
        )
    db.conn.commit()

    return await get_preferences(db=db, user_id=user_id)


@router.get("/sessions", response_model=List[CoachingSessionOut])
async def list_sessions(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List past coaching sessions (limit 20)."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    rows = db.conn.execute(
        "SELECT id, session_type, status, summary, key_insights_json, "
        "trajectory_data_json, audio_url, started_at, completed_at "
        "FROM coaching_sessions WHERE auth_user_id = ? "
        "ORDER BY started_at DESC LIMIT 20",
        (user_id,),
    ).fetchall()

    results = []
    for r in rows:
        insights = None
        trajectory = None
        try:
            if r[4]:
                insights = json.loads(r[4])
        except Exception:
            pass
        try:
            if r[5]:
                trajectory = json.loads(r[5])
        except Exception:
            pass
        results.append(CoachingSessionOut(
            id=r[0],
            session_type=r[1],
            status=r[2],
            summary=r[3],
            key_insights=insights,
            trajectory_data=trajectory,
            audio_url=r[6],
            started_at=r[7],
            completed_at=r[8],
        ))
    return results


@router.get("/sessions/pending")
async def check_pending_session(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Check if any coaching session is due right now based on preferences."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    prefs = db.conn.execute(
        "SELECT monday_enabled, monday_time, sunday_enabled, sunday_time, "
        "monthly_enabled, monthly_day, yearly_enabled "
        "FROM coaching_preferences WHERE auth_user_id = ?",
        (user_id,),
    ).fetchone()

    if not prefs:
        prefs = (1, "08:00", 1, "19:00", 1, 1, 1)

    now = datetime.now()
    day_of_week = now.weekday()  # 0=Monday, 6=Sunday
    current_time = now.strftime("%H:%M")
    day_of_month = now.day
    month = now.month

    pending = []

    # Monday motivation
    if day_of_week == 0 and prefs[0] == 1 and current_time >= prefs[1]:
        # Check if already done today
        today = now.strftime("%Y-%m-%d")
        done = db.conn.execute(
            "SELECT 1 FROM coaching_sessions WHERE auth_user_id = ? "
            "AND session_type = 'monday_motivation' AND started_at LIKE ?",
            (user_id, f"{today}%"),
        ).fetchone()
        if not done:
            pending.append("monday_motivation")

    # Sunday review
    if day_of_week == 6 and prefs[2] == 1 and current_time >= prefs[3]:
        today = now.strftime("%Y-%m-%d")
        done = db.conn.execute(
            "SELECT 1 FROM coaching_sessions WHERE auth_user_id = ? "
            "AND session_type = 'sunday_review' AND started_at LIKE ?",
            (user_id, f"{today}%"),
        ).fetchone()
        if not done:
            pending.append("sunday_review")

    # Monthly recap (on the configured day)
    if day_of_month == prefs[5] and prefs[4] == 1:
        month_str = now.strftime("%Y-%m")
        done = db.conn.execute(
            "SELECT 1 FROM coaching_sessions WHERE auth_user_id = ? "
            "AND session_type = 'monthly_recap' AND started_at LIKE ?",
            (user_id, f"{month_str}%"),
        ).fetchone()
        if not done:
            pending.append("monthly_recap")

    # Yearly recap (January 1st)
    if month == 1 and day_of_month == 1 and prefs[6] == 1:
        year_str = now.strftime("%Y")
        done = db.conn.execute(
            "SELECT 1 FROM coaching_sessions WHERE auth_user_id = ? "
            "AND session_type = 'yearly_recap' AND started_at LIKE ?",
            (user_id, f"{year_str}%"),
        ).fetchone()
        if not done:
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
    user_context = build_full_user_context(
        db=db, user_id=user_id, profil=profil,
        include_collected_info=True, include_decisions=True,
        include_sous_objectifs=True, max_decisions=20,
    )

    # Load extra data based on session type
    extra_data = ""
    if data.session_type == "sunday_review":
        extra_data = _load_weekly_data(db, user_id, profil.id)
    elif data.session_type == "monthly_recap":
        extra_data = _load_monthly_data(db, user_id, profil.id)
    elif data.session_type == "yearly_recap":
        extra_data = _load_yearly_data(db, user_id, profil.id)

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

    # Save session
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    db.conn.execute(
        "INSERT INTO coaching_sessions "
        "(id, auth_user_id, session_type, status, summary, key_insights_json, "
        "trajectory_data_json, started_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, ?, ?)",
        (
            session_id,
            user_id,
            data.session_type,
            content,
            json.dumps(key_insights, ensure_ascii=False) if key_insights else None,
            json.dumps(trajectory_data, ensure_ascii=False) if trajectory_data else None,
            now,
        ),
    )
    db.conn.commit()

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
    """Generate TTS audio for a coaching session."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT summary FROM coaching_sessions WHERE id = ? AND auth_user_id = ?",
        (session_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session introuvable")

    text = row[0] or ""
    if not text:
        raise HTTPException(400, "Pas de contenu a convertir en audio")

    audio_url = await _generate_tts_file(text, session_id)
    if not audio_url:
        raise HTTPException(500, "Echec de la generation TTS")

    db.conn.execute(
        "UPDATE coaching_sessions SET audio_url = ? WHERE id = ?",
        (audio_url, session_id),
    )
    db.conn.commit()

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
    """Mark a coaching session as completed with optional user notes."""
    _ensure_coaching_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT id, session_type, status, summary, key_insights_json, "
        "trajectory_data_json, audio_url, started_at "
        "FROM coaching_sessions WHERE id = ? AND auth_user_id = ?",
        (session_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session introuvable")

    now = datetime.now(timezone.utc).isoformat()

    # Append user notes to summary if provided
    summary = row[3] or ""
    if data.notes:
        summary += f"\n\n--- Notes de l'utilisateur ---\n{data.notes}"

    db.conn.execute(
        "UPDATE coaching_sessions SET status = 'completed', summary = ?, completed_at = ? "
        "WHERE id = ?",
        (summary, now, session_id),
    )
    db.conn.commit()

    insights = None
    trajectory = None
    try:
        if row[4]:
            insights = json.loads(row[4])
    except Exception:
        pass
    try:
        if row[5]:
            trajectory = json.loads(row[5])
    except Exception:
        pass

    return CoachingSessionOut(
        id=session_id,
        session_type=row[1],
        status="completed",
        summary=summary,
        key_insights=insights,
        trajectory_data=trajectory,
        audio_url=row[6],
        started_at=row[7],
        completed_at=now,
    )
