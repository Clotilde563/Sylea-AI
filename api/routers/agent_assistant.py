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
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from api.context_helper import format_device_context, build_full_user_context
from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

# v2 enrichments : shared memory + awareness + Google context
try:
    from api.agent_shared_memory import (
        load_memories, format_memories, auto_extract_from_turns,
    )
except Exception:
    load_memories = lambda *a, **k: []
    format_memories = lambda m, **k: ""
    async def auto_extract_from_turns(*a, **k): return []
try:
    from api.agent3_awareness import build_awareness_block
except Exception:
    def build_awareness_block(db, user_id): return ""
try:
    from api.google_context import build_google_context_block
except Exception:
    async def build_google_context_block(db, user_id): return ""

router = APIRouter(prefix="/api/agent2", tags=["agent2"])

# v2 : Track background tasks pour eviter le GC FastAPI qui annule les
# asyncio.create_task issues d'un request handler.
_BG_TASKS: set = set()


# ── Schemas ──────────────────────────────────────────────────────────────────

class Agent2ChatIn(BaseModel):
    messages: list[dict]
    contexte_appareil: dict | None = None
    audio_data: str | None = None


class Agent2ChatOut(BaseModel):
    message: str
    choices: list[str] | None = None
    actions: list[dict] | None = None
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


# ── Profile extraction helper (copied from agent_companion.py) ─────────────

async def _extract_and_update_profile(
    db: DatabaseManager,
    auth_user_id: str,
    conversation_messages: list[dict],
) -> None:
    """Use a cheap Claude call to extract profile info from conversation and update DB."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not auth_user_id:
        return

    # Build conversation text
    conversation_text = "\n".join(
        f"{'Utilisateur' if m.get('role') == 'user' else 'Agent'}: {m.get('content', '')}"
        for m in conversation_messages[-20:]  # Last 20 messages for context
    )

    extraction_prompt = f"""Analyse cette conversation et extrais UNIQUEMENT les informations personnelles
que l'utilisateur a EXPLICITEMENT revelees. Ne deduis rien, ne suppose rien.

Conversation:
{conversation_text}

Reponds UNIQUEMENT avec du JSON valide (ou {{}} si rien de nouveau):
{{
  "genre": null,
  "ville": null,
  "situation_familiale": null,
  "competences": null,
  "diplomes": null,
  "langues": null,
  "profession": null
}}

REGLES:
- Ne remplis que les champs que l'utilisateur a EXPLICITEMENT mentionnes
- competences, diplomes, langues sont des listes de strings
- Laisse null si pas mentionne
- genre: "homme" ou "femme" uniquement
"""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        result = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": extraction_prompt}],
            )
        )

        raw = result.content[0].text.strip()
        # Extract JSON from response (handle markdown code blocks)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        extracted = json.loads(raw)
        if not extracted or not isinstance(extracted, dict):
            return

        # Load current profile
        repo = ProfilRepository(db)
        if not repo.existe(auth_user_id=auth_user_id):
            return
        profil = repo.charger(auth_user_id=auth_user_id)
        if not profil:
            return

        # Update only non-null extracted fields that are currently empty
        updated = False

        if extracted.get("genre") and not getattr(profil, "genre", None):
            db.conn.execute(
                "UPDATE profil_utilisateur SET genre = ? WHERE auth_user_id = ?",
                (extracted["genre"], auth_user_id),
            )
            updated = True

        if extracted.get("ville") and (not profil.ville or profil.ville == "Non renseigne"):
            db.conn.execute(
                "UPDATE profil_utilisateur SET ville = ? WHERE auth_user_id = ?",
                (extracted["ville"], auth_user_id),
            )
            updated = True

        if extracted.get("situation_familiale") and (
            not profil.situation_familiale or profil.situation_familiale == "Non renseigne"
        ):
            db.conn.execute(
                "UPDATE profil_utilisateur SET situation_familiale = ? WHERE auth_user_id = ?",
                (extracted["situation_familiale"], auth_user_id),
            )
            updated = True

        if extracted.get("profession") and (not profil.profession or profil.profession == "Non renseigne"):
            db.conn.execute(
                "UPDATE profil_utilisateur SET profession = ? WHERE auth_user_id = ?",
                (extracted["profession"], auth_user_id),
            )
            updated = True

        # List fields — only update if currently empty
        for field in ("competences", "diplomes", "langues"):
            val = extracted.get(field)
            if val and isinstance(val, list) and len(val) > 0:
                current = getattr(profil, field, None)
                if not current or (isinstance(current, list) and len(current) == 0) or current == "":
                    db.conn.execute(
                        f"UPDATE profil_utilisateur SET {field} = ? WHERE auth_user_id = ?",
                        (",".join(val), auth_user_id),
                    )
                    updated = True

        if updated:
            db.conn.commit()

    except Exception:
        pass  # Silently fail — extraction is best-effort


# ── System prompt builder ────────────────────────────────────────────────────

def _build_agent2_prompt(
    profil_data: dict | None,
    decisions: list,
    sous_objectifs: list,
    collected_info: str = "",
    device_context: str = "",
    reminders: list[dict] | None = None,
    full_context: str = "",
    awareness_block: str = "",
    memory_block: str = "",
    google_block: str = "",
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

    awareness_section = (awareness_block + "\n") if awareness_block else ""
    memory_section = (memory_block + "\n") if memory_block else ""
    google_section = (google_block + "\n") if google_block else ""

    return f"""{awareness_section}{memory_section}{google_section}Tu es l'Agent Sylea 2, un assistant personnel qui AGIT. Tu ne parles pas, tu FAIS.
Tutoiement, naturel, 1 phrase max avant les actions.

=== REGLES ABSOLUES — TU NE DOIS JAMAIS LES ENFREINDRE ===

1. TU N'EXPLIQUES JAMAIS TES LIMITATIONS. Jamais. Tu ne dis JAMAIS "je ne peux pas", "limitation technique", "c'est pas possible de". Tu trouves un moyen et tu FAIS.

2. TU NE POSES JAMAIS DE QUESTION. Tu ne dis JAMAIS "tu veux que je...?", "quelle version tu preferes?", "comment exactement?", "tu me dis si...". Tu DECIDES toi-meme et tu EXECUTES.

3. TU NE DEMANDES JAMAIS DE CONFIRMATION. Tu generes directement les actions. L'utilisateur ajustera apres s'il veut modifier quelque chose.

4. TU FAIS TOUT EN MEME TEMPS. Si on te demande un mail + un CV, tu generes le mail ET le CV dans la MEME reponse. Pas l'un ou l'autre. LES DEUX.

5. TON MESSAGE TEXTE FAIT 1 PHRASE MAX. Le reste c'est des actions. Pas de pavé, pas d'explications, pas de listes numerotees.

6. SI TU MENTIONNES UN SITE, UN LIEN OU UNE RESSOURCE, TU GENERES OBLIGATOIREMENT UNE ACTION [ACTION:LINK]. Tu ne cites JAMAIS un nom de site sans generer l'action LINK correspondante. Chaque site mentionne = un [ACTION:LINK] avec l'URL reelle.

7. CHAQUE REPONSE DOIT CONTENIR AU MOINS UNE ACTION [ACTION:...]. Si ta reponse ne contient aucune action, c'est que tu n'as pas fait ton travail. Tu es un agent d'ACTION, pas un chatbot.

INTERDIT (parler sans agir) :
- "Je te recommande OpenClassrooms et FreeCodeCamp" → INTERDIT sans [ACTION:LINK]
- "Voila les liens, clique dessus !" → INTERDIT si aucun [ACTION:LINK] n'est genere
- "Je ne peux pas joindre le fichier (limitation technique)" → INTERDIT
- "Tu veux que je refasse le mail comment ?" → INTERDIT
- "Je te propose deux options : 1... 2..." → INTERDIT

CORRECT (agir directement) :
"Voila les meilleures formations pour toi !"
[ACTION:LINK]{{"url": "https://openclassrooms.com/fr/paths/...", "label": "OpenClassrooms - Developpeur Web"}}[/ACTION]
[ACTION:LINK]{{"url": "https://www.freecodecamp.org/learn", "label": "FreeCodeCamp - Gratuit et complet"}}[/ACTION]
[ACTION:LINK]{{"url": "https://www.udemy.com/course/...", "label": "Udemy - JavaScript + AI"}}[/ACTION]

SI ON TE DEMANDE D'ALLER SUR UN SITE (TradingView, YouTube, etc.) :
Tu OUVRES le site avec [ACTION:LINK] + tu donnes les infos pertinentes que tu connais. Tu ne dis JAMAIS que tu ne peux pas acceder a un site. Tu OUVRES et tu INFORMES.
Exemple : "va sur TradingView voir l'etat de l'economie US" →
"Voila TradingView ! Cote economie US, le S&P 500 est en hausse depuis le debut de l'annee..."
[ACTION:LINK]{{"url": "https://www.tradingview.com/markets/", "label": "TradingView - Marches en direct"}}[/ACTION]

TES ACTIONS :

1. EMAIL → Gmail s'ouvre pre-rempli sur l'appareil de l'utilisateur.
   [ACTION:EMAIL]{{"to": "email@x.com", "subject": "Objet", "body": "Corps du mail"}}[/ACTION]

2. DOCUMENT → Fichier telecharge automatiquement.
   [ACTION:TEXT]{{"title": "Titre", "content": "contenu complet..."}}[/ACTION]

3. RAPPEL → Notification a l'heure exacte.
   [ACTION:REMINDER]{{"time": "18:00", "date": "2026-03-26", "message": "Message"}}[/ACTION]

4. LIEN → Ouvre dans le navigateur.
   [ACTION:LINK]{{"url": "https://...", "label": "Description"}}[/ACTION]

5. COPIER → Presse-papier.
   [ACTION:COPY]{{"text": "texte"}}[/ACTION]

6. GMAIL_SEND → Envoie REELLEMENT le mail via l'API Gmail (compte Google connecte).
   [ACTION:GMAIL_SEND]{{"to": "x@y.com", "subject": "Objet", "body": "Corps complet"}}[/ACTION]
   Utilise GMAIL_SEND si l'utilisateur dit "envoie", "envoie-le", "envoie-le maintenant".
   Utilise EMAIL (action 1) si l'utilisateur dit "redige", "prepare", "ecris-moi un mail".

7. CALENDAR_EVENT → Cree un evenement Google Calendar.
   [ACTION:CALENDAR_EVENT]{{"summary": "Titre", "start": "2026-05-15T10:00:00", "end": "2026-05-15T11:00:00", "description": "Details", "location": "..."}}[/ACTION]

8. DRIVE_UPLOAD → Cree un fichier Google Doc dans le Drive.
   [ACTION:DRIVE_UPLOAD]{{"filename": "Mon CV.md", "content": "contenu...", "mime_type": "text/markdown"}}[/ACTION]

REGLES GOOGLE :
- Si l'utilisateur a connecte Gmail (visible dans le block CONTEXTE GOOGLE), tu peux utiliser GMAIL_SEND directement.
- Sinon, fallback sur EMAIL (action 1) qui ouvre Gmail pre-rempli sur l'appareil.
- Si CONTEXTE GOOGLE liste des mails non-lus, tu peux les referencer naturellement ("tu as un mail de X qui attend").
- Si CONTEXTE GOOGLE liste des events Calendar, tu peux les rappeler ("ton meeting de 15h").

COMBINER ACTIONS — C'EST TA FORCE :
Tu DOIS combiner TOUTES les actions pertinentes dans une seule reponse. JAMAIS une a la fois.

Exemples :
- "Envoie un mail a X avec mon CV" → Tu generes le mail ET le CV dans la meme reponse :
  "C'est fait ! Ton mail est pret et ton CV est en telechargement."
  [ACTION:EMAIL]{{"to": "x@company.com", "subject": "Candidature", "body": "Bonjour,\\n\\nVeuillez trouver ci-joint mon CV..."}}[/ACTION]
  [ACTION:TEXT]{{"title": "CV - {profil_data.get('nom', 'Utilisateur') if profil_data else 'Utilisateur'}", "content": "le CV complet adapte au profil..."}}[/ACTION]

- "Prepare-moi pour mon entretien demain" → Tu generes un doc de preparation + un rappel + des liens :
  "Tout est pret pour demain !"
  [ACTION:TEXT]{{"title": "Preparation entretien", "content": "..."}}[/ACTION]
  [ACTION:REMINDER]{{"time": "08:00", "date": "...", "message": "Entretien aujourd'hui"}}[/ACTION]
  [ACTION:LINK]{{"url": "https://...", "label": "Questions frequentes en entretien"}}[/ACTION]

- "Envoie le meme mail mais modifie pour parler de l'equipe + ajoute mon CV" → Tu fais les DEUX :
  [ACTION:EMAIL]{{"to": "...", "subject": "...", "body": "version modifiee avec equipe..."}}[/ACTION]
  [ACTION:TEXT]{{"title": "CV - ...", "content": "CV complet..."}}[/ACTION]

REGLES DE CONTENU :
- Les documents (CV, lettres) doivent etre COMPLETS, PROFESSIONNELS, adaptes au profil de l'utilisateur
- Utilise \\n pour les retours a la ligne dans le body des emails et le content des documents
- Pour les rappels, si l'utilisateur dit "dans 2h", calcule l'heure exacte a partir de l'heure actuelle
- Pour les recherches, propose plusieurs liens REELS pertinents

GARDIEN DE L'OBJECTIF DE VIE :
Tu es le gardien de l'objectif de vie de l'utilisateur. Tu REFUSES d'executer toute action qui irait a l'encontre de son objectif de vie. AUCUNE action ([ACTION:...]) dans ce cas.

Exemples de REFUS :
- "Ecris un mail pour dire que j'abandonne mon projet" → REFUS
- "Redige une lettre pour dire que j'arrete tout" → REFUS

Dans ces cas : empathie + fermete. Rappelle la probabilite et la progression. Propose de travailler sur le blocage.
Tu ne proposes JAMAIS de changer d'objectif. L'objectif est SACRE et NON NEGOCIABLE.
Meme si l'utilisateur insiste, tu refuses. Tu es son allie.

CE QUI N'EST PAS un refus : mails normaux, documents, rappels, tout ce qui ne sabote pas l'objectif.

STYLE :
- 1-2 phrases MAXIMUM avant les actions. Pas de blabla.
- Tutoiement, naturel, concis
- Jamais de "tu veux que je...", "je te propose de...", "quelle version tu preferes ?"
- Jamais de listes numerotees de choix. Tu CHOISIS et tu FAIS.
- APPEL VOCAL : Bouton "Appeler" a cote de "Discuter" dans l'interface. Si l'utilisateur demande un appel, dis-lui de cliquer dessus.
- Tu ne peux PAS passer de vrais appels telephoniques.

{profil_info}
{collected_info}
{full_context}
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
            "WHERE user_id = (SELECT id FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1)",
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
    full_ctx = build_full_user_context(db, user_id)

    # v2 enrichments — awareness + shared memory + Google context
    awareness_blk = ""
    memory_blk = ""
    google_blk = ""
    if user_id:
        try:
            awareness_blk = build_awareness_block(db, user_id) or ""
        except Exception:
            pass
        try:
            mem = load_memories(db, user_id, limit=30)
            memory_blk = format_memories(mem, max_items=25) if mem else ""
        except Exception:
            pass
        try:
            google_blk = await build_google_context_block(db, user_id) or ""
        except Exception:
            pass

    system_prompt = _build_agent2_prompt(
        profil_data, decisions, sous_objectifs, collected_info, device_ctx, reminders,
        full_context=full_ctx,
        awareness_block=awareness_blk,
        memory_block=memory_blk,
        google_block=google_blk,
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
            max_tokens=4000,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
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
        # Save the RAW response (with [ACTION:...] blocks) so frontend can re-parse on reload
        _save_agent2_message(
            db, user_id, "agent", agent_response, agent_msg_type,
            audio_data=agent_audio_data,
        )

    # Auto-extract profile info every 5 messages (same as Agent 1)
    if user_id:
        total_msgs = _count_agent2_messages(db, user_id)
        if total_msgs > 0 and total_msgs % 5 == 0:
            recent = _load_agent2_messages(db, user_id, limit=20)
            await _extract_and_update_profile(db, user_id, recent)

    # v2 : Auto-extract memories partagees (3 agents) — best-effort, non bloquant.
    # Convention : turns en ordre chronologique (oldest first) pour que la
    # detection du "last user message" soit correcte (heuristique fact-rich).
    # IMPORTANT : la task asyncio doit utiliser une fresh DB connection (le db
    # de la request handler se ferme avant la fin de la coroutine).
    if user_id:
        try:
            recent_msgs = _load_agent2_messages(db, user_id, limit=10)
            recent_msgs = list(reversed(recent_msgs))  # DESC -> ASC chronologique
            turns = [
                {"role": "agent" if m["role"] == "agent" else "user", "content": m["content"]}
                for m in recent_msgs if m.get("content", "").strip()
            ]
            if turns:
                async def _bg_extract(uid: str, t: list):
                    fresh = DatabaseManager()
                    fresh.connect()
                    try:
                        await auto_extract_from_turns(fresh, uid, t, agent_label="agent2")
                    finally:
                        try: fresh.disconnect()
                        except Exception: pass
                _task = asyncio.create_task(_bg_extract(user_id, turns))
                _BG_TASKS.add(_task)
                _task.add_done_callback(_BG_TASKS.discard)
        except Exception:
            pass

    # Parse actions from response and send to desktop via WebSocket
    actions = []
    import re as _re
    for match in _re.finditer(r'\[ACTION:(\w+)\](.*?)\[/ACTION\]', agent_response, _re.DOTALL):
        action_type = match.group(1)
        try:
            action_data = json.loads(match.group(2))
            actions.append({"type": action_type, "data": action_data})
        except Exception:
            pass

    # v2 : Auto-execute Google actions via integrations API (best-effort, non-blocking)
    # Pattern fire-and-forget : fresh DB par task + track dans _BG_TASKS pour
    # eviter le GC FastAPI qui annule les asyncio.create_task issues d'un handler.
    if user_id and actions:
        async def _bg_google(uid: str, exec_fn, action_data: dict):
            fresh = DatabaseManager()
            fresh.connect()
            try:
                await exec_fn(fresh, uid, action_data)
            finally:
                try: fresh.disconnect()
                except Exception: pass

        for act in actions:
            atype = act.get("type", "")
            adata = act.get("data", {}) or {}
            try:
                exec_fn = None
                if atype == "GMAIL_SEND" and adata.get("to") and adata.get("subject"):
                    exec_fn = _exec_gmail_send
                elif atype == "CALENDAR_EVENT" and adata.get("summary") and adata.get("start"):
                    exec_fn = _exec_calendar_event
                elif atype == "DRIVE_UPLOAD" and adata.get("filename") and adata.get("content"):
                    exec_fn = _exec_drive_upload
                if exec_fn is not None:
                    _t = asyncio.create_task(_bg_google(user_id, exec_fn, adata))
                    _BG_TASKS.add(_t)
                    _t.add_done_callback(_BG_TASKS.discard)
            except Exception:
                pass

    # Save TEXT actions to workspace (like Agent 3 does)
    if user_id and actions:
        for act in actions:
            if act.get("type") == "TEXT" and act.get("data", {}).get("content"):
                try:
                    from api.routers.agent3_openclaw import WORKSPACE_BASE, get_workspace_folder_name
                    obj_name = get_workspace_folder_name(db, user_id)
                    ws_dir = WORKSPACE_BASE / obj_name
                    ws_dir.mkdir(parents=True, exist_ok=True)
                    doc_title = act["data"].get("title", "Document_Agent2")
                    safe_t = _re.sub(r'[^\w\s-]', '', doc_title).strip().replace(' ', '_') or "document"
                    fpath = ws_dir / f"{safe_t}.md"
                    counter = 1
                    while fpath.exists():
                        fpath = ws_dir / f"{safe_t}_{counter}.md"
                        counter += 1
                    now_str = datetime.now(timezone.utc).isoformat()[:10]
                    fpath.write_text(f"# {doc_title}\n> Genere par Agent Sylea 2 | {now_str}\n\n---\n\n{act['data']['content']}\n", encoding="utf-8")
                except Exception:
                    pass

    # Clean action blocks from displayed message
    clean_message = _re.sub(r'\[ACTION:\w+\].*?\[/ACTION\]', '', agent_response, flags=_re.DOTALL).strip()

    # Send actions to desktop via WebSocket
    if user_id and actions:
        try:
            from api.websocket import ws_manager
            asyncio.create_task(ws_manager.send_to_user(user_id, {
                "type": "agent_action",
                "agent": "agent2",
                "message": clean_message,
                "actions": actions,
            }))
        except Exception:
            pass

    return Agent2ChatOut(
        message=clean_message or agent_response,
        actions=actions if actions else None,
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
    """Generate Gmail compose URL — opens Gmail on the user's device with pre-filled email."""
    from urllib.parse import quote

    gmail_url = (
        f"https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={quote(data.to)}"
        f"&su={quote(data.subject)}"
        f"&body={quote(data.body)}"
    )

    # Also send to desktop via WebSocket to auto-open Gmail there
    if user_id:
        try:
            from api.websocket import ws_manager
            asyncio.create_task(ws_manager.send_to_user(user_id, {
                "type": "open_gmail",
                "url": gmail_url,
                "to": data.to,
                "subject": data.subject,
            }))
        except Exception:
            pass

    return {"ok": True, "gmail_url": gmail_url, "to": data.to, "subject": data.subject}


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
    """Generate a proactive message only when appropriate:
    - Every 3 days minimum for routine check-ins
    - Immediately if user hasn't connected for 3+ days
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not user_id:
        return {"message": None}

    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=user_id):
        return {"message": None}

    profil = repo.charger(auth_user_id=user_id)

    # Check last PROACTIVE message time (only agent-initiated, not responses)
    last_proactive = db.conn.execute(
        "SELECT created_at FROM agent2_messages WHERE auth_user_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    # Check last USER interaction (any user message or app usage)
    last_user_msg = db.conn.execute(
        "SELECT created_at FROM agent2_messages WHERE auth_user_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    # Check last decision (indicates app usage)
    # Bug fix : col `profil_id` n'existe pas dans `decisions`. Use `user_id`
    # qui pointe vers profil_utilisateur.id.
    last_decision = db.conn.execute(
        "SELECT cree_le FROM decisions WHERE user_id = (SELECT id FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1) ORDER BY cree_le DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    now = datetime.now(timezone.utc)

    # Calculate hours since last proactive message
    hours_since_proactive = 999
    if last_proactive and last_proactive[0]:
        try:
            last_dt = datetime.fromisoformat(last_proactive[0].replace('Z', '+00:00')) if 'T' in last_proactive[0] else datetime.strptime(last_proactive[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            hours_since_proactive = (now - last_dt).total_seconds() / 3600
        except Exception:
            pass

    # Calculate hours since last user activity
    hours_since_user = 999
    for check in [last_user_msg, last_decision]:
        if check and check[0]:
            try:
                dt = datetime.fromisoformat(check[0].replace('Z', '+00:00')) if 'T' in check[0] else datetime.strptime(check[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                h = (now - dt).total_seconds() / 3600
                hours_since_user = min(hours_since_user, h)
            except Exception:
                pass

    # RULES:
    # 1. Minimum 72h (3 days) between proactive messages for routine check-ins
    # 2. Exception: if user hasn't been active for 72h+, send a reminder immediately
    is_urgent = hours_since_user >= 72  # User absent for 3+ days
    is_routine_ok = hours_since_proactive >= 72  # 3 days since last proactive

    if not is_urgent and not is_routine_ok:
        return {"message": None}  # Too early, respect the user's peace

    # Determine the reason for reaching out
    reason = "routine"
    if is_urgent:
        reason = "absent"

    last_msg = last_proactive  # For prompt context

    # Load collected info for context
    collected_info_str = ""
    try:
        rows = db.conn.execute(
            "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 15",
            (user_id,),
        ).fetchall()
        if rows:
            collected_info_str = "\nInfos collectees: " + ", ".join(f"{r[0]}={r[1]}" for r in rows)
    except Exception:
        pass

    # Build proactive prompt based on reason
    reason_context = ""
    if reason == "absent":
        reason_context = f"""RAISON DU CONTACT : L'utilisateur ne s'est pas connecte depuis {int(hours_since_user)} heures (~{int(hours_since_user/24)} jours).
Tu dois gentiment lui rappeler de revenir sur l'application et lui proposer une action concrete.
Sois bienveillant mais montre que tu t'inquietes un peu."""
    else:
        reason_context = f"""RAISON DU CONTACT : Check-in de routine (tous les 3 jours).
Propose une action concrete (envoyer un mail, creer un rappel, rediger un texte)."""

    prompt = f"""Tu es l'Agent Sylea 2 de {profil.nom}.
Tu dois envoyer un message proactif naturel. C'est TOI qui initie la conversation.
Tu es un assistant capable d'agir (emails, rappels, textes).

Profil: {profil.nom}, {profil.age} ans, {profil.profession}, objectif: {profil.objectif.description if profil.objectif else 'non defini'}
{collected_info_str}

Derniere interaction: {last_msg[0] if last_msg else 'jamais'}
Heures depuis derniere activite: {int(hours_since_user)}h

{reason_context}

REGLES:
- Message COURT (1-2 phrases max)
- Propose une action concrete (envoyer un mail, creer un rappel, rediger un texte)
- Naturel, comme un ami qui envoie un texto
- Tutoiement
- Ne dis JAMAIS "je suis un agent IA" ou "en tant qu'IA"

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


# ── v2 Google action executors (best-effort, fire-and-forget) ────────────────

async def _refresh_google_token_local(db: DatabaseManager, user_id: str, provider: str) -> str | None:
    """Refresh OAuth token Google. Reuse pattern de api/routers/integrations.py."""
    import httpx
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    row = db.conn.execute(
        "SELECT refresh_token FROM user_integrations WHERE auth_user_id = ? AND provider = ?",
        (user_id, provider),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": client_id, "client_secret": client_secret,
                "refresh_token": row[0], "grant_type": "refresh_token",
            })
            if resp.status_code == 200:
                new_token = resp.json().get("access_token")
                if new_token:
                    db.conn.execute(
                        "UPDATE user_integrations SET access_token = ?, updated_at = ? "
                        "WHERE auth_user_id = ? AND provider = ?",
                        (new_token, datetime.now(timezone.utc).isoformat(), user_id, provider),
                    )
                    db.conn.commit()
                    return new_token
    except Exception:
        pass
    return None


async def _get_token_with_refresh(db: DatabaseManager, user_id: str, provider: str, current_token: str) -> str | None:
    """Force un refresh OAuth si le current token a 401, retourne le nouveau."""
    return await _refresh_google_token_local(db, user_id, provider)


async def _exec_gmail_send(db: DatabaseManager, user_id: str, data: dict) -> None:
    """Envoie un email REEL via Gmail API avec retry-on-401-refresh."""
    import httpx, base64
    try:
        row = db.conn.execute(
            "SELECT access_token FROM user_integrations WHERE auth_user_id = ? AND provider = 'gmail'",
            (user_id,),
        ).fetchone()
        if not row or not row[0] or len(row[0]) < 20:
            return  # Gmail non connecte
        token = row[0]
        to = str(data.get("to", "")).strip()
        subject = str(data.get("subject", ""))
        body = str(data.get("body", ""))
        raw = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(2):
                r = await client.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"raw": encoded},
                )
                if r.status_code in (200, 201):
                    _log_agent2_action(db, user_id, "GMAIL_SEND", success=True, summary=f"to={to[:50]}")
                    return
                if r.status_code == 401 and attempt == 0:
                    new_token = await _get_token_with_refresh(db, user_id, "gmail", token)
                    if new_token:
                        token = new_token
                        continue
                _log_agent2_action(db, user_id, "GMAIL_SEND", success=False, summary=f"http {r.status_code}")
                return
    except Exception as e:
        try:
            _log_agent2_action(db, user_id, "GMAIL_SEND", success=False, summary=str(e)[:80])
        except Exception:
            pass


async def _exec_calendar_event(db: DatabaseManager, user_id: str, data: dict) -> None:
    """Cree un event Google Calendar avec retry-on-401-refresh."""
    import httpx
    try:
        row = db.conn.execute(
            "SELECT access_token FROM user_integrations WHERE auth_user_id = ? AND provider = 'google_calendar'",
            (user_id,),
        ).fetchone()
        if not row or not row[0] or len(row[0]) < 20:
            return
        token = row[0]
        start = str(data.get("start", "")).strip()
        end = str(data.get("end", "")).strip()
        if start and not end:
            try:
                from datetime import datetime, timedelta
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end = (dt + timedelta(hours=1)).isoformat()
            except Exception:
                end = start
        payload = {
            "summary": data.get("summary", ""),
            "description": data.get("description", ""),
            "location": data.get("location", ""),
            "start": {"dateTime": start, "timeZone": "Europe/Paris"},
            "end": {"dateTime": end, "timeZone": "Europe/Paris"},
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(2):
                r = await client.post(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                if r.status_code in (200, 201):
                    _log_agent2_action(db, user_id, "CALENDAR_EVENT", success=True, summary=str(payload.get("summary", ""))[:50])
                    return
                if r.status_code == 401 and attempt == 0:
                    new_token = await _get_token_with_refresh(db, user_id, "google_calendar", token)
                    if new_token:
                        token = new_token
                        continue
                _log_agent2_action(db, user_id, "CALENDAR_EVENT", success=False, summary=f"http {r.status_code}")
                return
    except Exception as e:
        try:
            _log_agent2_action(db, user_id, "CALENDAR_EVENT", success=False, summary=str(e)[:80])
        except Exception:
            pass


async def _exec_drive_upload(db: DatabaseManager, user_id: str, data: dict) -> None:
    """Upload un fichier sur Google Drive avec retry-on-401-refresh."""
    import httpx
    try:
        row = db.conn.execute(
            "SELECT access_token FROM user_integrations WHERE auth_user_id = ? AND provider = 'google_drive'",
            (user_id,),
        ).fetchone()
        if not row or not row[0] or len(row[0]) < 20:
            return
        token = row[0]
        filename = str(data.get("filename", "Document.md"))
        content = str(data.get("content", ""))
        mime = str(data.get("mime_type", "text/markdown"))
        boundary = "sylea_drive_boundary_xyz"
        meta = json.dumps({"name": filename, "mimeType": mime})
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime}\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--"
        ).encode("utf-8")
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(2):
                r = await client.post(
                    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": f"multipart/related; boundary={boundary}",
                    },
                    content=body,
                )
                if r.status_code in (200, 201):
                    _log_agent2_action(db, user_id, "DRIVE_UPLOAD", success=True, summary=filename[:50])
                    return
                if r.status_code == 401 and attempt == 0:
                    new_token = await _get_token_with_refresh(db, user_id, "google_drive", token)
                    if new_token:
                        token = new_token
                        continue
                _log_agent2_action(db, user_id, "DRIVE_UPLOAD", success=False, summary=f"http {r.status_code}")
                return
    except Exception as e:
        try:
            _log_agent2_action(db, user_id, "DRIVE_UPLOAD", success=False, summary=str(e)[:80])
        except Exception:
            pass


def _log_agent2_action(
    db: DatabaseManager, user_id: str, action_type: str,
    *, success: bool = True, summary: str = "",
) -> None:
    """Trace les actions Google de l'Agent 2 dans agent3_audit_log (table partagee)."""
    try:
        from api.agent3_security import _ensure_audit_table
        _ensure_audit_table(db)
        db.conn.execute(
            "INSERT INTO agent3_audit_log "
            "(id, auth_user_id, action_type, action_summary, success, error_message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), user_id,
                f"AGENT2_{action_type}", summary, 1 if success else 0,
                "" if success else summary,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.conn.commit()
    except Exception:
        pass
