"""
Router Agent Assistant (Agent Sylea 2) — assistant personnel capable d'AGIR.

Envoie des emails, redige des textes, gere des rappels, ouvre des liens.
Replique le pattern de agent_companion.py avec un system prompt oriente actions.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from api.context_helper import format_device_context
from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

router = APIRouter(prefix="/api/agent2", tags=["agent2"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class Agent2ChatIn(BaseModel):
    messages: list[dict]
    contexte_appareil: dict | None = None
    audio_data: str | None = None


class Agent2ChatOut(BaseModel):
    message: str
    choices: list[str] | None = None
    audioData: str | None = None


class Agent2MessageOut(BaseModel):
    id: str
    role: str
    content: str
    type: str
    created_at: str
    audioData: str = ""


class SendEmailIn(BaseModel):
    to: str
    subject: str
    body: str


class CreateReminderIn(BaseModel):
    time: str
    date: str
    message: str


class ReminderOut(BaseModel):
    id: int
    time: str
    date: str
    message: str
    completed: bool
    created_at: str


# ── DB helpers for agent2_messages ──────────────────────────────────────────

def _save_agent2_message(
    db: DatabaseManager, auth_user_id: str, role: str, content: str,
    msg_type: str = "text", audio_data: str = "",
) -> None:
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO agent2_messages (id, auth_user_id, role, content, type, created_at, audio_data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (msg_id, auth_user_id, role, content, msg_type, now, audio_data or ""),
    )
    db.conn.commit()


def _load_agent2_messages(
    db: DatabaseManager, auth_user_id: str, limit: int = 50,
) -> list[dict]:
    cursor = db.conn.execute(
        "SELECT id, role, content, type, created_at, audio_data FROM agent2_messages "
        "WHERE auth_user_id = ? ORDER BY created_at DESC LIMIT ?",
        (auth_user_id, limit),
    )
    rows = cursor.fetchall()
    return [
        {
            "id": r[0], "role": r[1], "content": r[2],
            "type": r[3], "created_at": r[4], "audio_data": r[5] or "",
        }
        for r in reversed(rows)
    ]


def _count_agent2_messages(db: DatabaseManager, auth_user_id: str) -> int:
    cursor = db.conn.execute(
        "SELECT COUNT(*) FROM agent2_messages WHERE auth_user_id = ?",
        (auth_user_id,),
    )
    return cursor.fetchone()[0]


def _clear_agent2_messages(db: DatabaseManager, auth_user_id: str) -> None:
    db.conn.execute(
        "DELETE FROM agent2_messages WHERE auth_user_id = ?",
        (auth_user_id,),
    )
    db.conn.commit()


# ── System prompt builder ────────────────────────────────────────────────────

def _build_agent2_prompt(
    profil_data: dict | None,
    decisions: list,
    sous_objectifs: list,
    collected_info: str = "",
    device_context: str = "",
    reminders: list[dict] | None = None,
) -> str:
    if profil_data:
        profil_info = f"""
PROFIL DE L'UTILISATEUR :
- Nom : {profil_data.get('nom', 'Inconnu')}
- Age : {profil_data.get('age', '?')}
- Genre : {profil_data.get('genre', 'Non renseigne')}
- Profession : {profil_data.get('profession', 'Non renseigne')}
- Ville : {profil_data.get('ville', 'Non renseigne')}
- Situation familiale : {profil_data.get('situation_familiale', 'Non renseigne')}
- Objectif de vie : {profil_data.get('objectif_description', 'Non defini')}
- Probabilite actuelle : {profil_data.get('probabilite_actuelle', 0):.1f}%
"""
    else:
        profil_info = "AUCUN PROFIL CREE - L'utilisateur n'a pas encore cree son profil."

    decisions_str = ""
    if decisions:
        decisions_str = "\nDERNIERES DECISIONS :\n"
        for d in decisions[:10]:
            decisions_str += f"  - {d.get('question', '?')} -> {d.get('choix', '?')} (impact: {d.get('impact', 0):+.1f}%)\n"

    so_str = ""
    if sous_objectifs:
        so_str = "\nSOUS-OBJECTIFS :\n"
        for so in sous_objectifs:
            so_str += f"  - {so.get('titre', '?')} (progression: {so.get('progression', 0):.0f}%)\n"

    reminders_str = ""
    if reminders:
        reminders_str = "\nRAPPELS ACTIFS :\n"
        for r in reminders:
            reminders_str += f"  - {r.get('date', '?')} a {r.get('time', '?')} : {r.get('message', '?')}\n"

    return f"""Tu es l'Agent Sylea 2, un assistant personnel capable d'AGIR concretement.
Tu parles comme un ami proche (tutoiement, naturel, 2-4 phrases max).

TES CAPACITES D'ACTION :
1. ENVOYER UN EMAIL : Quand l'utilisateur te demande d'envoyer un mail, tu rediges le mail et tu reponds avec :
   [ACTION:EMAIL]{{"to": "destinataire@email.com", "subject": "Objet", "body": "Corps du mail"}}[/ACTION]

2. REDIGER UN TEXTE : Quand on te demande un CV, lettre de motivation, post LinkedIn, etc., tu le rediges et tu reponds avec :
   [ACTION:TEXT]{{"title": "Mon CV", "content": "contenu complet...", "format": "txt"}}[/ACTION]

3. RAPPEL : Quand on te demande un rappel, tu reponds avec :
   [ACTION:REMINDER]{{"time": "18:00", "date": "2026-03-26", "message": "Coder pendant 2h"}}[/ACTION]

4. OUVRIR UN LIEN : Quand tu trouves une ressource utile :
   [ACTION:LINK]{{"url": "https://...", "label": "Formation React gratuite"}}[/ACTION]

5. COPIER : Quand l'utilisateur veut copier du texte :
   [ACTION:COPY]{{"text": "texte a copier"}}[/ACTION]

Tu peux combiner un message naturel + une action. Exemple :
"Voila ton mail pour le recruteur, je l'ai prepare pour toi !"
[ACTION:EMAIL]{{"to": "recruteur@company.com", "subject": "Candidature dev web", "body": "Bonjour..."}}[/ACTION]

REGLES :
- Avant d'envoyer un mail, TOUJOURS demander confirmation a l'utilisateur
- Pour les rappels, confirme l'heure et le message
- Tutoiement, naturel, concis
- Tu es un AGENT qui AGIT, pas juste un chatbot qui parle
- Tes messages font 1-3 phrases MAXIMUM. Jamais plus.
- Tu t'exprimes de la maniere la plus humaine possible

{profil_info}
{collected_info}
{decisions_str}
{so_str}
{reminders_str}
{device_context}
"""


# ── TTS audio generation helper ─────────────────────────────────────────────

async def _generate_tts_audio(text: str) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return ""
    try:
        import base64
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "tts-1", "voice": "nova", "input": text, "response_format": "mp3"},
                timeout=30,
            )
            if resp.status_code == 200:
                return base64.b64encode(resp.content).decode()
    except Exception:
        pass
    return ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=Agent2ChatOut)
async def agent2_chat(
    data: Agent2ChatIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return Agent2ChatOut(message="Agent indisponible -- cle API manquante.")

    # Load user data
    repo = ProfilRepository(db)
    profil_data = None
    if repo.existe(auth_user_id=user_id):
        profil = repo.charger(auth_user_id=user_id)
        profil_data = {
            "nom": profil.nom,
            "age": profil.age,
            "genre": getattr(profil, 'genre', None),
            "profession": profil.profession,
            "ville": profil.ville,
            "situation_familiale": profil.situation_familiale,
            "competences": getattr(profil, 'competences', []),
            "diplomes": getattr(profil, 'diplomes', []),
            "langues": getattr(profil, 'langues', []),
            "objectif_description": profil.objectif.description if profil.objectif else None,
            "probabilite_actuelle": profil.probabilite_actuelle,
        }

    # Load decisions
    dec_repo = DecisionRepository(db)
    try:
        decisions_raw = dec_repo.lister_pour_utilisateur(user_id or "", 20, auth_user_id=user_id)
    except Exception:
        decisions_raw = []
    decisions = (
        [{"question": d.question, "choix": d.choix, "impact": d.impact_probabilite} for d in decisions_raw[:20]]
        if decisions_raw
        else []
    )

    # Load sub-objectives
    sous_objectifs: list[dict] = []
    try:
        cursor = db.conn.execute(
            "SELECT titre, progression FROM sous_objectifs "
            "WHERE profil_id = (SELECT id FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1)",
            (user_id or "",),
        )
        sous_objectifs = [{"titre": r[0], "progression": r[1]} for r in cursor.fetchall()]
    except Exception:
        pass

    # Load collected info
    collected_info = ""
    if user_id:
        try:
            rows = db.conn.execute(
                "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 30",
                (user_id,),
            ).fetchall()
            if rows:
                collected_info = "\nINFORMATIONS COLLECTEES :\n"
                for field, value in rows:
                    collected_info += f"  - {field}: {value}\n"
        except Exception:
            pass

    # Load active reminders
    reminders: list[dict] = []
    if user_id:
        try:
            cursor = db.conn.execute(
                "SELECT time, date, message FROM agent_reminders "
                "WHERE user_id = ? AND completed = 0 ORDER BY date, time LIMIT 10",
                (user_id,),
            )
            reminders = [{"time": r[0], "date": r[1], "message": r[2]} for r in cursor.fetchall()]
        except Exception:
            pass

    # Build prompt
    device_ctx = format_device_context(data.contexte_appareil) if data.contexte_appareil else ""
    system_prompt = _build_agent2_prompt(
        profil_data, decisions, sous_objectifs, collected_info, device_ctx, reminders,
    )

    # Build chat context
    if user_id:
        db_messages = _load_agent2_messages(db, user_id, limit=50)
        chat_messages = [
            {"role": "assistant" if m["role"] == "agent" else "user", "content": m["content"]}
            for m in db_messages
        ]
        if data.messages:
            last_msg = data.messages[-1]
            if last_msg.get("role") == "user":
                chat_messages.append({"role": "user", "content": last_msg["content"]})
    else:
        chat_messages = data.messages[-20:]

    user_msg_type = "text"
    if data.messages:
        last_input = data.messages[-1]
        user_msg_type = last_input.get("type", "text")

    # Call Claude
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=system_prompt,
            messages=chat_messages[-20:],
        )
    )

    agent_response = msg.content[0].text.strip()

    # Generate TTS audio for agent response if user sent a voice message
    agent_audio_data = ""
    if user_msg_type == "voice":
        agent_audio_data = await _generate_tts_audio(agent_response)

    # Persist messages if authenticated
    if user_id:
        if data.messages:
            last_user = data.messages[-1]
            if last_user.get("role") == "user":
                _save_agent2_message(
                    db, user_id, "user", last_user["content"], user_msg_type,
                    audio_data=data.audio_data or "",
                )
        agent_msg_type = "voice" if user_msg_type == "voice" else "text"
        _save_agent2_message(
            db, user_id, "agent", agent_response, agent_msg_type,
            audio_data=agent_audio_data,
        )

    return Agent2ChatOut(
        message=agent_response,
        audioData=agent_audio_data if agent_audio_data else None,
    )


@router.get("/messages", response_model=list[Agent2MessageOut])
async def get_agent2_messages(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not user_id:
        return []
    messages = _load_agent2_messages(db, user_id, limit=200)
    return [
        Agent2MessageOut(
            id=m["id"], role=m["role"], content=m["content"],
            type=m["type"], created_at=m["created_at"],
            audioData=m.get("audio_data", ""),
        )
        for m in messages
    ]


@router.delete("/messages")
async def clear_agent2_messages(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if user_id:
        _clear_agent2_messages(db, user_id)
    return {"detail": "Historique de conversation supprime."}


@router.post("/send-email")
async def send_email(
    data: SendEmailIn,
    user_id: str | None = Depends(get_optional_user),
):
    smtp_email = os.environ.get("SMTP_EMAIL", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    if not smtp_email or not smtp_password:
        return {"ok": False, "error": "SMTP non configure. Definissez SMTP_EMAIL et SMTP_PASSWORD."}

    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import smtplib

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = data.to
    msg["Subject"] = data.subject
    msg.attach(MIMEText(data.body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/create-reminder")
async def create_reminder(
    data: CreateReminderIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not user_id:
        return {"ok": False, "error": "Authentification requise"}
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO agent_reminders (user_id, agent_id, reminder_time, reminder_date, message, completed, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (user_id, "agent2", data.time, data.date, data.message, now),
    )
    db.conn.commit()
    return {"ok": True}


@router.get("/reminders", response_model=list[ReminderOut])
async def get_reminders(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not user_id:
        return []
    cursor = db.conn.execute(
        "SELECT id, reminder_time, reminder_date, message, completed, created_at "
        "FROM agent_reminders WHERE user_id = ? AND completed = 0 ORDER BY reminder_date, reminder_time",
        (user_id,),
    )
    return [
        ReminderOut(
            id=r[0], time=r[1], date=r[2], message=r[3],
            completed=bool(r[4]), created_at=r[5],
        )
        for r in cursor.fetchall()
    ]


@router.post("/reminders/{reminder_id}/complete")
async def complete_reminder(
    reminder_id: int,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not user_id:
        return {"ok": False}
    db.conn.execute(
        "UPDATE agent_reminders SET completed = 1 WHERE id = ? AND user_id = ?",
        (reminder_id, user_id),
    )
    db.conn.commit()
    return {"ok": True}


@router.post("/proactive")
async def generate_proactive_message(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not user_id:
        return {"message": None}

    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=user_id):
        return {"message": None}

    profil = repo.charger(auth_user_id=user_id)

    # Check last proactive message time
    last_proactive = db.conn.execute(
        "SELECT created_at FROM agent2_messages WHERE auth_user_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    now = datetime.now(timezone.utc)
    hours_since_proactive = 999
    if last_proactive and last_proactive[0]:
        try:
            last_dt = datetime.fromisoformat(last_proactive[0].replace('Z', '+00:00')) if 'T' in last_proactive[0] else datetime.strptime(last_proactive[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            hours_since_proactive = (now - last_dt).total_seconds() / 3600
        except Exception:
            pass

    if hours_since_proactive < 72:
        return {"message": None}

    prompt = f"""Tu es l'Agent Sylea 2 de {profil.nom}.
Tu dois envoyer un message proactif naturel. C'est TOI qui initie la conversation.
Tu es un assistant capable d'agir (emails, rappels, textes).

Profil: {profil.nom}, {profil.age} ans, {profil.profession}, objectif: {profil.objectif.description if profil.objectif else 'non defini'}

REGLES:
- Message COURT (1-2 phrases max)
- Propose une action concrete (envoyer un mail, creer un rappel, rediger un texte)
- Naturel, comme un ami qui envoie un texto
- Tutoiement

Ecris le message:"""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
        )

        agent_text = msg.content[0].text.strip()
        _save_agent2_message(db, user_id, "agent", agent_text, "text")
        return {"message": agent_text}
    except Exception:
        return {"message": None}


@router.post("/tts")
async def text_to_speech(data: dict):
    text = data.get("text", "")
    if not text:
        return Response(content=b"", media_type="audio/mpeg")

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        return Response(content=b"", media_type="audio/mpeg", status_code=503)

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "tts-1",
                    "input": text,
                    "voice": "nova",
                    "response_format": "mp3",
                    "speed": 1.0,
                },
                timeout=30.0,
            )
            if response.status_code == 200:
                return Response(content=response.content, media_type="audio/mpeg")
            else:
                return Response(content=b"", media_type="audio/mpeg", status_code=502)
    except Exception:
        return Response(content=b"", media_type="audio/mpeg", status_code=500)
