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
from sqlalchemy import text

from api.database import get_session_factory
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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
                "probability_current, visibility, mentor_available, created_at, updated_at "
                "FROM community_profiles WHERE auth_user_id = :uid"
            ),
            {"uid": user_id},
        )
        row = result.mappings().first()

    if not row:
        raise HTTPException(404, "Profil communautaire non cree")

    return CommunityProfileOut(
        auth_user_id=row["auth_user_id"], display_name=row["display_name"], bio=row["bio"],
        objective_summary=row["objective_summary"], objective_category=row["objective_category"],
        probability_current=row["probability_current"], visibility=row["visibility"],
        mentor_available=row["mentor_available"], created_at=row["created_at"],
        updated_at=row["updated_at"],
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
    factory = get_session_factory()
    async with factory() as session:
        try:
            existing_result = await session.execute(
                text("SELECT 1 FROM community_profiles WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            existing = existing_result.first()

            if existing:
                await session.execute(
                    text(
                        "UPDATE community_profiles SET display_name = :display_name, "
                        "bio = :bio, objective_summary = :objective_summary, "
                        "visibility = :visibility, mentor_available = :mentor_available, "
                        "updated_at = :updated_at WHERE auth_user_id = :uid"
                    ),
                    {
                        "display_name": data.display_name,
                        "bio": data.bio,
                        "objective_summary": data.objective_summary,
                        "visibility": data.visibility,
                        "mentor_available": data.mentor_available,
                        "updated_at": now,
                        "uid": user_id,
                    },
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO community_profiles "
                        "(auth_user_id, display_name, bio, objective_summary, visibility, "
                        "mentor_available, created_at, updated_at) "
                        "VALUES (:uid, :display_name, :bio, :objective_summary, :visibility, "
                        ":mentor_available, :created_at, :updated_at)"
                    ),
                    {
                        "uid": user_id,
                        "display_name": data.display_name,
                        "bio": data.bio,
                        "objective_summary": data.objective_summary,
                        "visibility": data.visibility,
                        "mentor_available": data.mentor_available,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # Sync from main profile
    await _sync_profile_from_sylea_async(user_id)

    return await get_own_profile(db=db, user_id=user_id)


@router.get("/profile/{target_user_id}", response_model=CommunityProfileOut)
async def get_public_profile(
    target_user_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Get someone's public profile."""
    _ensure_network_tables(db)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
                "probability_current, visibility, mentor_available, created_at, updated_at "
                "FROM community_profiles WHERE auth_user_id = :uid AND visibility = 'public'"
            ),
            {"uid": target_user_id},
        )
        row = result.mappings().first()

    if not row:
        raise HTTPException(404, "Profil introuvable ou prive")

    return CommunityProfileOut(
        auth_user_id=row["auth_user_id"], display_name=row["display_name"], bio=row["bio"],
        objective_summary=row["objective_summary"], objective_category=row["objective_category"],
        probability_current=row["probability_current"], visibility=row["visibility"],
        mentor_available=row["mentor_available"], created_at=row["created_at"],
        updated_at=row["updated_at"],
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
    await _sync_profile_from_sylea_async(user_id)

    factory = get_session_factory()
    async with factory() as session:
        # Get own category and probability
        own_result = await session.execute(
            text(
                "SELECT objective_category, probability_current FROM community_profiles "
                "WHERE auth_user_id = :uid"
            ),
            {"uid": user_id},
        )
        own = own_result.mappings().first()

        own_cat = own["objective_category"] if own else ""
        own_prob = own["probability_current"] if own else 0.0

        # Get connected user IDs to exclude
        connected_ids = set()
        connected_ids.add(user_id)
        conn_result = await session.execute(
            text(
                "SELECT requester_id, receiver_id FROM connections "
                "WHERE (requester_id = :uid OR receiver_id = :uid) "
                "AND status IN ('pending', 'accepted')"
            ),
            {"uid": user_id},
        )
        for r in conn_result.mappings().all():
            connected_ids.add(r["requester_id"])
            connected_ids.add(r["receiver_id"])

        # Fetch public profiles, excluding connected — named-param placeholders
        params: dict = {"own_cat": own_cat, "own_prob": own_prob}
        ph_keys = []
        for i, cid in enumerate(connected_ids):
            key = f"cid{i}"
            ph_keys.append(f":{key}")
            params[key] = cid
        placeholders = ",".join(ph_keys)

        all_result = await session.execute(
            text(
                f"SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
                f"probability_current, visibility, mentor_available, created_at, updated_at "
                f"FROM community_profiles WHERE visibility = 'public' "
                f"AND auth_user_id NOT IN ({placeholders}) "
                f"ORDER BY CASE WHEN objective_category = :own_cat THEN 0 ELSE 1 END, "
                f"ABS(probability_current - :own_prob) ASC "
                f"LIMIT 20"
            ),
            params,
        )
        all_profiles = all_result.mappings().all()

    return [
        CommunityProfileOut(
            auth_user_id=r["auth_user_id"], display_name=r["display_name"], bio=r["bio"],
            objective_summary=r["objective_summary"], objective_category=r["objective_category"],
            probability_current=r["probability_current"], visibility=r["visibility"],
            mentor_available=r["mentor_available"], created_at=r["created_at"],
            updated_at=r["updated_at"],
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Check if already connected or pending
            existing_result = await session.execute(
                text(
                    "SELECT status FROM connections WHERE "
                    "(requester_id = :uid AND receiver_id = :tid) "
                    "OR (requester_id = :tid AND receiver_id = :uid)"
                ),
                {"uid": user_id, "tid": target_user_id},
            )
            existing = existing_result.mappings().first()
            if existing:
                raise HTTPException(400, f"Connexion deja existante (statut: {existing['status']})")

            conn_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "INSERT INTO connections (id, requester_id, receiver_id, status, created_at) "
                    "VALUES (:id, :uid, :tid, 'pending', :now)"
                ),
                {"id": conn_id, "uid": user_id, "tid": target_user_id, "now": now},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT c.id, c.requester_id, c.receiver_id, c.status, c.created_at, c.updated_at, "
                "COALESCE(cp.display_name, '') AS display_name "
                "FROM connections c "
                "LEFT JOIN community_profiles cp ON "
                "  CASE WHEN c.requester_id = :uid THEN c.receiver_id ELSE c.requester_id END "
                "  = cp.auth_user_id "
                "WHERE (c.requester_id = :uid OR c.receiver_id = :uid) AND c.status = 'accepted'"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()

    return [
        ConnectionOut(
            id=r["id"], requester_id=r["requester_id"], receiver_id=r["receiver_id"],
            status=r["status"], created_at=r["created_at"], updated_at=r["updated_at"],
            display_name=r["display_name"],
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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT c.id, c.requester_id, c.receiver_id, c.status, c.created_at, c.updated_at, "
                "COALESCE(cp.display_name, '') AS display_name "
                "FROM connections c "
                "LEFT JOIN community_profiles cp ON c.requester_id = cp.auth_user_id "
                "WHERE c.receiver_id = :uid AND c.status = 'pending'"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()

    return [
        ConnectionOut(
            id=r["id"], requester_id=r["requester_id"], receiver_id=r["receiver_id"],
            status=r["status"], created_at=r["created_at"], updated_at=r["updated_at"],
            display_name=r["display_name"],
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("SELECT receiver_id, status FROM connections WHERE id = :cid"),
                {"cid": conn_id},
            )
            row = result.mappings().first()
            if not row:
                raise HTTPException(404, "Connexion introuvable")
            if row["receiver_id"] != user_id:
                raise HTTPException(403, "Seul le destinataire peut accepter")
            if row["status"] != "pending":
                raise HTTPException(400, "Cette connexion n'est plus en attente")

            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "UPDATE connections SET status = 'accepted', updated_at = :now WHERE id = :cid"
                ),
                {"now": now, "cid": conn_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("SELECT receiver_id, status FROM connections WHERE id = :cid"),
                {"cid": conn_id},
            )
            row = result.mappings().first()
            if not row:
                raise HTTPException(404, "Connexion introuvable")
            if row["receiver_id"] != user_id:
                raise HTTPException(403, "Seul le destinataire peut refuser")

            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "UPDATE connections SET status = 'rejected', updated_at = :now WHERE id = :cid"
                ),
                {"now": now, "cid": conn_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
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

    factory = get_session_factory()
    async with factory() as session:
        sql = (
            "SELECT auth_user_id, display_name, bio, objective_summary, objective_category, "
            "probability_current, visibility, mentor_available, created_at, updated_at "
            "FROM community_profiles "
            "WHERE mentor_available = 1 AND probability_current >= 70 AND visibility = 'public'"
        )
        params: dict = {}
        if user_id:
            sql += " AND auth_user_id != :uid"
            params["uid"] = user_id
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()

    return [
        CommunityProfileOut(
            auth_user_id=r["auth_user_id"], display_name=r["display_name"], bio=r["bio"],
            objective_summary=r["objective_summary"], objective_category=r["objective_category"],
            probability_current=r["probability_current"], visibility=r["visibility"],
            mentor_available=r["mentor_available"], created_at=r["created_at"],
            updated_at=r["updated_at"],
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Check mentor exists and is available
            mentor_result = await session.execute(
                text(
                    "SELECT mentor_available, display_name FROM community_profiles "
                    "WHERE auth_user_id = :mid"
                ),
                {"mid": data.mentor_id},
            )
            mentor = mentor_result.mappings().first()
            if not mentor or mentor["mentor_available"] != 1:
                raise HTTPException(404, "Mentor non disponible")

            # Check for existing relationship
            existing_result = await session.execute(
                text(
                    "SELECT status FROM mentoring_relationships "
                    "WHERE mentor_id = :mid AND mentee_id = :uid "
                    "AND status IN ('pending', 'active')"
                ),
                {"mid": data.mentor_id, "uid": user_id},
            )
            existing = existing_result.mappings().first()
            if existing:
                raise HTTPException(
                    400, f"Relation de mentorat deja existante (statut: {existing['status']})"
                )

            rel_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "INSERT INTO mentoring_relationships "
                    "(id, mentor_id, mentee_id, status, message, created_at) "
                    "VALUES (:id, :mid, :uid, 'pending', :msg, :now)"
                ),
                {
                    "id": rel_id,
                    "mid": data.mentor_id,
                    "uid": user_id,
                    "msg": data.message,
                    "now": now,
                },
            )
            await session.commit()

            # Get mentee name
            mentee_result = await session.execute(
                text("SELECT display_name FROM community_profiles WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            mentee = mentee_result.mappings().first()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

    return MentoringOut(
        id=rel_id, mentor_id=data.mentor_id, mentee_id=user_id,
        mentor_name=mentor["display_name"] or "",
        mentee_name=(mentee["display_name"] if mentee else "") or "",
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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT mr.id, mr.mentor_id, mr.mentee_id, mr.status, mr.message, "
                "mr.created_at, mr.updated_at, "
                "COALESCE(cm.display_name, '') AS mentor_name, "
                "COALESCE(ce.display_name, '') AS mentee_name "
                "FROM mentoring_relationships mr "
                "LEFT JOIN community_profiles cm ON mr.mentor_id = cm.auth_user_id "
                "LEFT JOIN community_profiles ce ON mr.mentee_id = ce.auth_user_id "
                "WHERE mr.mentor_id = :uid OR mr.mentee_id = :uid "
                "ORDER BY mr.created_at DESC"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()

    return [
        MentoringOut(
            id=r["id"], mentor_id=r["mentor_id"], mentee_id=r["mentee_id"],
            status=r["status"], message=r["message"] or "",
            created_at=r["created_at"], updated_at=r["updated_at"],
            mentor_name=r["mentor_name"], mentee_name=r["mentee_name"],
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("SELECT mentor_id, status FROM mentoring_relationships WHERE id = :rid"),
                {"rid": rel_id},
            )
            row = result.mappings().first()
            if not row:
                raise HTTPException(404, "Relation introuvable")
            if row["mentor_id"] != user_id:
                raise HTTPException(403, "Seul le mentor peut accepter")
            if row["status"] != "pending":
                raise HTTPException(400, "Cette relation n'est plus en attente")

            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "UPDATE mentoring_relationships SET status = 'active', "
                    "updated_at = :now WHERE id = :rid"
                ),
                {"now": now, "rid": rel_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("SELECT mentor_id, mentee_id FROM mentoring_relationships WHERE id = :rid"),
                {"rid": rel_id},
            )
            row = result.mappings().first()
            if not row:
                raise HTTPException(404, "Relation introuvable")
            if user_id not in (row["mentor_id"], row["mentee_id"]):
                raise HTTPException(403, "Non autorise")

            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "UPDATE mentoring_relationships SET status = 'ended', "
                    "updated_at = :now WHERE id = :rid"
                ),
                {"now": now, "rid": rel_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT c.id, c.title, c.description, c.category, c.start_date, c.end_date, "
                "c.rules_json, c.created_at, "
                "(SELECT COUNT(*) FROM challenge_participants cp WHERE cp.challenge_id = c.id) "
                "  AS participant_count "
                "FROM challenges c WHERE c.end_date >= :today ORDER BY c.start_date"
            ),
            {"today": today},
        )
        rows = result.mappings().all()

    results = []
    for r in rows:
        rules = None
        try:
            if r["rules_json"]:
                rules = json.loads(r["rules_json"])
        except Exception:
            pass
        results.append(ChallengeOut(
            id=r["id"], title=r["title"], description=r["description"], category=r["category"],
            start_date=r["start_date"], end_date=r["end_date"], rules=rules,
            created_at=r["created_at"], participant_count=r["participant_count"],
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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT c.id, c.title, c.description, c.category, c.start_date, c.end_date, "
                "c.rules_json, c.created_at, "
                "(SELECT COUNT(*) FROM challenge_participants cp WHERE cp.challenge_id = c.id) "
                "  AS participant_count "
                "FROM challenges c WHERE c.end_date < :today "
                "ORDER BY c.end_date DESC LIMIT 20"
            ),
            {"today": today},
        )
        rows = result.mappings().all()

    results = []
    for r in rows:
        rules = None
        try:
            if r["rules_json"]:
                rules = json.loads(r["rules_json"])
        except Exception:
            pass
        results.append(ChallengeOut(
            id=r["id"], title=r["title"], description=r["description"], category=r["category"],
            start_date=r["start_date"], end_date=r["end_date"], rules=rules,
            created_at=r["created_at"], participant_count=r["participant_count"],
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

    factory = get_session_factory()
    async with factory() as session:
        ch_result = await session.execute(
            text(
                "SELECT id, title, description, category, start_date, end_date, "
                "rules_json, created_at FROM challenges WHERE id = :cid"
            ),
            {"cid": challenge_id},
        )
        row = ch_result.mappings().first()
        if not row:
            raise HTTPException(404, "Challenge introuvable")

        rules = None
        try:
            if row["rules_json"]:
                rules = json.loads(row["rules_json"])
        except Exception:
            pass

        # Leaderboard
        part_result = await session.execute(
            text(
                "SELECT cp.auth_user_id, cp.progress, cp.joined_at, "
                "COALESCE(c.display_name, 'Anonyme') AS display_name "
                "FROM challenge_participants cp "
                "LEFT JOIN community_profiles c ON cp.auth_user_id = c.auth_user_id "
                "WHERE cp.challenge_id = :cid ORDER BY cp.progress DESC"
            ),
            {"cid": challenge_id},
        )
        participants = part_result.mappings().all()

        count_result = await session.execute(
            text("SELECT COUNT(*) FROM challenge_participants WHERE challenge_id = :cid"),
            {"cid": challenge_id},
        )
        count = count_result.scalar() or 0

    leaderboard = [
        {
            "auth_user_id": p["auth_user_id"],
            "progress": p["progress"],
            "joined_at": p["joined_at"],
            "display_name": p["display_name"],
            "rank": i + 1,
        }
        for i, p in enumerate(participants)
    ]

    return ChallengeDetailOut(
        id=row["id"], title=row["title"], description=row["description"],
        category=row["category"], start_date=row["start_date"], end_date=row["end_date"],
        rules=rules, created_at=row["created_at"], participant_count=count,
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Check challenge exists
            ch_result = await session.execute(
                text("SELECT 1 FROM challenges WHERE id = :cid"),
                {"cid": challenge_id},
            )
            if not ch_result.first():
                raise HTTPException(404, "Challenge introuvable")

            # Check not already joined
            existing_result = await session.execute(
                text(
                    "SELECT 1 FROM challenge_participants "
                    "WHERE challenge_id = :cid AND auth_user_id = :uid"
                ),
                {"cid": challenge_id, "uid": user_id},
            )
            if existing_result.first():
                raise HTTPException(400, "Deja inscrit a ce challenge")

            part_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "INSERT INTO challenge_participants "
                    "(id, challenge_id, auth_user_id, progress, joined_at) "
                    "VALUES (:id, :cid, :uid, 0.0, :now)"
                ),
                {"id": part_id, "cid": challenge_id, "uid": user_id, "now": now},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

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

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id FROM challenge_participants "
                    "WHERE challenge_id = :cid AND auth_user_id = :uid"
                ),
                {"cid": challenge_id, "uid": user_id},
            )
            if not result.first():
                raise HTTPException(404, "Non inscrit a ce challenge")

            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "UPDATE challenge_participants SET progress = :progress, updated_at = :now "
                    "WHERE challenge_id = :cid AND auth_user_id = :uid"
                ),
                {"progress": data.progress, "now": now, "cid": challenge_id, "uid": user_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

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

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT v.id, v.auth_user_id, v.title, v.description, v.category, "
                "v.is_public, v.reactions_count, v.created_at, "
                "COALESCE(cp.display_name, '') AS display_name "
                "FROM victories v "
                "LEFT JOIN community_profiles cp ON v.auth_user_id = cp.auth_user_id "
                "WHERE v.auth_user_id = :uid ORDER BY v.created_at DESC"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()

    return [
        VictoryOut(
            id=r["id"], auth_user_id=r["auth_user_id"], title=r["title"],
            description=r["description"], category=r["category"], is_public=r["is_public"],
            reactions_count=r["reactions_count"], created_at=r["created_at"],
            display_name=r["display_name"],
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

    factory = get_session_factory()
    async with factory() as session:
        # Get connected user IDs
        connected_ids: list[str] = []
        conn_result = await session.execute(
            text(
                "SELECT requester_id, receiver_id FROM connections "
                "WHERE (requester_id = :uid OR receiver_id = :uid) AND status = 'accepted'"
            ),
            {"uid": user_id},
        )
        for r in conn_result.mappings().all():
            other = r["receiver_id"] if r["requester_id"] == user_id else r["requester_id"]
            connected_ids.append(other)

        if not connected_ids:
            return []

        # Named-param placeholders for IN-clause
        params: dict = {}
        ph_keys = []
        for i, cid in enumerate(connected_ids):
            key = f"cid{i}"
            ph_keys.append(f":{key}")
            params[key] = cid
        placeholders = ",".join(ph_keys)

        vic_result = await session.execute(
            text(
                f"SELECT v.id, v.auth_user_id, v.title, v.description, v.category, "
                f"v.is_public, v.reactions_count, v.created_at, "
                f"COALESCE(cp.display_name, '') AS display_name "
                f"FROM victories v "
                f"LEFT JOIN community_profiles cp ON v.auth_user_id = cp.auth_user_id "
                f"WHERE v.auth_user_id IN ({placeholders}) AND v.is_public = 1 "
                f"ORDER BY v.created_at DESC LIMIT 50"
            ),
            params,
        )
        victory_rows = vic_result.mappings().all()

    return [
        VictoryOut(
            id=r["id"], auth_user_id=r["auth_user_id"], title=r["title"],
            description=r["description"], category=r["category"], is_public=r["is_public"],
            reactions_count=r["reactions_count"], created_at=r["created_at"],
            display_name=r["display_name"],
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

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO victories "
                    "(id, auth_user_id, title, description, category, is_public, created_at) "
                    "VALUES (:id, :uid, :title, :description, :category, :is_public, :now)"
                ),
                {
                    "id": vic_id,
                    "uid": user_id,
                    "title": data.title,
                    "description": data.description,
                    "category": data.category,
                    "is_public": data.is_public,
                    "now": now,
                },
            )
            await session.commit()

            display_name = ""
            name_result = await session.execute(
                text("SELECT display_name FROM community_profiles WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            row = name_result.mappings().first()
            if row:
                display_name = row["display_name"] or ""
        except Exception:
            await session.rollback()
            raise

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

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Check victory exists
            vic_result = await session.execute(
                text("SELECT 1 FROM victories WHERE id = :vid"),
                {"vid": victory_id},
            )
            if not vic_result.first():
                raise HTTPException(404, "Victoire introuvable")

            # Check not already reacted
            existing_result = await session.execute(
                text(
                    "SELECT 1 FROM victory_reactions "
                    "WHERE victory_id = :vid AND reactor_id = :uid"
                ),
                {"vid": victory_id, "uid": user_id},
            )
            if existing_result.first():
                raise HTTPException(400, "Deja reagit a cette victoire")

            react_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text(
                    "INSERT INTO victory_reactions "
                    "(id, victory_id, reactor_id, reaction_type, created_at) "
                    "VALUES (:id, :vid, :uid, :rtype, :now)"
                ),
                {
                    "id": react_id,
                    "vid": victory_id,
                    "uid": user_id,
                    "rtype": data.reaction_type,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "UPDATE victories SET reactions_count = reactions_count + 1 "
                    "WHERE id = :vid"
                ),
                {"vid": victory_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

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

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("SELECT auth_user_id FROM victories WHERE id = :vid"),
                {"vid": victory_id},
            )
            row = result.mappings().first()
            if not row:
                raise HTTPException(404, "Victoire introuvable")
            if row["auth_user_id"] != user_id:
                raise HTTPException(403, "Non autorise")

            await session.execute(
                text("DELETE FROM victory_reactions WHERE victory_id = :vid"),
                {"vid": victory_id},
            )
            await session.execute(
                text("DELETE FROM victories WHERE id = :vid"),
                {"vid": victory_id},
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

    return {"deleted": True}


# ══════════════════════════════════════════════════════════════════════════════
# ASYNC HELPERS (SQLAlchemy text() — SQLite + PostgreSQL compatible)
# ══════════════════════════════════════════════════════════════════════════════

async def _sync_profile_from_sylea_async(user_id: str) -> None:
    """Async sibling of ``_sync_profile_from_sylea``.

    Syncs objective_category and probability_current from profil_utilisateur
    using the async SQLAlchemy session factory. Used by async endpoints to
    avoid mixing sync (db.conn) and async access patterns.

    Silently swallows exceptions to preserve original behavior.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT objectif_categorie, probabilite_actuelle, objectif_description "
                    "FROM profil_utilisateur WHERE auth_user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if row:
                await session.execute(
                    text(
                        "UPDATE community_profiles SET objective_category = :cat, "
                        "probability_current = :prob WHERE auth_user_id = :uid"
                    ),
                    {
                        "cat": row["objectif_categorie"] or "",
                        "prob": row["probabilite_actuelle"] or 0.0,
                        "uid": user_id,
                    },
                )
                await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass

