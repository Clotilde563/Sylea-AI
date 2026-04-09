"""
Router Sylea Network (Communaute) — Sylea.AI.

Fonctionnalites sociales :
  - Profils communautaires
  - Decouverte et connexions
  - Mentorat
  - Challenges communautaires
  - Timeline de victoires

Prefix : /api/network
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager

router = APIRouter(prefix="/api/network", tags=["network"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class CommunityProfileIn(BaseModel):
    display_name: str = ""
    bio: str = ""
    objective_summary: str = ""
    visibility: str = "public"
    mentor_available: int = 0


class CommunityProfileOut(BaseModel):
    auth_user_id: str
    display_name: str = ""
    bio: str = ""
    objective_summary: str = ""
    objective_category: str = ""
    probability_current: float = 0.0
    visibility: str = "public"
    mentor_available: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConnectionOut(BaseModel):
    id: str
    requester_id: str
    receiver_id: str
    status: str
    created_at: str
    updated_at: Optional[str] = None
    display_name: Optional[str] = None


class ChallengeOut(BaseModel):
    id: str
    title: str
    description: str
    category: str
    start_date: str
    end_date: str
    rules: Optional[list] = None
    created_at: str
    participant_count: int = 0


class ChallengeDetailOut(ChallengeOut):
    leaderboard: List[dict] = []


class ChallengeParticipantOut(BaseModel):
    id: str
    challenge_id: str
    auth_user_id: str
    display_name: str = ""
    progress: float = 0.0
    joined_at: str


class ProgressIn(BaseModel):
    progress: float = Field(ge=0, le=100)


class VictoryIn(BaseModel):
    title: str
    description: str = ""
    category: str = ""
    is_public: int = 1


class VictoryOut(BaseModel):
    id: str
    auth_user_id: str
    display_name: str = ""
    title: str
    description: str = ""
    category: str = ""
    is_public: int = 1
    reactions_count: int = 0
    created_at: str


class ReactionIn(BaseModel):
    reaction_type: str = "celebrate"


class MentoringRequestIn(BaseModel):
    mentor_id: str
    message: str = ""


class MentoringOut(BaseModel):
    id: str
    mentor_id: str
    mentee_id: str
    mentor_name: str = ""
    mentee_name: str = ""
    status: str
    message: str = ""
    created_at: str
    updated_at: Optional[str] = None


# ── Database table creation ──────────────────────────────────────────────────

_DEFAULT_CHALLENGES = [
    {
        "title": "30 jours de discipline",
        "description": "Maintiens une routine quotidienne stricte pendant 30 jours : reveil a la meme heure, bilans quotidiens, et progres sur ton objectif chaque jour.",
        "category": "general",
    },
    {
        "title": "Semaine sans distraction",
        "description": "7 jours sans reseaux sociaux, sans Netflix, sans distractions. Concentre-toi uniquement sur ton objectif de vie.",
        "category": "productivite",
    },
    {
        "title": "Objectif fitness 30 jours",
        "description": "30 minutes d'exercice physique chaque jour pendant 30 jours. Course, musculation, yoga... choisis ta discipline.",
        "category": "sante",
    },
]


def _ensure_network_tables(db: DatabaseManager) -> None:
    """Create network tables if they don't exist."""
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS community_profiles (
            auth_user_id TEXT PRIMARY KEY,
            display_name TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            objective_summary TEXT DEFAULT '',
            objective_category TEXT DEFAULT '',
            probability_current REAL DEFAULT 0.0,
            visibility TEXT DEFAULT 'public',
            mentor_available INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY,
            requester_id TEXT NOT NULL,
            receiver_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS challenges (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            start_date TEXT,
            end_date TEXT,
            rules_json TEXT,
            created_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS challenge_participants (
            id TEXT PRIMARY KEY,
            challenge_id TEXT NOT NULL,
            auth_user_id TEXT NOT NULL,
            progress REAL DEFAULT 0.0,
            joined_at TEXT,
            updated_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS victories (
            id TEXT PRIMARY KEY,
            auth_user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            is_public INTEGER DEFAULT 1,
            reactions_count INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS victory_reactions (
            id TEXT PRIMARY KEY,
            victory_id TEXT NOT NULL,
            reactor_id TEXT NOT NULL,
            reaction_type TEXT DEFAULT 'celebrate',
            created_at TEXT
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS mentoring_relationships (
            id TEXT PRIMARY KEY,
            mentor_id TEXT NOT NULL,
            mentee_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            message TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    db.conn.commit()

    # Seed default challenges if table is empty
    count = db.conn.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        for ch in _DEFAULT_CHALLENGES:
            # 30-day challenges starting today
            start = datetime.now(timezone.utc)
            end = start + timedelta(days=30)
            db.conn.execute(
                "INSERT INTO challenges (id, title, description, category, start_date, end_date, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    ch["title"],
                    ch["description"],
                    ch["category"],
                    start.strftime("%Y-%m-%d"),
                    end.strftime("%Y-%m-%d"),
                    now,
                ),
            )
        db.conn.commit()


# ── Helper ────────────────────────────────────────────────────────────────────

def _sync_profile_from_sylea(db: DatabaseManager, user_id: str) -> None:
    """Sync objective_category and probability_current from profil_utilisateur."""
    try:
        row = db.conn.execute(
            "SELECT objectif_categorie, probabilite_actuelle, objectif_description "
            "FROM profil_utilisateur WHERE auth_user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            db.conn.execute(
                "UPDATE community_profiles SET objective_category = ?, probability_current = ? "
                "WHERE auth_user_id = ?",
                (row[0] or "", row[1] or 0.0, user_id),
            )
            db.conn.commit()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNITY PROFILE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/profile", response_model=CommunityProfileOut)
async def get_own_profile(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Get own community profile."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
        "probability_current, visibility, mentor_available, created_at, updated_at "
        "FROM community_profiles WHERE auth_user_id = ?",
        (user_id,),
    ).fetchone()

    if not row:
        raise HTTPException(404, "Profil communautaire non cree")

    return CommunityProfileOut(
        auth_user_id=row[0], display_name=row[1], bio=row[2],
        objective_summary=row[3], objective_category=row[4],
        probability_current=row[5], visibility=row[6],
        mentor_available=row[7], created_at=row[8], updated_at=row[9],
    )


@router.put("/profile", response_model=CommunityProfileOut)
async def upsert_profile(
    data: CommunityProfileIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Create or update community profile."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    now = datetime.now(timezone.utc).isoformat()
    existing = db.conn.execute(
        "SELECT 1 FROM community_profiles WHERE auth_user_id = ?", (user_id,)
    ).fetchone()

    if existing:
        db.conn.execute(
            "UPDATE community_profiles SET display_name = ?, bio = ?, objective_summary = ?, "
            "visibility = ?, mentor_available = ?, updated_at = ? WHERE auth_user_id = ?",
            (data.display_name, data.bio, data.objective_summary,
             data.visibility, data.mentor_available, now, user_id),
        )
    else:
        db.conn.execute(
            "INSERT INTO community_profiles "
            "(auth_user_id, display_name, bio, objective_summary, visibility, "
            "mentor_available, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, data.display_name, data.bio, data.objective_summary,
             data.visibility, data.mentor_available, now, now),
        )
    db.conn.commit()

    # Sync from main profile
    _sync_profile_from_sylea(db, user_id)

    return await get_own_profile(db=db, user_id=user_id)


@router.get("/profile/{target_user_id}", response_model=CommunityProfileOut)
async def get_public_profile(
    target_user_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Get someone's public profile."""
    _ensure_network_tables(db)

    row = db.conn.execute(
        "SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
        "probability_current, visibility, mentor_available, created_at, updated_at "
        "FROM community_profiles WHERE auth_user_id = ? AND visibility = 'public'",
        (target_user_id,),
    ).fetchone()

    if not row:
        raise HTTPException(404, "Profil introuvable ou prive")

    return CommunityProfileOut(
        auth_user_id=row[0], display_name=row[1], bio=row[2],
        objective_summary=row[3], objective_category=row[4],
        probability_current=row[5], visibility=row[6],
        mentor_available=row[7], created_at=row[8], updated_at=row[9],
    )


# ══════════════════════════════════════════════════════════════════════════════
# DISCOVERY & CONNECTIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/discover", response_model=List[CommunityProfileOut])
async def discover_users(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Discover users with similar objectives."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    # Sync own profile first
    _sync_profile_from_sylea(db, user_id)

    # Get own category and probability
    own = db.conn.execute(
        "SELECT objective_category, probability_current FROM community_profiles WHERE auth_user_id = ?",
        (user_id,),
    ).fetchone()

    own_cat = own[0] if own else ""
    own_prob = own[1] if own else 0.0

    # Get connected user IDs to exclude
    connected_ids = set()
    connected_ids.add(user_id)
    rows = db.conn.execute(
        "SELECT requester_id, receiver_id FROM connections "
        "WHERE (requester_id = ? OR receiver_id = ?) AND status IN ('pending', 'accepted')",
        (user_id, user_id),
    ).fetchall()
    for r in rows:
        connected_ids.add(r[0])
        connected_ids.add(r[1])

    # Fetch public profiles, excluding connected
    placeholders = ",".join("?" for _ in connected_ids)
    all_profiles = db.conn.execute(
        f"SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
        f"probability_current, visibility, mentor_available, created_at, updated_at "
        f"FROM community_profiles WHERE visibility = 'public' "
        f"AND auth_user_id NOT IN ({placeholders}) "
        f"ORDER BY CASE WHEN objective_category = ? THEN 0 ELSE 1 END, "
        f"ABS(probability_current - ?) ASC "
        f"LIMIT 20",
        (*connected_ids, own_cat, own_prob),
    ).fetchall()

    return [
        CommunityProfileOut(
            auth_user_id=r[0], display_name=r[1], bio=r[2],
            objective_summary=r[3], objective_category=r[4],
            probability_current=r[5], visibility=r[6],
            mentor_available=r[7], created_at=r[8], updated_at=r[9],
        )
        for r in all_profiles
    ]


@router.post("/connect/{target_user_id}")
async def send_connection_request(
    target_user_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Send a connection request."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")
    if user_id == target_user_id:
        raise HTTPException(400, "Impossible de se connecter a soi-meme")

    # Check if already connected or pending
    existing = db.conn.execute(
        "SELECT status FROM connections WHERE "
        "(requester_id = ? AND receiver_id = ?) OR (requester_id = ? AND receiver_id = ?)",
        (user_id, target_user_id, target_user_id, user_id),
    ).fetchone()
    if existing:
        raise HTTPException(400, f"Connexion deja existante (statut: {existing[0]})")

    conn_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO connections (id, requester_id, receiver_id, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (conn_id, user_id, target_user_id, now),
    )
    db.conn.commit()

    return {"id": conn_id, "status": "pending"}


@router.get("/connections", response_model=List[ConnectionOut])
async def list_connections(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List accepted connections."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    rows = db.conn.execute(
        "SELECT c.id, c.requester_id, c.receiver_id, c.status, c.created_at, c.updated_at, "
        "COALESCE(cp.display_name, '') "
        "FROM connections c "
        "LEFT JOIN community_profiles cp ON "
        "  CASE WHEN c.requester_id = ? THEN c.receiver_id ELSE c.requester_id END = cp.auth_user_id "
        "WHERE (c.requester_id = ? OR c.receiver_id = ?) AND c.status = 'accepted'",
        (user_id, user_id, user_id),
    ).fetchall()

    return [
        ConnectionOut(
            id=r[0], requester_id=r[1], receiver_id=r[2],
            status=r[3], created_at=r[4], updated_at=r[5],
            display_name=r[6],
        )
        for r in rows
    ]


@router.get("/connections/pending", response_model=List[ConnectionOut])
async def list_pending_connections(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List pending connection requests received."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    rows = db.conn.execute(
        "SELECT c.id, c.requester_id, c.receiver_id, c.status, c.created_at, c.updated_at, "
        "COALESCE(cp.display_name, '') "
        "FROM connections c "
        "LEFT JOIN community_profiles cp ON c.requester_id = cp.auth_user_id "
        "WHERE c.receiver_id = ? AND c.status = 'pending'",
        (user_id,),
    ).fetchall()

    return [
        ConnectionOut(
            id=r[0], requester_id=r[1], receiver_id=r[2],
            status=r[3], created_at=r[4], updated_at=r[5],
            display_name=r[6],
        )
        for r in rows
    ]


@router.put("/connections/{conn_id}/accept")
async def accept_connection(
    conn_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Accept a connection request."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT receiver_id, status FROM connections WHERE id = ?", (conn_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Connexion introuvable")
    if row[0] != user_id:
        raise HTTPException(403, "Seul le destinataire peut accepter")
    if row[1] != "pending":
        raise HTTPException(400, "Cette connexion n'est plus en attente")

    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "UPDATE connections SET status = 'accepted', updated_at = ? WHERE id = ?",
        (now, conn_id),
    )
    db.conn.commit()
    return {"status": "accepted"}


@router.put("/connections/{conn_id}/reject")
async def reject_connection(
    conn_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Reject a connection request."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT receiver_id, status FROM connections WHERE id = ?", (conn_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Connexion introuvable")
    if row[0] != user_id:
        raise HTTPException(403, "Seul le destinataire peut refuser")

    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "UPDATE connections SET status = 'rejected', updated_at = ? WHERE id = ?",
        (now, conn_id),
    )
    db.conn.commit()
    return {"status": "rejected"}


# ══════════════════════════════════════════════════════════════════════════════
# MENTORING
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/mentors", response_model=List[CommunityProfileOut])
async def list_mentors(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List available mentors (mentor_available=1, probability >= 70)."""
    _ensure_network_tables(db)

    rows = db.conn.execute(
        "SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
        "probability_current, visibility, mentor_available, created_at, updated_at "
        "FROM community_profiles "
        "WHERE mentor_available = 1 AND probability_current >= 70 AND visibility = 'public'"
        + (" AND auth_user_id != ?" if user_id else ""),
        (user_id,) if user_id else (),
    ).fetchall()

    return [
        CommunityProfileOut(
            auth_user_id=r[0], display_name=r[1], bio=r[2],
            objective_summary=r[3], objective_category=r[4],
            probability_current=r[5], visibility=r[6],
            mentor_available=r[7], created_at=r[8], updated_at=r[9],
        )
        for r in rows
    ]


@router.post("/mentoring/request", response_model=MentoringOut)
async def request_mentoring(
    data: MentoringRequestIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Request mentoring from a mentor."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")
    if user_id == data.mentor_id:
        raise HTTPException(400, "Impossible de se mentorer soi-meme")

    # Check mentor exists and is available
    mentor = db.conn.execute(
        "SELECT mentor_available, display_name FROM community_profiles WHERE auth_user_id = ?",
        (data.mentor_id,),
    ).fetchone()
    if not mentor or mentor[0] != 1:
        raise HTTPException(404, "Mentor non disponible")

    # Check for existing relationship
    existing = db.conn.execute(
        "SELECT status FROM mentoring_relationships "
        "WHERE mentor_id = ? AND mentee_id = ? AND status IN ('pending', 'active')",
        (data.mentor_id, user_id),
    ).fetchone()
    if existing:
        raise HTTPException(400, f"Relation de mentorat deja existante (statut: {existing[0]})")

    rel_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO mentoring_relationships (id, mentor_id, mentee_id, status, message, created_at) "
        "VALUES (?, ?, ?, 'pending', ?, ?)",
        (rel_id, data.mentor_id, user_id, data.message, now),
    )
    db.conn.commit()

    # Get mentee name
    mentee = db.conn.execute(
        "SELECT display_name FROM community_profiles WHERE auth_user_id = ?", (user_id,)
    ).fetchone()

    return MentoringOut(
        id=rel_id, mentor_id=data.mentor_id, mentee_id=user_id,
        mentor_name=mentor[1] or "", mentee_name=(mentee[0] if mentee else "") or "",
        status="pending", message=data.message, created_at=now,
    )


@router.get("/mentoring", response_model=List[MentoringOut])
async def list_mentoring(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List mentoring relationships (as mentor or mentee)."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    rows = db.conn.execute(
        "SELECT mr.id, mr.mentor_id, mr.mentee_id, mr.status, mr.message, "
        "mr.created_at, mr.updated_at, "
        "COALESCE(cm.display_name, ''), COALESCE(ce.display_name, '') "
        "FROM mentoring_relationships mr "
        "LEFT JOIN community_profiles cm ON mr.mentor_id = cm.auth_user_id "
        "LEFT JOIN community_profiles ce ON mr.mentee_id = ce.auth_user_id "
        "WHERE mr.mentor_id = ? OR mr.mentee_id = ? "
        "ORDER BY mr.created_at DESC",
        (user_id, user_id),
    ).fetchall()

    return [
        MentoringOut(
            id=r[0], mentor_id=r[1], mentee_id=r[2], status=r[3],
            message=r[4] or "", created_at=r[5], updated_at=r[6],
            mentor_name=r[7], mentee_name=r[8],
        )
        for r in rows
    ]


@router.put("/mentoring/{rel_id}/accept")
async def accept_mentoring(
    rel_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Mentor accepts a mentoring request."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT mentor_id, status FROM mentoring_relationships WHERE id = ?", (rel_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Relation introuvable")
    if row[0] != user_id:
        raise HTTPException(403, "Seul le mentor peut accepter")
    if row[1] != "pending":
        raise HTTPException(400, "Cette relation n'est plus en attente")

    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "UPDATE mentoring_relationships SET status = 'active', updated_at = ? WHERE id = ?",
        (now, rel_id),
    )
    db.conn.commit()
    return {"status": "active"}


@router.put("/mentoring/{rel_id}/end")
async def end_mentoring(
    rel_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """End a mentoring relationship (either party)."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT mentor_id, mentee_id FROM mentoring_relationships WHERE id = ?", (rel_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Relation introuvable")
    if user_id not in (row[0], row[1]):
        raise HTTPException(403, "Non autorise")

    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "UPDATE mentoring_relationships SET status = 'ended', updated_at = ? WHERE id = ?",
        (now, rel_id),
    )
    db.conn.commit()
    return {"status": "ended"}


# ══════════════════════════════════════════════════════════════════════════════
# CHALLENGES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/challenges", response_model=List[ChallengeOut])
async def list_challenges(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List active challenges (end_date >= today)."""
    _ensure_network_tables(db)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows = db.conn.execute(
        "SELECT c.id, c.title, c.description, c.category, c.start_date, c.end_date, "
        "c.rules_json, c.created_at, "
        "(SELECT COUNT(*) FROM challenge_participants cp WHERE cp.challenge_id = c.id) "
        "FROM challenges c WHERE c.end_date >= ? ORDER BY c.start_date",
        (today,),
    ).fetchall()

    results = []
    for r in rows:
        rules = None
        try:
            if r[6]:
                rules = json.loads(r[6])
        except Exception:
            pass
        results.append(ChallengeOut(
            id=r[0], title=r[1], description=r[2], category=r[3],
            start_date=r[4], end_date=r[5], rules=rules,
            created_at=r[7], participant_count=r[8],
        ))
    return results


@router.get("/challenges/history", response_model=List[ChallengeOut])
async def challenges_history(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List past challenges."""
    _ensure_network_tables(db)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows = db.conn.execute(
        "SELECT c.id, c.title, c.description, c.category, c.start_date, c.end_date, "
        "c.rules_json, c.created_at, "
        "(SELECT COUNT(*) FROM challenge_participants cp WHERE cp.challenge_id = c.id) "
        "FROM challenges c WHERE c.end_date < ? ORDER BY c.end_date DESC LIMIT 20",
        (today,),
    ).fetchall()

    results = []
    for r in rows:
        rules = None
        try:
            if r[6]:
                rules = json.loads(r[6])
        except Exception:
            pass
        results.append(ChallengeOut(
            id=r[0], title=r[1], description=r[2], category=r[3],
            start_date=r[4], end_date=r[5], rules=rules,
            created_at=r[7], participant_count=r[8],
        ))
    return results


@router.get("/challenges/{challenge_id}", response_model=ChallengeDetailOut)
async def get_challenge_detail(
    challenge_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Get challenge detail with leaderboard."""
    _ensure_network_tables(db)

    row = db.conn.execute(
        "SELECT id, title, description, category, start_date, end_date, rules_json, created_at "
        "FROM challenges WHERE id = ?",
        (challenge_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Challenge introuvable")

    rules = None
    try:
        if row[6]:
            rules = json.loads(row[6])
    except Exception:
        pass

    # Leaderboard
    participants = db.conn.execute(
        "SELECT cp.auth_user_id, cp.progress, cp.joined_at, "
        "COALESCE(c.display_name, 'Anonyme') "
        "FROM challenge_participants cp "
        "LEFT JOIN community_profiles c ON cp.auth_user_id = c.auth_user_id "
        "WHERE cp.challenge_id = ? ORDER BY cp.progress DESC",
        (challenge_id,),
    ).fetchall()

    leaderboard = [
        {
            "auth_user_id": p[0],
            "progress": p[1],
            "joined_at": p[2],
            "display_name": p[3],
            "rank": i + 1,
        }
        for i, p in enumerate(participants)
    ]

    count = db.conn.execute(
        "SELECT COUNT(*) FROM challenge_participants WHERE challenge_id = ?",
        (challenge_id,),
    ).fetchone()[0]

    return ChallengeDetailOut(
        id=row[0], title=row[1], description=row[2], category=row[3],
        start_date=row[4], end_date=row[5], rules=rules,
        created_at=row[7], participant_count=count,
        leaderboard=leaderboard,
    )


@router.post("/challenges/{challenge_id}/join")
async def join_challenge(
    challenge_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Join a challenge."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    # Check challenge exists
    ch = db.conn.execute("SELECT 1 FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if not ch:
        raise HTTPException(404, "Challenge introuvable")

    # Check not already joined
    existing = db.conn.execute(
        "SELECT 1 FROM challenge_participants WHERE challenge_id = ? AND auth_user_id = ?",
        (challenge_id, user_id),
    ).fetchone()
    if existing:
        raise HTTPException(400, "Deja inscrit a ce challenge")

    part_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO challenge_participants (id, challenge_id, auth_user_id, progress, joined_at) "
        "VALUES (?, ?, ?, 0.0, ?)",
        (part_id, challenge_id, user_id, now),
    )
    db.conn.commit()

    return {"id": part_id, "status": "joined"}


@router.put("/challenges/{challenge_id}/progress")
async def update_progress(
    challenge_id: str,
    data: ProgressIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Update challenge progress."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT id FROM challenge_participants WHERE challenge_id = ? AND auth_user_id = ?",
        (challenge_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Non inscrit a ce challenge")

    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "UPDATE challenge_participants SET progress = ?, updated_at = ? "
        "WHERE challenge_id = ? AND auth_user_id = ?",
        (data.progress, now, challenge_id, user_id),
    )
    db.conn.commit()

    return {"progress": data.progress}


# ══════════════════════════════════════════════════════════════════════════════
# VICTORIES TIMELINE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/victories", response_model=List[VictoryOut])
async def list_own_victories(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List own victories."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    rows = db.conn.execute(
        "SELECT v.id, v.auth_user_id, v.title, v.description, v.category, "
        "v.is_public, v.reactions_count, v.created_at, "
        "COALESCE(cp.display_name, '') "
        "FROM victories v "
        "LEFT JOIN community_profiles cp ON v.auth_user_id = cp.auth_user_id "
        "WHERE v.auth_user_id = ? ORDER BY v.created_at DESC",
        (user_id,),
    ).fetchall()

    return [
        VictoryOut(
            id=r[0], auth_user_id=r[1], title=r[2], description=r[3],
            category=r[4], is_public=r[5], reactions_count=r[6],
            created_at=r[7], display_name=r[8],
        )
        for r in rows
    ]


@router.get("/victories/feed", response_model=List[VictoryOut])
async def victories_feed(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Feed of public victories from connections."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    # Get connected user IDs
    connected_ids = []
    rows = db.conn.execute(
        "SELECT requester_id, receiver_id FROM connections "
        "WHERE (requester_id = ? OR receiver_id = ?) AND status = 'accepted'",
        (user_id, user_id),
    ).fetchall()
    for r in rows:
        other = r[1] if r[0] == user_id else r[0]
        connected_ids.append(other)

    if not connected_ids:
        return []

    placeholders = ",".join("?" for _ in connected_ids)
    victory_rows = db.conn.execute(
        f"SELECT v.id, v.auth_user_id, v.title, v.description, v.category, "
        f"v.is_public, v.reactions_count, v.created_at, "
        f"COALESCE(cp.display_name, '') "
        f"FROM victories v "
        f"LEFT JOIN community_profiles cp ON v.auth_user_id = cp.auth_user_id "
        f"WHERE v.auth_user_id IN ({placeholders}) AND v.is_public = 1 "
        f"ORDER BY v.created_at DESC LIMIT 50",
        connected_ids,
    ).fetchall()

    return [
        VictoryOut(
            id=r[0], auth_user_id=r[1], title=r[2], description=r[3],
            category=r[4], is_public=r[5], reactions_count=r[6],
            created_at=r[7], display_name=r[8],
        )
        for r in victory_rows
    ]


@router.post("/victories", response_model=VictoryOut)
async def create_victory(
    data: VictoryIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Record a victory."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    vic_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    db.conn.execute(
        "INSERT INTO victories (id, auth_user_id, title, description, category, is_public, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (vic_id, user_id, data.title, data.description, data.category, data.is_public, now),
    )
    db.conn.commit()

    display_name = ""
    row = db.conn.execute(
        "SELECT display_name FROM community_profiles WHERE auth_user_id = ?", (user_id,)
    ).fetchone()
    if row:
        display_name = row[0] or ""

    return VictoryOut(
        id=vic_id, auth_user_id=user_id, title=data.title,
        description=data.description, category=data.category,
        is_public=data.is_public, reactions_count=0,
        created_at=now, display_name=display_name,
    )


@router.post("/victories/{victory_id}/react")
async def react_to_victory(
    victory_id: str,
    data: ReactionIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """React to a victory."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    # Check victory exists
    vic = db.conn.execute("SELECT 1 FROM victories WHERE id = ?", (victory_id,)).fetchone()
    if not vic:
        raise HTTPException(404, "Victoire introuvable")

    # Check not already reacted
    existing = db.conn.execute(
        "SELECT 1 FROM victory_reactions WHERE victory_id = ? AND reactor_id = ?",
        (victory_id, user_id),
    ).fetchone()
    if existing:
        raise HTTPException(400, "Deja reagit a cette victoire")

    react_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO victory_reactions (id, victory_id, reactor_id, reaction_type, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (react_id, victory_id, user_id, data.reaction_type, now),
    )
    db.conn.execute(
        "UPDATE victories SET reactions_count = reactions_count + 1 WHERE id = ?",
        (victory_id,),
    )
    db.conn.commit()

    return {"reaction_id": react_id, "reaction_type": data.reaction_type}


@router.delete("/victories/{victory_id}")
async def delete_victory(
    victory_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Delete own victory."""
    _ensure_network_tables(db)
    if not user_id:
        raise HTTPException(401, "Authentification requise")

    row = db.conn.execute(
        "SELECT auth_user_id FROM victories WHERE id = ?", (victory_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Victoire introuvable")
    if row[0] != user_id:
        raise HTTPException(403, "Non autorise")

    db.conn.execute("DELETE FROM victory_reactions WHERE victory_id = ?", (victory_id,))
    db.conn.execute("DELETE FROM victories WHERE id = ?", (victory_id,))
    db.conn.commit()

    return {"deleted": True}
