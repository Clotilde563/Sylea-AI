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

from api.context_helper import format_device_context, build_full_user_context_async
from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

# v2 enrichments : shared memory + awareness (partages avec Agent 2 + Agent 3)
try:
    from api.agent_shared_memory import (
        load_memories_async,
        save_memory_async,
        delete_memory_async,
        format_memories, auto_extract_from_turns,
    )
except Exception:
    async def load_memories_async(*a, **k): return []
    async def save_memory_async(*a, **k): return None
    async def delete_memory_async(*a, **k): return False
    format_memories = lambda m, **k: ""
    async def auto_extract_from_turns(*a, **k): return []
try:
    from api.agent3_awareness import build_awareness_block_async
except Exception:
    async def build_awareness_block_async(user_id): return ""

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Track background tasks (avoid GC FastAPI annulant asyncio.create_task)
_BG_TASKS: set = set()


# ── Schemas ──────────────────────────────────────────────────────────────────

class AgentChatIn(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": "...", "type": "text"|"voice"}]
    contexte_appareil: dict | None = None
    audio_data: str | None = None  # base64 encoded audio for the last user message


class AgentChatOut(BaseModel):
    message: str
    choices: list[str] | None = None
    audioData: str | None = None  # base64 mp3 for agent voice response
    # Proposition d'enregistrement officiel (event/decision majeure) detectee
    # par l'agent. Si presente, le frontend affiche une card avec boutons
    # Confirmer/Refuser sous le message.
    proposal: dict | None = None


class AgentMessageOut(BaseModel):
    id: str
    role: str
    content: str
    type: str
    created_at: str
    audioData: str = ""


# ── DB helpers for agent_messages ────────────────────────────────────────────
# Migration PG (2026-05-13) : versions async via SQLAlchemy text() —
# compatible SQLite + PostgreSQL. La caller (endpoint async) doit await.

async def _save_agent_message_async(
    auth_user_id: str, role: str, content: str,
    msg_type: str = "text", audio_data: str = "",
) -> None:
    """Save a single message to the agent_messages table (async)."""
    from sqlalchemy import text
    from api.database import get_session_factory
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO agent_messages "
                    "(id, auth_user_id, role, content, type, created_at, audio_data) "
                    "VALUES (:id, :uid, :role, :content, :type, :created_at, :audio)"
                ),
                {
                    "id": msg_id, "uid": auth_user_id, "role": role,
                    "content": content, "type": msg_type,
                    "created_at": now, "audio": audio_data or "",
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _load_agent_messages_async(
    auth_user_id: str, limit: int = 50,
) -> list[dict]:
    """Load recent messages from agent_messages table (async)."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, role, content, type, created_at, audio_data "
                    "FROM agent_messages WHERE auth_user_id = :uid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"uid": auth_user_id, "limit": limit},
            )
            rows = list(result.mappings().all())
        except Exception:
            # Fallback si audio_data n'existe pas (schema migration en cours)
            result = await session.execute(
                text(
                    "SELECT id, role, content, type, created_at "
                    "FROM agent_messages WHERE auth_user_id = :uid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"uid": auth_user_id, "limit": limit},
            )
            rows = [
                {**dict(r), "audio_data": ""}
                for r in result.mappings().all()
            ]
    # Reverse so oldest first
    return [
        {
            "id": r["id"], "role": r["role"], "content": r["content"],
            "type": r["type"], "created_at": r["created_at"],
            "audio_data": r.get("audio_data") or "",
        }
        for r in reversed(rows)
    ]


async def _count_agent_messages_async(auth_user_id: str) -> int:
    """Count total messages for this user (async)."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM agent_messages WHERE auth_user_id = :uid"),
            {"uid": auth_user_id},
        )
        return int(result.scalar() or 0)


async def _clear_agent_messages_async(auth_user_id: str) -> None:
    """Delete all messages for this user (async)."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text("DELETE FROM agent_messages WHERE auth_user_id = :uid"),
                {"uid": auth_user_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── System prompt builder ────────────────────────────────────────────────────

async def _load_collected_info_async(user_id: str, limit: int = 30) -> list[tuple[str, str]]:
    """Async sibling: load (field, value) rows from agent_collected_info.

    Migration PG (2026-05-13) — replaces inline db.conn.execute calls in
    _build_agent_prompt and proactive endpoints.
    """
    if not user_id:
        return []
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT field, value FROM agent_collected_info "
                    "WHERE user_id = :uid ORDER BY collected_at DESC LIMIT :lim"
                ),
                {"uid": user_id, "lim": int(limit)},
            )
            return [(r["field"], r["value"]) for r in result.mappings().all()]
    except Exception:
        return []


def _build_agent_prompt(
    profil_data: dict | None,
    decisions: list,
    sous_objectifs: list,
    device_context: str = "",
    db: DatabaseManager | None = None,
    user_id: str | None = None,
    full_context: str = "",
    awareness_block: str = "",
    memory_block: str = "",
    collected_info_rows: list[tuple[str, str]] | None = None,
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
- Progression vers l'objectif : {profil_data.get('probabilite_actuelle', 0):.1f}% (temps parcouru / temps total)
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

    # Load previously collected personal info from agent_collected_info table.
    # Migration PG : on attend que l'appelant ait pre-charge via
    # _load_collected_info_async (le seul caller le fait deja). Plus de
    # fallback sync.
    collected_info = ""
    rows: list[tuple[str, str]] = list(collected_info_rows or [])
    if rows:
        collected_info = "\nINFORMATIONS COLLECTEES PAR L'AGENT :\n"
        for field, value in rows:
            collected_info += f"  - {field}: {value}\n"

    awareness_section = (awareness_block + "\n") if awareness_block else ""
    memory_section = (memory_block + "\n") if memory_block else ""

    return f"""{awareness_section}{memory_section}Tu es l'Agent Sylea 1, un compagnon personnel bienveillant et intelligent.
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
14. Ne propose JAMAIS de choix multiples ou de QCM. Pose toujours des questions ouvertes pour avoir des reponses precises et detaillees.

EXEMPLES DE TON :
BON : "Hey ! Comment ca se passe avec le dev web ? T'as eu le temps de coder un peu cette semaine ?"
MAUVAIS : "Bonjour ! Comment allez-vous ? Avez-vous progresse sur votre objectif de devenir developpeur web freelance ?"

BON : "Au fait, je me demandais — t'as fait des etudes dans quel domaine avant de bosser en restauration ?"
MAUVAIS : "Information manquante detectee : diplomes. Pourriez-vous renseigner vos diplomes ?"

{profil_info}
{collected_info}

{full_context}

INFORMATIONS MANQUANTES A RECOLTER NATURELLEMENT :
{missing_str}

{decisions_str}
{so_str}
{device_context}

GARDIEN DE L'OBJECTIF DE VIE :
L'objectif de vie de l'utilisateur est SACRE et NON NEGOCIABLE. C'est le pilier de toute l'application.
Si l'utilisateur exprime l'envie d'abandonner son objectif, de tout lacher, ou de prendre une decision qui saboterait directement son objectif de vie :
- Tu ne l'encourages JAMAIS a abandonner
- Tu ne proposes JAMAIS de changer d'objectif, d'en trouver un autre, ou de se "reorienter" vers autre chose
- Tu fais preuve d'empathie (c'est normal d'avoir des moments de doute)
- Tu lui rappelles son objectif, sa progression, ses sous-objectifs
- Tu proposes des solutions DANS LE CADRE de l'objectif actuel (pause, identifier le blocage, demander du soutien, revoir la methode)
- Meme s'il insiste, tu restes ferme mais bienveillant — tu es son allie

ATTENTION : Ce n'est PAS un refus systematique. Tu ne bloques pas :
- L'expression de frustration ou fatigue (ecouter ≠ valider l'abandon)
- Les decisions de vie normales sans lien avec l'objectif
- Les demandes d'aide ou de conseil

DETECTION D'EVENEMENTS IMPORTANTS — REGLE CRITIQUE :
Quand l'utilisateur te confie un evenement ou une decision MAJEUR(E) qui devrait
impacter sa progression vers l'objectif, tu DOIS proposer de l'enregistrer
officiellement. NE l'enregistre JAMAIS toi-meme — propose-le, l'utilisateur
valide via boutons.

Sont MAJEURS (a proposer) :
- Argent significatif recu/perdu (heritage, bonus, achat, perte) > 1000 EUR
- Changement professionnel (embauche, demission, promotion, lancement projet)
- Decision financiere majeure (investissement, levee, achat immobilier)
- Etape franchie sur l'objectif (lancement produit, premiere vente, milestone)
- Echec ou crise majeure (rupture business, probleme sante grave)
- Engagement significatif (partenariat, contrat, signature)

Sont BANALITES (ne propose RIEN) :
- Repas, sommeil, sport ponctuel, meteo
- Sortie, hobby, rencontre amicale
- Petit achat (<100 EUR)
- Humeur quotidienne, fatigue passagere
- Discussion casuelle sans engagement concret

QUAND tu detectes un evenement MAJEUR, AJOUTE a la fin de ta reponse
texte un bloc INVISIBLE pour l'utilisateur (le frontend l'extrait et affiche
des boutons cliquables) :

[[PROPOSITION]]
{{
  "type": "evenement",
  "description": "Description courte et factuelle de l'evenement",
  "impact_jours": 365,
  "resume": "Resume en 1 phrase de pourquoi c'est positif/negatif",
  "rationale": "Pourquoi tu penses que c'est important",
  "target_so_hint": "Nom du sous-objectif probablement impacte"
}}
[[/PROPOSITION]]

IMPORTANT pour le bloc :
- impact_jours = nombre de jours GAGNES sur l objectif total (positif) ou
  PERDUS (negatif). Estime de maniere realiste — un heritage de 50k peut
  faire gagner 200-500 jours sur un objectif "milliardaire", pas plus.
- type doit etre "evenement" (par defaut), ou "decision_majeure" pour un
  choix structurant.
- target_so_hint : si tu reconnais quel sous-objectif est concerne, ecris
  son nom. Sinon laisse vide.
- Tu n ecris JAMAIS le bloc dans le texte conversationnel. Il vient APRES
  ta phrase de reponse, jamais au milieu, jamais expose a l utilisateur.

EXEMPLE :
User : "J ai recu 50 000 euros de mon oncle, c est dingue"
Agent : "Whoa, felicitations Louis ! C est un coup de pouce enorme. Tu sais deja ce que tu vas en faire ?

[[PROPOSITION]]
{{
  "type": "evenement",
  "description": "Reception d un don familial de 50 000 EUR",
  "impact_jours": 250,
  "resume": "Apport de cash important qui peut accelerer le lancement de Sylea ou diversifier les revenus",
  "rationale": "50k EUR = ~6 mois de runway ou capital initial pour structurer un investissement",
  "target_so_hint": "Lancer Sylea comme premiere source de revenu"
}}
[[/PROPOSITION]]"

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

        # Migration PG (2026-05-13) : UPDATE via SQLAlchemy text() async.
        # SECURITE : noms de colonnes en whitelist statique (FIELDS / LIST_FIELDS).
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()

        SCALAR_FIELDS = ("genre", "ville", "situation_familiale", "profession")
        LIST_FIELDS = ("competences", "diplomes", "langues")

        async with factory() as session:
            try:
                # Champs scalaires
                if extracted.get("genre") and not getattr(profil, "genre", None):
                    await session.execute(
                        text(
                            "UPDATE profil_utilisateur SET genre = :val "
                            "WHERE auth_user_id = :uid"
                        ),
                        {"val": extracted["genre"], "uid": auth_user_id},
                    )
                if extracted.get("ville") and (
                    not profil.ville or profil.ville == "Non renseigne"
                ):
                    await session.execute(
                        text(
                            "UPDATE profil_utilisateur SET ville = :val "
                            "WHERE auth_user_id = :uid"
                        ),
                        {"val": extracted["ville"], "uid": auth_user_id},
                    )
                if extracted.get("situation_familiale") and (
                    not profil.situation_familiale
                    or profil.situation_familiale == "Non renseigne"
                ):
                    await session.execute(
                        text(
                            "UPDATE profil_utilisateur SET situation_familiale = :val "
                            "WHERE auth_user_id = :uid"
                        ),
                        {"val": extracted["situation_familiale"], "uid": auth_user_id},
                    )
                if extracted.get("profession") and (
                    not profil.profession or profil.profession == "Non renseigne"
                ):
                    await session.execute(
                        text(
                            "UPDATE profil_utilisateur SET profession = :val "
                            "WHERE auth_user_id = :uid"
                        ),
                        {"val": extracted["profession"], "uid": auth_user_id},
                    )
                # Champs listes
                for field in LIST_FIELDS:
                    val = extracted.get(field)
                    if val and isinstance(val, list) and len(val) > 0:
                        current = getattr(profil, field, None)
                        if (not current
                                or (isinstance(current, list) and len(current) == 0)
                                or current == ""):
                            # SECURITE : field in LIST_FIELDS (whitelist statique)
                            await session.execute(
                                text(
                                    f"UPDATE profil_utilisateur SET {field} = :val "
                                    f"WHERE auth_user_id = :uid"
                                ),
                                {"val": ",".join(val), "uid": auth_user_id},
                            )
                await session.commit()
            except Exception:
                await session.rollback()

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

        # Save to agent_collected_info table (Migration PG : async + portable
        # datetime instead of SQLite-specific datetime('now'))
        from sqlalchemy import text
        from api.database import get_session_factory
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).isoformat()
        factory = get_session_factory()
        async with factory() as session:
            try:
                for field, value in extracted.items():
                    if value and str(value).strip():
                        await session.execute(
                            text(
                                "INSERT INTO agent_collected_info "
                                "(user_id, field, value, collected_at) "
                                "VALUES (:uid, :field, :val, :now)"
                            ),
                            {
                                "uid": user_id or "", "field": field,
                                "val": (json.dumps(value, ensure_ascii=False)
                                        if isinstance(value, (list, dict))
                                        else str(value)),
                                "now": now_iso,
                            },
                        )
                await session.commit()
            except Exception:
                await session.rollback()
    except Exception:
        pass  # Silent fail — don't break the chat


# ── TTS audio generation helper ───────────────────────────────────────────

async def _generate_tts_audio(text: str) -> str:
    """Generate TTS audio using OpenAI and return base64 encoded mp3."""
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
        # Quota quotidien d'actions IA : on ne compte qu'a la reception du
        # message user (pas a chaque ping). 1 message = 1 action.
        if user_id and profil:
            from api.daily_action_limit import check_daily_action_quota_async
            from api.agent3_quotas import get_user_plan_async as _get_plan
            try:
                _plan = await _get_plan(user_id)
                plan_name = _plan.get('name', 'free')
            except Exception:
                plan_name = 'free'
            ok, count, limit = await check_daily_action_quota_async(profil.id, user_id, plan_name)
            if not ok:
                quota_msg = (
                    f"Tu as atteint ton quota d'actions IA pour aujourd'hui ({count}/{limit}). "
                    + (
                        "Passe a Avance pour 30 actions/jour."
                        if plan_name == 'free'
                        else "Reessaie demain ou contacte le support."
                    )
                )
                return AgentChatOut(message=quota_msg)
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
            # Unification : on expose progression (% temps gagne sur temps initial)
            # comme metric unique, plus comprehensible que la probabilite IA.
            "probabilite_actuelle": (
                round((profil.temps_gagne_jours or 0) / profil.temps_initial_jours * 100, 1)
                if (profil.temps_initial_jours or 0) > 0 else 0.0
            ),
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

    # Load sub-objectives (col `user_id`, pas `profil_id`).
    # Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async — compat SQLite + PG.
    sous_objectifs: list[dict] = []
    try:
        from sqlalchemy import text as _sa_text
        from api.database import get_session_factory as _gsf_so
        _factory_so = _gsf_so()
        async with _factory_so() as _session_so:
            _result_so = await _session_so.execute(
                _sa_text(
                    "SELECT titre, progression FROM sous_objectifs "
                    "WHERE user_id = (SELECT id FROM profil_utilisateur WHERE auth_user_id = :auid LIMIT 1)"
                ),
                {"auid": user_id or ""},
            )
            sous_objectifs = [
                {"titre": r["titre"], "progression": r["progression"]}
                for r in _result_so.mappings().all()
            ]
    except Exception:
        pass

    # Pre-charge collected_info en async pour _build_agent_prompt (qui reste sync).
    collected_rows = await _load_collected_info_async(user_id, limit=30) if user_id else []

    # Build prompt + v2 enrichments (memory partagee + awareness contextuel)
    device_ctx = format_device_context(data.contexte_appareil) if data.contexte_appareil else ""
    full_ctx = await build_full_user_context_async(db, user_id)
    awareness_blk = ""
    memory_blk = ""
    if user_id:
        try:
            awareness_blk = await build_awareness_block_async(user_id) or ""
        except Exception:
            pass
        try:
            # Memoire long terme : on charge plus de souvenirs (80) et on en
            # injecte plus dans le system prompt (60). Avec le prompt caching
            # Anthropic (api/llm_router.py), le surcout est negligeable car
            # le bloc memoire est cache 5 min entre messages.
            mem = await load_memories_async(user_id, limit=80)
            memory_blk = format_memories(mem, max_items=60) if mem else ""
        except Exception:
            pass
    system_prompt = _build_agent_prompt(
        profil_data, decisions, sous_objectifs, device_ctx,
        db=db, user_id=user_id, full_context=full_ctx,
        awareness_block=awareness_blk,
        memory_block=memory_blk,
        collected_info_rows=collected_rows,
    )

    # Build chat context: load from DB if authenticated, else use what frontend sent.
    # CRITIQUE : Anthropic refuse les champs autres que role+content sur les messages.
    # On strippe systematiquement type/audio_data/timestamp/id pour eviter le 400
    # "messages.0.type: Extra inputs are not permitted".
    def _clean_msg(m: dict) -> dict:
        return {"role": m.get("role"), "content": m.get("content", "")}

    if user_id:
        db_messages = await _load_agent_messages_async(user_id, limit=50)
        chat_messages = [
            {"role": "assistant" if m["role"] == "agent" else "user", "content": m["content"]}
            for m in db_messages
        ]
        if data.messages:
            last_msg = data.messages[-1]
            if last_msg.get("role") == "user":
                chat_messages.append({"role": "user", "content": last_msg.get("content", "")})
    else:
        chat_messages = [_clean_msg(m) for m in data.messages[-20:]]

    # Determine the user message type from the request
    user_msg_type = "text"
    if data.messages:
        last_input = data.messages[-1]
        user_msg_type = last_input.get("type", "text")

    # Call Claude. Sanitization finale : Anthropic refuse strictement les champs
    # autres que role/content sur les items de `messages`. On reconstruit chaque
    # dict pour eviter toute fuite (defense in depth, meme si _clean_msg a deja
    # tourne plus haut).
    sanitized_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in chat_messages[-20:]
        if m.get("content")
    ]

    import anthropic
    import logging
    _agent_logger = logging.getLogger("sylea.agent1")

    client = anthropic.Anthropic(api_key=key)
    try:
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=sanitized_messages,
            )
        )
    except anthropic.APIStatusError as e:
        # Erreur API Anthropic (rate limit, quota, mauvais format, etc.)
        _agent_logger.error(
            "[agent1] Anthropic API error status=%s msg=%s system_len=%d msgs=%d audio=%s",
            getattr(e, "status_code", "?"), str(e)[:300],
            len(system_prompt), len(sanitized_messages),
            "yes" if user_msg_type == "voice" else "no",
        )
        return AgentChatOut(
            message=f"Erreur Claude {getattr(e, 'status_code', '?')} : {str(e)[:200]}",
        )
    except Exception as e:
        _agent_logger.error(
            "[agent1] Erreur inattendue type=%s msg=%s",
            type(e).__name__, str(e)[:300],
            exc_info=True,
        )
        return AgentChatOut(
            message=f"Erreur interne ({type(e).__name__}) : {str(e)[:200]}",
        )

    agent_response_raw = msg.content[0].text.strip()

    # Extraction d'une proposition d'event/decision detectee par l'agent.
    # Le bloc [[PROPOSITION]]{json}[[/PROPOSITION]] est retire du texte affiche
    # a l'utilisateur, et sauvegarde en DB pour validation ultérieure via boutons.
    from api.agent_proposals import extract_proposal_from_text, save_proposal_async
    agent_response, proposal_payload = extract_proposal_from_text(agent_response_raw)
    saved_proposal: dict | None = None
    if proposal_payload and user_id:
        try:
            saved_proposal = await save_proposal_async(user_id, "agent1", proposal_payload)
        except Exception:
            saved_proposal = None

    # Generate TTS audio for agent response if user sent a voice message
    agent_audio_data = ""
    if user_msg_type == "voice":
        agent_audio_data = await _generate_tts_audio(agent_response)

    # Persist messages if authenticated
    if user_id:
        # Save user message (with user's recorded audio if provided)
        if data.messages:
            last_user = data.messages[-1]
            if last_user.get("role") == "user":
                await _save_agent_message_async(
                    user_id, "user", last_user["content"], user_msg_type,
                    audio_data=data.audio_data or "",
                )
        # Save agent response — same type as user message (voice -> voice, text -> text)
        agent_msg_type = "voice" if user_msg_type == "voice" else "text"
        await _save_agent_message_async(
            user_id, "agent", agent_response, agent_msg_type,
            audio_data=agent_audio_data,
        )

        # Auto-extract profile info every 5 messages
        total_msgs = await _count_agent_messages_async(user_id)
        if total_msgs > 0 and total_msgs % 5 == 0:
            recent = await _load_agent_messages_async(user_id, limit=20)
            await _extract_and_update_profile(db, user_id, recent)

        # Fire-and-forget: extract and save personal info to collected_info table
        recent_for_info = await _load_agent_messages_async(user_id, limit=4)
        asyncio.create_task(_extract_and_save_info(recent_for_info, profil_data, db, user_id))

        # v2 : Auto-extract shared memory (Agent 1/2/3) — best-effort + fresh DB
        try:
            recent_msgs = await _load_agent_messages_async(user_id, limit=10)
            recent_msgs = list(reversed(recent_msgs))  # DESC -> ASC chrono
            turns = [
                {"role": "agent" if m["role"] == "agent" else "user", "content": m["content"]}
                for m in recent_msgs if m.get("content", "").strip()
            ]
            if turns:
                async def _bg_extract(uid: str, t: list):
                    fresh = DatabaseManager()
                    fresh.connect()
                    try:
                        await auto_extract_from_turns(fresh, uid, t, agent_label="agent1")
                    finally:
                        try: fresh.disconnect()
                        except Exception: pass
                _t = asyncio.create_task(_bg_extract(user_id, turns))
                _BG_TASKS.add(_t)
                _t.add_done_callback(_BG_TASKS.discard)
        except Exception:
            pass

    return AgentChatOut(
        message=agent_response,
        audioData=agent_audio_data if agent_audio_data else None,
        proposal=saved_proposal,
    )


@router.get("/messages", response_model=list[AgentMessageOut])
async def get_agent_messages(
    user_id: str | None = Depends(get_optional_user),
):
    """Return all persisted agent messages for the authenticated user.

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    if not user_id:
        return []
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, role, content, type, created_at, audio_data "
                    "FROM agent_messages "
                    "WHERE auth_user_id = :uid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"uid": user_id, "limit": 200},
            )
        except Exception:
            # Fallback si audio_data n'existe pas (schema migration en cours)
            result = await session.execute(
                text(
                    "SELECT id, role, content, type, created_at "
                    "FROM agent_messages "
                    "WHERE auth_user_id = :uid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"uid": user_id, "limit": 200},
            )
        rows = list(reversed(result.mappings().all()))  # plus ancien en premier
    return [
        AgentMessageOut(
            id=m["id"], role=m["role"], content=m["content"],
            type=m["type"], created_at=m["created_at"],
            audioData=m.get("audio_data") or "",
        )
        for m in rows
    ]


@router.delete("/messages")
async def clear_agent_messages(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Clear all conversation history for the authenticated user.

    Migration PG (2026-05-13) : DELETE via SQLAlchemy text() async.
    """
    if user_id:
        await _clear_agent_messages_async(user_id)
    return {"detail": "Historique de conversation supprime."}


# ── Agent proposals (confirm/reject buttons in chat) ─────────────────────────

@router.get("/proposals")
async def list_agent_proposals(
    user_id: str | None = Depends(get_optional_user),
):
    """Liste toutes les propositions en attente pour l'utilisateur.

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    if not user_id:
        return []
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, agent_label, type, description, impact_jours, resume, "
                "rationale, target_so_hint, created_at "
                "FROM agent_proposals "
                "WHERE auth_user_id = :uid AND statut = 'pending' "
                "ORDER BY created_at DESC LIMIT 20"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()
    return [
        {
            "id": r["id"], "agent_label": r["agent_label"], "type": r["type"],
            "description": r["description"], "impact_jours": r["impact_jours"],
            "resume": r["resume"], "rationale": r["rationale"],
            "target_so_hint": r["target_so_hint"], "created_at": r["created_at"],
            "statut": "pending",
        }
        for r in rows
    ]


@router.post("/proposals/{proposal_id}/confirm")
async def confirm_agent_proposal(
    proposal_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Confirme une proposition agent : applique l'impact sur le profil + SO.

    Reuse exactement le meme path que /api/evenement/confirmer pour creer la
    Decision et appliquer l'impact via apply_impact_invariant_safe — garantit
    l'invariant.
    """
    from fastapi import HTTPException
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    # Migration PG (2026-05-13) : get_proposal / mark_responded / SO cascade
    # passent par les versions async (compatibles SQLite + PostgreSQL).
    from api.agent_proposals import get_proposal_async, mark_responded_async
    prop = await get_proposal_async(proposal_id, user_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if prop["statut"] != "pending":
        raise HTTPException(status_code=400, detail=f"Proposition deja {prop['statut']}")

    # Charger le profil (sync repo : pas de cascade ici)
    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Profil introuvable")
    profil = repo.charger(auth_user_id=user_id)
    if profil is None or profil.temps_initial_jours <= 0:
        raise HTTPException(status_code=400, detail="Profil incomplet")

    # Creer la Decision avec impact pre-applique sur temps_gagne
    from sylea.core.models.decision import Decision, OptionDilemme
    impact_jours = float(prop["impact_jours"])
    temps_gagne_avant = profil.temps_gagne_jours
    temps_gagne_apres = max(0, min(
        profil.temps_initial_jours, temps_gagne_avant + impact_jours
    ))
    prob_avant = profil.probabilite_actuelle
    prob_apres = round((temps_gagne_apres / profil.temps_initial_jours) * 100, 2)

    opt = OptionDilemme(
        description=prop["description"],
        impact_score=0,
        explication_impact=prop["resume"] or prop["rationale"],
    )
    decision = Decision(
        user_id=profil.id,
        question=f"[Agent {prop['agent_label']}] {prop['description']}",
        options=[opt],
        probabilite_avant=prob_avant,
        option_choisie_id=opt.id,
        probabilite_apres=prob_apres,
        temps_gagne_avant=temps_gagne_avant,
        temps_gagne_apres=temps_gagne_apres,
    )
    dec_repo = DecisionRepository(db)
    dec_repo.sauvegarder(decision)

    # Mettre a jour profil
    profil.temps_gagne_jours = temps_gagne_apres
    profil.probabilite_actuelle = prob_apres
    profil.marquer_modification()
    repo.sauvegarder(profil)

    # Appliquer l'impact sur les SO via apply_impact_invariant_safe_async
    # (Migration PG : SELECT SO + cascade dans UNE transaction async)
    so_titre_impacte = None
    try:
        from sqlalchemy import text as _sql_text
        from api.database import get_session_factory as _gsf
        from api.so_invariant import apply_impact_invariant_safe_async
        _factory = _gsf()
        async with _factory() as _session:
            try:
                _so_result = await _session.execute(
                    _sql_text(
                        "SELECT id, titre, progression, ordre, temps_estime "
                        "FROM sous_objectifs WHERE user_id = :uid ORDER BY ordre"
                    ),
                    {"uid": profil.id},
                )
                all_so_all = list(_so_result.mappings().all())
                all_so = [so for so in all_so_all if (so["progression"] or 0) < 100]
                if all_so:
                    target_so = None
                    if prop.get("target_so_hint"):
                        hint_norm = prop["target_so_hint"].lower()
                        for so in all_so:
                            if hint_norm in (so["titre"] or "").lower():
                                target_so = so
                                break
                    if target_so is None:
                        target_so = all_so[0]

                    target_id_used, applied_delta_pct = await apply_impact_invariant_safe_async(
                        _session, profil.id, target_so["id"], impact_jours,
                        profil.temps_initial_jours,
                    )
                    so_titre_impacte = target_so["titre"]
                    decision.sous_objectif_id = target_id_used or target_so["id"]
                    decision.impact_sous_objectif = applied_delta_pct
                await _session.commit()
            except Exception:
                await _session.rollback()
                raise
        if so_titre_impacte:
            dec_repo.sauvegarder(decision)
    except Exception:
        pass

    # Marquer la proposition comme confirmée
    await mark_responded_async(proposal_id, "confirmed", decision_id=decision.id)

    return {
        "detail": "Proposition confirmee et impact applique.",
        "decision_id": decision.id,
        "sous_objectif_impacte": so_titre_impacte,
        "temps_gagne_jours": profil.temps_gagne_jours,
        "probabilite_actuelle": profil.probabilite_actuelle,
    }


@router.post("/proposals/{proposal_id}/reject")
async def reject_agent_proposal(
    proposal_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Refuse une proposition agent : aucun impact stats, juste un log."""
    from fastapi import HTTPException
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    # Migration PG (2026-05-13) : versions async (compat SQLite + PG).
    from api.agent_proposals import get_proposal_async, mark_responded_async
    prop = await get_proposal_async(proposal_id, user_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if prop["statut"] != "pending":
        raise HTTPException(status_code=400, detail=f"Proposition deja {prop['statut']}")

    await mark_responded_async(proposal_id, "rejected")
    return {"detail": "Proposition refusee. Aucun impact applique."}


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

    # Check last PROACTIVE message time / USER message / decision / account+profile creation.
    # Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async — compat SQLite + PG.
    last_proactive = None
    last_user_msg = None
    last_decision = None
    account_created = None
    profil_created = None
    try:
        from sqlalchemy import text as _sa_text
        from api.database import get_session_factory as _gsf
        _factory = _gsf()
        async with _factory() as _session:
            _r = await _session.execute(
                _sa_text(
                    "SELECT created_at FROM agent_messages "
                    "WHERE auth_user_id = :uid AND role = 'agent' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": user_id},
            )
            _row = _r.first()
            last_proactive = (_row[0],) if _row else None

            _r = await _session.execute(
                _sa_text(
                    "SELECT created_at FROM agent_messages "
                    "WHERE auth_user_id = :uid AND role = 'user' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": user_id},
            )
            _row = _r.first()
            last_user_msg = (_row[0],) if _row else None

            _r = await _session.execute(
                _sa_text(
                    "SELECT cree_le FROM decisions "
                    "WHERE user_id = (SELECT id FROM profil_utilisateur "
                    "WHERE auth_user_id = :uid LIMIT 1) "
                    "ORDER BY cree_le DESC LIMIT 1"
                ),
                {"uid": user_id},
            )
            _row = _r.first()
            last_decision = (_row[0],) if _row else None

            _r = await _session.execute(
                _sa_text("SELECT created_at FROM users WHERE id = :uid LIMIT 1"),
                {"uid": user_id},
            )
            _row = _r.first()
            account_created = (_row[0],) if _row else None

            _r = await _session.execute(
                _sa_text("SELECT cree_le FROM profil_utilisateur WHERE auth_user_id = :uid LIMIT 1"),
                {"uid": user_id},
            )
            _row = _r.first()
            profil_created = (_row[0],) if _row else None
    except Exception:
        pass

    now = datetime.now(timezone.utc)

    def _parse_iso(s: str | None) -> datetime | None:
        # Tolere : '2026-05-08T18:27:52.127032' (naive, format ISO sans tz),
        # '2026-03-22T14:52:15.566288+00:00' (ISO avec offset),
        # '2026-05-08 18:27:52' (format SQLite). Toujours retourne TZ-aware.
        if not s:
            return None
        try:
            if 'T' in s:
                dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    # Calculate hours since last proactive message
    hours_since_proactive = 999
    last_dt = _parse_iso(last_proactive[0] if last_proactive else None)
    if last_dt:
        hours_since_proactive = (now - last_dt).total_seconds() / 3600

    # Calculate hours since last user activity
    # On collecte tous les candidats (msg, decision, account, profil) et on prend
    # le plus recent. Le fallback compte/profil garantit qu'un compte neuf n'est
    # pas marque "absent depuis 41 jours" alors qu'il vient d'etre cree.
    hours_since_user = 999
    for check in [last_user_msg, last_decision, account_created, profil_created]:
        dt = _parse_iso(check[0] if check else None)
        if dt:
            h = (now - dt).total_seconds() / 3600
            hours_since_user = min(hours_since_user, h)

    # RULES (FIX 2026-05-16 : eviter spam quand user absent) :
    # 1. Minimum 72h entre proactifs pour routine check-ins.
    # 2. Exception "absent" : si user inactif 72h+, on envoie un rappel — MAIS
    #    avec un cooldown plancher de 24h pour eviter le spam si le user
    #    revient sur la page sans interagir (chaque visite ne doit PAS regenerer
    #    un message).
    # 3. Compte neuf (<24h) : pas de proactive du tout.
    is_brand_new = hours_since_user < 24
    is_urgent = (not is_brand_new) and hours_since_user >= 72
    is_routine_ok = hours_since_proactive >= 72
    # Cooldown plancher meme en mode urgent : 24h min entre 2 proactifs.
    is_urgent_cooldown_ok = hours_since_proactive >= 24

    # Skip si compte neuf OU (pas urgent ET pas routine OK) OU
    # (urgent MAIS dans le cooldown 24h)
    if (is_brand_new
            or (not is_urgent and not is_routine_ok)
            or (is_urgent and not is_urgent_cooldown_ok)):
        return {"message": None}  # Too early, respect the user's peace

    # Determine the reason for reaching out
    reason = "routine"
    if is_urgent:
        reason = "absent"

    last_msg = last_proactive  # For prompt context

    # Load collected info for context.
    # Migration PG (2026-05-13) : SELECT via _load_collected_info_async — compat SQLite + PG.
    collected_info_str = ""
    try:
        _rows = await _load_collected_info_async(user_id, limit=15)
        if _rows:
            collected_info_str = "\nInfos collectees: " + ", ".join(f"{f}={v}" for f, v in _rows)
    except Exception:
        pass

    # Build proactive prompt based on reason
    # IMPORTANT : on ne donne PAS la valeur exacte de hours_since_user au LLM
    # pour eviter qu'il hallucine "ca fait 41 jours" sur un compte neuf.
    days_since = int(hours_since_user / 24)
    objectif_desc = profil.objectif.description if profil.objectif else 'non defini'

    if reason == "absent":
        prompt = f"""Tu es l'Agent Sylea 1, le compagnon IA personnel de {profil.nom}.
{profil.nom}, {profil.age} ans, {profil.profession}. Objectif : {objectif_desc}.
{collected_info_str}

CONTEXTE : {profil.nom} ne s'est pas connecte depuis {days_since} jours. Tu lui envoies un texto pour lui rappeler de revenir.

Ecris UN message court (max 2 phrases), tutoiement, naturel comme un ami. Tu peux mentionner la duree d'absence ({days_since} jours).
N'ecris RIEN d'autre que le message lui-meme.

Message :"""
    else:
        # Routine : intent-driven prompt — on NE parle pas d'"absence" / "check-in" /
        # "depuis", on demande juste une question utile sur l'objectif.
        prompt = f"""Tu es l'Agent Sylea 1, le compagnon IA personnel de {profil.nom}.
{profil.nom}, {profil.age} ans, {profil.profession}. Objectif : {objectif_desc}.
{collected_info_str}

TACHE : Pose UNE question concrete et utile a {profil.nom} sur son objectif, OU partage un encouragement court lie a son projet.

CONTRAINTES STRICTES :
- {profil.nom} est ACTIVEMENT en train d'utiliser l'application maintenant.
- N'ecris JAMAIS "ca fait", "depuis", "longtemps", "des nouvelles", "plus d'un", "on s'est pas vus", "ca faisait" ou toute autre formulation d'absence/retrouvailles.
- N'ecris JAMAIS de salutation type "yo", "salut", "hey" — entre directement dans le sujet.
- Max 2 phrases, tutoiement.
- N'invente AUCUN fait non present dans le profil ci-dessus.
- N'ecris RIEN d'autre que le message lui-meme.

Bons exemples (style attendu) :
- "Ton objectif avance bien ? Tu as identifie le prochain levier a activer ?"
- "Petite idee : avec les 50k recus, tu pourrais securiser 6 mois de runway. Tu y as pense ?"

Mauvais exemples (interdits) :
- "Yo, ca fait longtemps !" (absence)
- "Salut Louis, comment ca va ?" (salutation generique)

Message :"""

    # Mots-cles d'absence interdits — on rejette + retry si le LLM les utilise
    forbidden_in_routine = [
        "ca fait", "ça fait", "depuis", "longtemps", "plus d'un",
        "on s'est pas vus", "on s'est pas parle", "ca faisait", "ça faisait",
        "des nouvelles depuis", "absent", "absente", "ou tu etais", "où tu étais",
    ]

    def _is_clean(text: str) -> bool:
        if reason == "absent":
            return True  # absent message can mention duration
        low = text.lower()
        return not any(kw in low for kw in forbidden_in_routine)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)

        agent_text = ""
        for attempt in range(3):
            msg = await asyncio.to_thread(
                lambda: client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=150,
                    messages=[{"role": "user", "content": prompt}],
                )
            )
            agent_text = msg.content[0].text.strip()
            if _is_clean(agent_text):
                break
            # Si le LLM a glisse un mot interdit, on reessaie avec un prompt
            # plus ferme. Apres 3 tentatives, on abandonne (return None).
        else:
            return {"message": None}

        # Save to DB
        await _save_agent_message_async(user_id, "agent", agent_text, "text")

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
    type: str = "dilemme"  # "dilemme" or "evenement"
    question: str = ""  # the original dilemma question or event description
    options: list[str] | None = None


class SaveContextOut(BaseModel):
    ok: bool
    sufficient: bool  # True if the context is now sufficient for analysis
    feedback: str | None = None  # If not sufficient, explain what's missing


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

        # Load collected info + recent agent conversation (mémoire longue) for context.
        # Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async.
        try:
            _rows = await _load_collected_info_async(user_id, limit=30)
            if _rows:
                collected_info = "\n".join(f"{f}: {v}" for f, v in _rows)
        except Exception:
            pass

        try:
            from sqlalchemy import text as _sa_text
            from api.database import get_session_factory as _gsf
            _factory = _gsf()
            async with _factory() as _session:
                _r = await _session.execute(
                    _sa_text(
                        "SELECT role, content FROM agent_messages "
                        "WHERE auth_user_id = :uid ORDER BY created_at DESC LIMIT 20"
                    ),
                    {"uid": user_id},
                )
                _msg_rows = [(m["role"], m["content"]) for m in _r.mappings().all()]
            if _msg_rows:
                conversation_context = "\n".join(
                    f"{'Utilisateur' if r[0] == 'user' else 'Agent'}: {r[1][:150]}"
                    for r in reversed(_msg_rows)
                )
                collected_info += "\n\nCONVERSATION RECENTE AVEC L'AGENT :\n" + conversation_context
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

INFORMATIONS ET CONVERSATIONS CONNUES SUR L'UTILISATEUR :
{collected_info or "Aucune"}

QUESTION: As-tu assez de contexte pour analyser cette demande ?

REGLE CRITIQUE : Si des personnes, lieux ou situations mentionnes dans la DEMANDE
apparaissent DEJA dans les INFORMATIONS/CONVERSATIONS ci-dessus,
tu as DEJA le contexte. Reponds needs_context: false.

Exemples qui NECESSITENT du contexte (personnes/situations INCONNUES):
- "Me mettre en couple avec Claire ou Laura" -> Claire et Laura n'apparaissent NULLE PART dans les infos -> needs_context: true
- "Accepter l'offre de Jean" -> Jean n'apparait NULLE PART -> needs_context: true

Exemples qui N'ONT PAS BESOIN de contexte:
- "Aller a la soiree de Arthur" ET la conversation mentionne Arthur -> needs_context: false
- "Apprendre l'anglais ou l'espagnol" -> Assez generique -> needs_context: false
- "Manger ou aller courir" -> Activites courantes, analyse directe
- "J'ai obtenu une promotion" -> Clair en soi, analyse directe
- "J'ai recu un financement de 10000 euros" -> Le montant est clair MAIS le type de financement manque -> QCM

IMPORTANT: Ne mentionne JAMAIS des personnes ou des infos des "informations connues" dans ta question
si elles ne sont PAS mentionnees dans la DEMANDE.

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


@router.post("/save-context", response_model=SaveContextOut)
async def save_context(
    data: SaveContextIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Save context provided by the user, then validate if it is sufficient for analysis."""
    # Save the context.
    # Migration PG (2026-05-13) : INSERT via SQLAlchemy text() async — compat SQLite + PG.
    if user_id:
        try:
            from sqlalchemy import text as _sa_text
            from api.database import get_session_factory as _gsf
            _factory = _gsf()
            _now_iso = datetime.now(timezone.utc).isoformat()
            async with _factory() as _session:
                await _session.execute(
                    _sa_text(
                        "INSERT INTO agent_collected_info (user_id, field, value, collected_at) "
                        "VALUES (:uid, :field, :value, :collected_at)"
                    ),
                    {
                        "uid": user_id,
                        "field": f"contexte_{data.related_to[:50]}",
                        "value": data.context_text,
                        "collected_at": _now_iso,
                    },
                )
                await _session.commit()
        except Exception:
            pass

    # Now validate: is the context sufficient?
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return SaveContextOut(ok=True, sufficient=True)

    # Load all collected info for this user.
    # Migration PG (2026-05-13) : SELECT via _load_collected_info_async.
    collected_info = ""
    if user_id:
        try:
            _rows = await _load_collected_info_async(user_id, limit=20)
            collected_info = "\n".join(f"{f}: {v}" for f, v in _rows)
        except Exception:
            pass

    options_text = ""
    if data.options:
        options_text = f"\nOptions: {' | '.join(data.options)}"

    prompt = f"""L'utilisateur a repondu a une question de contexte pour une analyse.

DEMANDE ORIGINALE: {data.question}{options_text}
REPONSE DE L'UTILISATEUR: {data.context_text}

QUESTION IMPORTANTE : Est-ce que la reponse de l'utilisateur repond a la question qui lui a ete posee ?

REGLES STRICTES :
1. Si l'utilisateur a donne une reponse qui explique QUI sont les personnes ou QUEL est le contexte -> SUFFISANT
2. Ne demande JAMAIS l'objectif de vie, la profession, la ville, l'age -> tu as DEJA ces infos
3. Ne pose JAMAIS de question supplementaire au-dela de ce qui etait demande initialement
4. Sois TOLERANT : une reponse courte mais claire = suffisant
5. En cas de doute, reponds SUFFISANT (mieux vaut analyser avec peu de contexte que bloquer l'utilisateur)

Exemples :
- Question "Qui est Marc?" -> Reponse "C'est un ami investisseur" -> SUFFISANT
- Question "Quel type de financement?" -> Reponse "Pret bancaire" -> SUFFISANT
- Question "Qui sont Claire et Laura?" -> Reponse "Claire est mon amie, Laura ma collegue" -> SUFFISANT

Reponds UNIQUEMENT en JSON:
{{"sufficient": true/false, "feedback": "explication courte" ou null}}"""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = msg.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return SaveContextOut(
                ok=True,
                sufficient=result.get("sufficient", True),
                feedback=result.get("feedback"),
            )
    except Exception:
        pass

    return SaveContextOut(ok=True, sufficient=True)
