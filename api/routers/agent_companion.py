"""
Router Agent Companion (Agent Sylea 1) — chatbot bienveillant qui enrichit le profil.

Analyse le profil, les decisions et les sous-objectifs pour engager une conversation
naturelle et recolter les informations manquantes.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.context_helper import format_device_context
from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AgentChatIn(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": "..."}]
    contexte_appareil: dict | None = None


class AgentChatOut(BaseModel):
    message: str


# ── System prompt builder ────────────────────────────────────────────────────

def _build_agent_prompt(
    profil_data: dict | None,
    decisions: list,
    sous_objectifs: list,
    device_context: str = "",
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

EXEMPLES DE TON :
BON : "Hey ! Comment ca se passe avec le dev web ? T'as eu le temps de coder un peu cette semaine ?"
MAUVAIS : "Bonjour ! Comment allez-vous ? Avez-vous progresse sur votre objectif de devenir developpeur web freelance ?"

BON : "Au fait, je me demandais — t'as fait des etudes dans quel domaine avant de bosser en restauration ?"
MAUVAIS : "Information manquante detectee : diplomes. Pourriez-vous renseigner vos diplomes ?"

{profil_info}

INFORMATIONS MANQUANTES A RECOLTER NATURELLEMENT :
{missing_str}

{decisions_str}
{so_str}
{device_context}

MISSION : Engage une conversation naturelle. Si des infos manquent, trouve un moyen naturel de les demander.
Si rien ne manque, parle des decisions recentes, de l'objectif, ou demande comment va l'utilisateur."""


# ── Endpoint ─────────────────────────────────────────────────────────────────

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
    decisions_raw = dec_repo.lister_pour_utilisateur(auth_user_id=user_id)
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
    system_prompt = _build_agent_prompt(profil_data, decisions, sous_objectifs, device_ctx)

    # Call Claude
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system_prompt,
            messages=data.messages[-20:],
        )
    )

    return AgentChatOut(message=msg.content[0].text.strip())
