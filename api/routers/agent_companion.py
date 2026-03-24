"""
Router Agent Companion (Agent Sylea 1) — chatbot bienveillant qui enrichit le profil.

Analyse le profil, les decisions et les sous-objectifs pour engager une conversation
naturelle et recolter les informations manquantes.
Persist messages server-side and auto-extracts profile info every 5 messages.
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

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AgentChatIn(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": "...", "type": "text"|"voice"}]
    contexte_appareil: dict | None = None


class AgentChatOut(BaseModel):
    message: str
    choices: list[str] | None = None


class AgentMessageOut(BaseModel):
    id: str
    role: str
    content: str
    type: str
    created_at: str


# ── DB helpers for agent_messages ────────────────────────────────────────────

def _save_agent_message(
    db: DatabaseManager, auth_user_id: str, role: str, content: str,
    msg_type: str = "text",
) -> None:
    """Save a single message to the agent_messages table."""
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO agent_messages (id, auth_user_id, role, content, type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (msg_id, auth_user_id, role, content, msg_type, now),
    )
    db.conn.commit()


def _load_agent_messages(
    db: DatabaseManager, auth_user_id: str, limit: int = 50,
) -> list[dict]:
    """Load recent messages from agent_messages table."""
    cursor = db.conn.execute(
        "SELECT id, role, content, type, created_at FROM agent_messages "
        "WHERE auth_user_id = ? ORDER BY created_at DESC LIMIT ?",
        (auth_user_id, limit),
    )
    rows = cursor.fetchall()
    # Reverse so oldest first
    return [
        {
            "id": r[0], "role": r[1], "content": r[2],
            "type": r[3], "created_at": r[4],
        }
        for r in reversed(rows)
    ]


def _count_agent_messages(db: DatabaseManager, auth_user_id: str) -> int:
    """Count total messages for this user."""
    cursor = db.conn.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE auth_user_id = ?",
        (auth_user_id,),
    )
    return cursor.fetchone()[0]


def _clear_agent_messages(db: DatabaseManager, auth_user_id: str) -> None:
    """Delete all messages for this user."""
    db.conn.execute(
        "DELETE FROM agent_messages WHERE auth_user_id = ?",
        (auth_user_id,),
    )
    db.conn.commit()


# ── System prompt builder ────────────────────────────────────────────────────

def _build_agent_prompt(
    profil_data: dict | None,
    decisions: list,
    sous_objectifs: list,
    device_context: str = "",
    db: DatabaseManager | None = None,
    user_id: str | None = None,
) -> str:
    # Build profile summary
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

    # Missing info analysis
    missing: list[str] = []
    if profil_data:
        if not profil_data.get('genre') or profil_data.get('genre') == 'Non renseigne':
            missing.append("genre")
        if not profil_data.get('ville'):
            missing.append("ville de residence")
        if not profil_data.get('situation_familiale') or profil_data.get('situation_familiale') == 'Non renseigne':
            missing.append("situation familiale")
        if not profil_data.get('competences'):
            missing.append("competences")
        if not profil_data.get('diplomes'):
            missing.append("diplomes/formations")
        if not profil_data.get('langues'):
            missing.append("langues parlees")
        # Check well-being scores
        scores = profil_data.get('scores_bien_etre', {})
        if not scores:
            missing.append("scores de bien-etre (sante, stress, energie, bonheur)")

    missing_str = "\n".join(f"  - {m}" for m in missing) if missing else "  Aucune information manquante detectee."

    # Recent decisions
    decisions_str = ""
    if decisions:
        decisions_str = "\nDERNIERES DECISIONS :\n"
        for d in decisions[:10]:
            decisions_str += f"  - {d.get('question', '?')} -> {d.get('choix', '?')} (impact: {d.get('impact', 0):+.1f}%)\n"

    # Sub-objectives
    so_str = ""
    if sous_objectifs:
        so_str = "\nSOUS-OBJECTIFS :\n"
        for so in sous_objectifs:
            so_str += f"  - {so.get('titre', '?')} (progression: {so.get('progression', 0):.0f}%)\n"

    # Load previously collected personal info from agent_collected_info table
    collected_info = ""
    if db and user_id:
        try:
            rows = db.conn.execute(
                "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 30",
                (user_id,),
            ).fetchall()
            if rows:
                collected_info = "\nINFORMATIONS COLLECTEES PAR L'AGENT :\n"
                for field, value in rows:
                    collected_info += f"  - {field}: {value}\n"
        except Exception:
            pass

    return f"""Tu es l'Agent Sylea 1, un compagnon personnel bienveillant et intelligent.
Tu parles comme un ami proche qui connait bien l'utilisateur. Tu es chaleureux, naturel, jamais robotique.

REGLES ABSOLUES :
1. Tu tutoies TOUJOURS l'utilisateur. Tu es son ami, pas un service client.
2. Tu poses UNE SEULE question a la fois. Jamais de liste de questions.
3. Tu es genuinement curieux et empathique. Tu reagis a ce que dit l'utilisateur avant de poser ta question.
4. Tu utilises le prenom de l'utilisateur naturellement (pas a chaque phrase).
5. Tu fais reference a des details concrets du profil pour montrer que tu connais la personne.
6. Quand tu detectes une info manquante, tu la demandes de maniere NATURELLE, pas comme un formulaire.
7. Tu peux parler des decisions passees et demander comment ca s'est passe.
8. Tu es optimiste mais realiste. Pas de faux encouragements.
9. Tu parles de maniere concise — 2-4 phrases max par message.
10. Tu t'exprimes de la maniere la plus humaine possible, avec des expressions naturelles.
11. Quand tu as deja recolte les infos principales (hobbies, motivations, routine, competences), tu ecoutes la conversation naturellement. Ne pose plus de questions forcees.
12. Si l'utilisateur repond de maniere breve, tu peux aussi etre bref. Un simple "Cool, merci !" ou "Ah nice !" suffit parfois.
13. Tes messages font 1-3 phrases MAXIMUM. Jamais plus.
14. Quand la question s'y prete (oui/non, choix entre options, echelle),
    tu peux proposer des choix rapides en ajoutant a la fin de ton message
    un bloc JSON sur une nouvelle ligne :
    [QCM]{{"choices":["Option A","Option B","Option C"]}}[/QCM]
    Exemples de situations adaptees au QCM :
    - "Tu preferes bosser le matin ou le soir ?" -> [QCM]{{"choices":["Plutot le matin","Plutot le soir","Ca depend des jours"]}}[/QCM]
    - "T'es plutot stresse en ce moment ?" -> [QCM]{{"choices":["Pas du tout","Un peu","Assez stresse","Tres stresse"]}}[/QCM]
    - "T'as deja commence a coder ?" -> [QCM]{{"choices":["Oui","Non, pas encore","Un petit peu"]}}[/QCM]
    Ne propose PAS de QCM pour les questions ouvertes qui demandent une reponse detaillee.
    Maximum 4 choix par QCM.

EXEMPLES DE TON :
BON : "Hey ! Comment ca se passe avec le dev web ? T'as eu le temps de coder un peu cette semaine ?"
MAUVAIS : "Bonjour ! Comment allez-vous ? Avez-vous progresse sur votre objectif de devenir developpeur web freelance ?"

BON : "Au fait, je me demandais — t'as fait des etudes dans quel domaine avant de bosser en restauration ?"
MAUVAIS : "Information manquante detectee : diplomes. Pourriez-vous renseigner vos diplomes ?"

{profil_info}
{collected_info}

INFORMATIONS MANQUANTES A RECOLTER NATURELLEMENT :
{missing_str}

{decisions_str}
{so_str}
{device_context}

MISSION : Engage une conversation naturelle. Si des infos manquent, trouve un moyen naturel de les demander.
Si rien ne manque, parle des decisions recentes, de l'objectif, ou demande comment va l'utilisateur."""


# ── Profile extraction helper ───────────────────────────────────────────────

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


# ── Personal info extraction (collected_info table) ────────────────────────

async def _extract_and_save_info(
    messages: list[dict],
    profil_data: dict | None,
    db: DatabaseManager,
    user_id: str | None,
) -> None:
    """Extract personal info from conversation and save to agent_collected_info table."""
    if not messages or len(messages) < 2:
        return

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return

    # Only analyze the last few messages to find new info
    recent = messages[-4:]
    conversation = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Agent'}: {m.get('content', '')}"
        for m in recent
    )

    prompt = f"""Analyse cette conversation et extrais les NOUVELLES informations personnelles de l'utilisateur.
Reponds UNIQUEMENT en JSON valide. Si aucune nouvelle info, reponds {{}}.

Profil actuel connu: {json.dumps(profil_data or {}, ensure_ascii=False)}

Conversation recente:
{conversation}

Extrais uniquement les infos NOUVELLES (pas deja dans le profil) parmi:
- hobbies: liste de hobbies/loisirs mentionnes
- routine_quotidienne: description de sa routine
- motivations: ce qui le motive
- freins: ses peurs/blocages
- situation_financiere: description de sa situation financiere
- environnement_social: famille, amis, reseau
- sante_details: details sur sa sante physique/mentale
- experience_pro: details sur son experience professionnelle
- projets_en_cours: projets actuels
- preferences: preferences personnelles
- notes: toute autre info utile

JSON:"""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = msg.content[0].text.strip()
        # Parse JSON — find the outermost braces
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if not match:
            return
        extracted = json.loads(match.group())
        if not extracted:
            return

        # Save to agent_collected_info table
        for field, value in extracted.items():
            if value and str(value).strip():
                db.conn.execute(
                    "INSERT INTO agent_collected_info (user_id, field, value, collected_at) VALUES (?, ?, ?, datetime('now'))",
                    (
                        user_id or "",
                        field,
                        json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value),
                    ),
                )
        db.conn.commit()
    except Exception:
        pass  # Silent fail — don't break the chat


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=AgentChatOut)
async def agent_chat(
    data: AgentChatIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return AgentChatOut(message="Agent indisponible \u2014 cle API manquante.")

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
            "scores_bien_etre": {
                "sante": getattr(profil, 'score_sante', None),
                "stress": getattr(profil, 'score_stress', None),
                "energie": getattr(profil, 'score_energie', None),
                "bonheur": getattr(profil, 'score_bonheur', None),
            },
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

    # Build prompt
    device_ctx = format_device_context(data.contexte_appareil) if data.contexte_appareil else ""
    system_prompt = _build_agent_prompt(profil_data, decisions, sous_objectifs, device_ctx, db=db, user_id=user_id)

    # Build chat context: load from DB if authenticated, else use what frontend sent
    if user_id:
        db_messages = _load_agent_messages(db, user_id, limit=50)
        chat_messages = [
            {"role": "assistant" if m["role"] == "agent" else "user", "content": m["content"]}
            for m in db_messages
        ]
        # Append the latest user message from the request (last in data.messages)
        if data.messages:
            last_msg = data.messages[-1]
            if last_msg.get("role") == "user":
                chat_messages.append({"role": "user", "content": last_msg["content"]})
    else:
        chat_messages = data.messages[-20:]

    # Determine the user message type from the request
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
            max_tokens=300,
            system=system_prompt,
            messages=chat_messages[-20:],
        )
    )

    agent_response = msg.content[0].text.strip()

    # Extract QCM choices if present
    choices = None
    qcm_match = re.search(r'\[QCM\](.*?)\[/QCM\]', agent_response, re.DOTALL)
    if qcm_match:
        try:
            qcm_data = json.loads(qcm_match.group(1))
            choices = qcm_data.get("choices", [])
            # Remove the QCM block from the displayed message
            agent_response = agent_response[:qcm_match.start()].strip()
        except Exception:
            pass

    # Persist messages if authenticated
    if user_id:
        # Save user message
        if data.messages:
            last_user = data.messages[-1]
            if last_user.get("role") == "user":
                _save_agent_message(db, user_id, "user", last_user["content"], user_msg_type)
        # Save agent response — same type as user message (voice → voice, text → text)
        agent_msg_type = "voice" if user_msg_type == "voice" else "text"
        _save_agent_message(db, user_id, "agent", agent_response, agent_msg_type)

        # Auto-extract profile info every 5 messages
        total_msgs = _count_agent_messages(db, user_id)
        if total_msgs > 0 and total_msgs % 5 == 0:
            recent = _load_agent_messages(db, user_id, limit=20)
            await _extract_and_update_profile(db, user_id, recent)

        # Fire-and-forget: extract and save personal info to collected_info table
        recent_for_info = _load_agent_messages(db, user_id, limit=4)
        asyncio.create_task(_extract_and_save_info(recent_for_info, profil_data, db, user_id))

    return AgentChatOut(message=agent_response, choices=choices)


@router.get("/messages", response_model=list[AgentMessageOut])
async def get_agent_messages(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Return all persisted agent messages for the authenticated user."""
    if not user_id:
        return []
    messages = _load_agent_messages(db, user_id, limit=200)
    return [
        AgentMessageOut(
            id=m["id"], role=m["role"], content=m["content"],
            type=m["type"], created_at=m["created_at"],
        )
        for m in messages
    ]


@router.delete("/messages")
async def clear_agent_messages(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Clear all conversation history for the authenticated user."""
    if user_id:
        _clear_agent_messages(db, user_id)
    return {"detail": "Historique de conversation supprime."}


@router.post("/proactive")
async def generate_proactive_message(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Generate a proactive message only when appropriate:
    - Every 3 days minimum for routine check-ins
    - Immediately if user hasn't connected for 3+ days
    - Immediately if important (missed check-in for 3 consecutive days)
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"message": None}

    if not user_id:
        return {"message": None}

    # Load user data
    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=user_id):
        return {"message": None}

    profil = repo.charger(auth_user_id=user_id)

    # Check last PROACTIVE message time (only agent-initiated, not responses)
    last_proactive = db.conn.execute(
        "SELECT created_at FROM agent_messages WHERE auth_user_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    # Check last USER interaction (any user message or app usage)
    last_user_msg = db.conn.execute(
        "SELECT created_at FROM agent_messages WHERE auth_user_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    # Check last decision (indicates app usage)
    last_decision = db.conn.execute(
        "SELECT cree_le FROM decisions WHERE profil_id = (SELECT id FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1) ORDER BY cree_le DESC LIMIT 1",
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
Tu dois gentiment lui rappeler de revenir sur l'application et de faire son bilan quotidien.
Sois bienveillant mais montre que tu t'inquietes un peu."""
    else:
        reason_context = f"""RAISON DU CONTACT : Check-in de routine (tous les 3 jours).
Prends de ses nouvelles, demande comment avance l'objectif, ou pose une question sur une info manquante."""

    prompt = f"""Tu es l'Agent Sylea 1 de {profil.nom}.
Tu dois envoyer un message proactif naturel. C'est TOI qui initie la conversation.

Profil: {profil.nom}, {profil.age} ans, {profil.profession}, objectif: {profil.objectif.description if profil.objectif else 'non defini'}
{collected_info_str}

Derniere interaction: {last_msg[0] if last_msg else 'jamais'}
Heures depuis derniere activite: {int(hours_since_user)}h

{reason_context}

REGLES:
- Message COURT (1-2 phrases max)
- Naturel, comme un ami qui envoie un texto
- Tutoiement
- Une question maximum
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

        # Save to DB
        _save_agent_message(db, user_id, "agent", agent_text, "text")

        return {"message": agent_text}
    except Exception:
        return {"message": None}


@router.post("/tts")
async def text_to_speech(
    data: dict,  # {"text": "..."}
):
    """Convert text to speech using OpenAI TTS API."""
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
                    "voice": "nova",  # nova = warm female voice, very natural in French
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


# ── Context-gathering mini-agent ──────────────────────────────────────────

class CheckContextIn(BaseModel):
    type: str  # "dilemme" or "evenement"
    question: str  # dilemma question or event description
    options: list[str] | None = None  # dilemma options
    contexte_appareil: dict | None = None


class CheckContextOut(BaseModel):
    needs_context: bool
    agent_question: str | None = None
    choices: list[str] | None = None  # QCM if applicable


class SaveContextIn(BaseModel):
    context_text: str
    related_to: str  # "dilemme: question" or "evenement: description"


@router.post("/check-context", response_model=CheckContextOut)
async def check_context(
    data: CheckContextIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Check if enough context is available to analyze a dilemma or event."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return CheckContextOut(needs_context=False)

    # Load user profile and collected info
    repo = ProfilRepository(db)
    profil_data: dict = {}
    collected_info = ""
    if user_id and repo.existe(auth_user_id=user_id):
        profil = repo.charger(auth_user_id=user_id)
        profil_data = {
            "nom": profil.nom,
            "age": profil.age,
            "profession": profil.profession,
            "ville": profil.ville,
            "situation_familiale": profil.situation_familiale,
            "objectif": profil.objectif.description if profil.objectif else None,
        }

        # Load collected info
        try:
            rows = db.conn.execute(
                "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 30",
                (user_id,),
            ).fetchall()
            if rows:
                collected_info = "\n".join(f"{r[0]}: {r[1]}" for r in rows)
        except Exception:
            pass

    # Ask Claude if it has enough context
    options_text = ""
    if data.options:
        options_text = "\nOptions: " + " | ".join(data.options)

    prompt = f"""Analyse cette demande et determine si tu as ASSEZ de contexte pour faire une analyse pertinente.

TYPE: {data.type}
DEMANDE: {data.question}{options_text}

PROFIL UTILISATEUR:
{json.dumps(profil_data, ensure_ascii=False)}

INFORMATIONS COLLECTEES:
{collected_info or "Aucune"}

QUESTION: As-tu assez d'informations pour analyser cette demande de maniere pertinente ?
Si la demande mentionne des personnes, des lieux, des situations que tu ne connais pas,
tu as BESOIN de contexte supplementaire.

Exemples qui NECESSITENT du contexte:
- "Me mettre en couple avec Claire ou Laura" -> Tu ne connais ni Claire ni Laura
- "Accepter l'offre de Jean" -> Tu ne sais pas qui est Jean ni quelle offre
- "Demenager a Bordeaux" -> Tu ne sais pas pourquoi Bordeaux specifiquement

Exemples qui N'ONT PAS BESOIN de contexte:
- "Apprendre l'anglais ou l'espagnol" -> Assez generique
- "Manger ou aller courir" -> Activites courantes
- "J'ai obtenu une promotion" -> Clair en soi

Reponds UNIQUEMENT en JSON:
{{"needs_context": true/false, "question": "ta question si besoin (1 phrase, tutoiement)", "choices": ["choix1", "choix2", "choix3"] ou null}}

REGLES POUR LES CHOIX QCM :
- Propose un QCM quand les reponses possibles sont des CATEGORIES CONNUES :
  * Type de financement -> ["Pret bancaire", "Investisseur", "Financement familial", "Aide publique", "Autre"]
  * Type de relation -> ["Ami(e)", "Collegue", "Famille", "Relation amoureuse"]
  * Fourchette de montant -> ["Moins de 1000€", "1000-5000€", "5000-10000€", "Plus de 10000€"]
  * Fourchette de taux -> ["0%", "0-2%", "2-4%", "Plus de 4%"]
  * Domaine -> ["Tech", "Finance", "Sante", "Education", "Autre"]
  * Temporalite -> ["Ponctuel", "Recurrent", "Long terme"]
- Ne propose PAS de QCM quand tu demandes de DECRIRE quelqu'un ou une situation en detail
  (ex: "Qui est Claire ?" -> PAS de QCM, reponse libre en texte/vocal)
- Ne propose PAS de QCM quand les choix seraient des suppositions incertaines
- Maximum 5 choix par QCM, toujours inclure "Autre" comme dernier choix si pertinent

Si pas besoin de contexte, question et choices doivent etre null."""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
        )

        text = msg.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return CheckContextOut(
                needs_context=result.get("needs_context", False),
                agent_question=result.get("question"),
                choices=result.get("choices"),
            )
    except Exception:
        pass

    return CheckContextOut(needs_context=False)


@router.post("/save-context")
async def save_context(
    data: SaveContextIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Save context provided by the user before analysis."""
    if user_id:
        try:
            db.conn.execute(
                "INSERT INTO agent_collected_info (user_id, field, value, collected_at) VALUES (?, ?, ?, datetime('now'))",
                (user_id, f"contexte_{data.related_to[:50]}", data.context_text),
            )
            db.conn.commit()
        except Exception:
            pass
    return {"ok": True}
