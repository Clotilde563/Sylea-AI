"""
Router FastAPI -- Enregistrement d'evenements.

Routes :
  POST /api/evenement/analyser   -> analyse l'impact d'un evenement via IA
  POST /api/evenement/confirmer  -> enregistre l'evenement comme Decision
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException

from sylea.core.models.decision import Decision, OptionDilemme
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

from api.schemas import (
    EvenementIn,
    AnalyseEvenementOut,
    ConfirmerEvenementIn,
    DecisionOut,
    OptionDilemmeOut,
)
from api.dependencies import get_profil_repo, get_decision_repo, get_optional_user, get_db
from sylea.core.storage.database import DatabaseManager
from api.context_helper import format_device_context, build_full_user_context

router = APIRouter(prefix="/api/evenement", tags=["evenement"])


# -- Helpers ----------------------------------------------------------------

def _decision_to_out(d: Decision, sous_objectif_impacte: str | None = None) -> DecisionOut:
    opts = [
        OptionDilemmeOut(
            id=o.id,
            description=o.description,
            impact_score=o.impact_score,
            explication_impact=o.explication_impact,
            est_delegable=o.est_delegable,
            temps_estime=o.temps_estime,
        )
        for o in d.options
    ]
    chosen = d.get_option_choisie()
    return DecisionOut(
        id=d.id,
        user_id=d.user_id,
        question=d.question,
        options=opts,
        probabilite_avant=d.probabilite_avant,
        option_choisie_id=d.option_choisie_id,
        probabilite_apres=d.probabilite_apres,
        action_agent=None,
        cree_le=d.cree_le.isoformat(),
        option_choisie_description=chosen.description if chosen else None,
        impact_net=(
            (d.probabilite_apres - d.probabilite_avant)
            if d.probabilite_apres is not None else None
        ),
        sous_objectif_impacte=sous_objectif_impacte,
    )


# -- Analyse heuristique locale (fallback) ----------------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _analyser_evenement_local(description: str, objectif_desc: str) -> dict:
    """Heuristique simple par mots-cles."""
    desc = _strip_accents(description.lower())

    positifs = [
        "promotion", "augmentation", "formation", "diplome", "certif",
        "investis", "economis", "epargn", "gagne", "reussi", "accept",
        "embauche", "contrat", "partenariat", "mentor", "opportunit",
        "progres", "amelior", "rencontr", "reseau", "lance", "cree",
        "marathon", "sport", "sante", "gueris", "termine",
    ]
    negatifs = [
        "licencie", "vire", "perdu", "echec", "refuse", "rejet",
        "dette", "depense", "accident", "maladie", "bless",
        "rupture", "divorce", "conflit", "demission", "burn",
        "stress", "abandon", "annul", "retard",
    ]

    score_pos = sum(1 for w in positifs if w in desc)
    score_neg = sum(1 for w in negatifs if w in desc)

    if score_pos > score_neg:
        impact = min(1.5, 0.1 + score_pos * 0.3)
        resume = "Evenement positif detecte."
        explication = "Cet evenement semble favorable a votre objectif."
        conseil = "Capitalisez sur cet elan positif."
    elif score_neg > score_pos:
        impact = max(-1.5, -(0.1 + score_neg * 0.3))
        resume = "Evenement negatif detecte."
        explication = "Cet evenement pourrait ralentir votre progression."
        conseil = "Ne vous decouragez pas, chaque obstacle est une lecon."
    else:
        impact = 0.1  # leger positif par defaut
        resume = "Impact neutre detecte."
        explication = "L'impact de cet evenement est difficile a evaluer automatiquement."
        conseil = "Configurez votre cle API Anthropic pour une analyse approfondie."

    return {
        "resume": resume,
        "impact_probabilite": round(impact, 2),
        "explication": explication,
        "conseil": conseil,
    }


# -- Analyse Claude --------------------------------------------------------

async def _analyser_evenement_claude(
    description: str,
    objectif_desc: str,
    objectif_cat: str,
    prob_actuelle: float,
    prob_calculee: float = 0.0,
    profession: str = "",
    device_context: str = "",
    collected_context: str = "",
    full_context: str = "",
) -> dict:
    """Analyse via Claude Haiku."""
    import anthropic as _anthropic

    # Charger .env si pas encore fait
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")

    client = _anthropic.Anthropic(api_key=key)
    # Calculer le temps estime
    prob_totale = max(0.01, min(99.99, prob_actuelle + prob_calculee))
    temps_j = min(73000, max(1, round(900 * ((100 - prob_totale) / prob_totale) ** 0.675)))
    temps_ans = temps_j // 365
    temps_mois = (temps_j % 365) // 30
    temps_str = f"{temps_ans} ans {temps_mois} mois" if temps_ans > 0 else f"{temps_mois} mois"

    prompt = (
        "Tu es un robot probabiliste froid et factuel. Tu calcules l'impact reel "
        "d'un evenement sur un objectif de vie. ZERO emotion, ZERO encouragement. "
        "Tu raisonnes en TEMPS D'ABORD, puis tu convertis en jours.\n\n"
        f"{full_context}\n\n"
        "CONTEXTE :\n"
        f"- Objectif de vie : \"{objectif_desc}\"\n"
        f"- Categorie : {objectif_cat}\n"
        f"- Profession : {profession}\n"
        f"- Temps estime restant : {temps_str} ({temps_j} jours)\n"
        f"- Progression actuelle (jauge) : {prob_actuelle:.1f}%\n"
        f"{device_context}\n"
        f"{collected_context}\n\n"
        f"EVENEMENT RAPPORTE :\n\"{description}\"\n\n"
        "METHODE DE CALCUL (OBLIGATOIRE) :\n"
        "1. PENSE EN TEMPS D'ABORD : combien de JOURS cet evenement fait-il reellement "
        f"gagner ou perdre sur l'objectif (temps restant = {temps_j} jours) ?\n"
        "2. Le champ 'impact_jours' doit contenir ce nombre de jours "
        "(positif = temps gagne, negatif = temps perdu).\n"
        f"3. L'impact ne peut pas depasser {temps_j} jours (la duree totale de l'objectif).\n"
        "4. REALISATION DE L'OBJECTIF : Si l'utilisateur declare que l'objectif "
        f"est ATTEINT ou realise, impact_jours = {temps_j} (toute la duree restante).\n"
        "5. RIGUEUR ABSOLUE — Exemples :\n"
        "   - Financement de 100 EUR pour objectif 3000 EUR/mois freelance : "
        "ne couvre pas 1 mois de loyer, n'elimine aucune barriere. impact_jours = +1 a +5.\n"
        "   - Financement de 1M EUR pour le meme objectif : elimine la barriere "
        f"financiere totalement. impact_jours = +{min(temps_j, int(temps_j * 0.7))} a +{min(temps_j, int(temps_j * 0.9))}.\n"
        "   - Evenement sans impact concret = impact_jours = 0.\n"
        "6. Sois FACTUEL. Pas d'impact par sympathie.\n\n"
        "Reponds UNIQUEMENT avec du JSON valide, sans aucun markdown :\n"
        '{"resume": "...", "impact_jours": <float>, "explication": "...", "conseil": "..."}'
    )

    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    text = msg.content[0].text.strip()
    # Extraire le JSON — supporter les accolades imbriquées et les guillemets
    start = text.find('{')
    if start == -1:
        raise ValueError("JSON invalide — pas d'accolade ouvrante")
    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    json_str = text[start:end]
    if not json_str:
        raise ValueError("JSON invalide — extraction echouee")
    data = json.loads(json_str)

    # L'IA retourne impact_jours (en jours). On convertit en % via la formule inverse.
    impact_jours_val = float(data.get("impact_jours", data.get("impact_probabilite", 0.0)))
    # temps_apres = temps_j - impact_jours (moins de temps restant = plus de probabilite)
    temps_apres = max(1, temps_j - impact_jours_val)
    # Formule inverse : prob = 100 / (1 + (temps/900)^(1/0.675))
    prob_apres = 100.0 / (1.0 + (temps_apres / 900.0) ** (1.0 / 0.675))
    impact_pct = round(prob_apres - prob_totale, 4)

    return {
        "resume": str(data.get("resume", "")),
        "impact_probabilite": impact_pct,
        "explication": str(data.get("explication", "")),
        "conseil": str(data.get("conseil", "")),
    }



async def _identifier_so_pertinent(description: str, sous_objectifs: list) -> dict | None:
    """Utilise Claude pour identifier le sous-objectif le plus pertinent."""
    if len(sous_objectifs) <= 1:
        return sous_objectifs[0] if sous_objectifs else None

    try:
        import anthropic as _anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None

        client = _anthropic.Anthropic(api_key=key)
        so_list = "\n".join(
            f"{i+1}. {so['titre']}" for i, so in enumerate(sous_objectifs)
        )
        prompt = (
            "Voici une action/evenement d'un utilisateur :\n"
            f'"{description}"\n\n'
            f"Voici ses sous-objectifs en cours :\n{so_list}\n\n"
            "Quel sous-objectif (numero) est le PLUS DIRECTEMENT impacte "
            "par cette action ? Reponds UNIQUEMENT avec le numero (ex: 1, 2, 3...)."
        )

        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = msg.content[0].text.strip()
        # Extract the number
        num_match = re.search(r"(\d+)", text)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(sous_objectifs):
                return sous_objectifs[idx]
    except Exception:
        pass
    return None


# -- Routes ----------------------------------------------------------------

@router.post("/analyser", response_model=AnalyseEvenementOut)
async def analyser_evenement(
    data: EvenementIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Analyse l'impact d'un evenement sur l'objectif de vie."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None or not profil.objectif:
        raise HTTPException(status_code=400, detail="Profil ou objectif manquant.")

    # Charger les infos collectées + messages agent pour enrichir le contexte
    collected_context = ""
    try:
        rows = db.conn.execute(
            "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 20",
            (user_id or "",),
        ).fetchall()
        if rows:
            collected_context = "CONTEXTE ADDITIONNEL COLLECTE PAR L'AGENT :\n" + "\n".join(
                f"  - {r[0]}: {r[1]}" for r in rows
            )
    except Exception:
        pass
    # Chercher dans les messages agent les infos pertinentes à l'événement
    try:
        msg_rows = db.conn.execute(
            "SELECT role, content FROM agent_messages WHERE auth_user_id = ? ORDER BY created_at DESC LIMIT 30",
            (user_id or "",),
        ).fetchall()
        if msg_rows:
            desc_lower = data.description.lower()
            relevant_msgs = []
            for r in msg_rows:
                content_lower = r[1].lower()
                for word in data.description.split():
                    if len(word) > 3 and word.lower() in content_lower:
                        relevant_msgs.append(f"{'Utilisateur' if r[0] == 'user' else 'Agent'}: {r[1][:250]}")
                        break
            if relevant_msgs:
                collected_context += "\n\nINFORMATIONS PERTINENTES (conversations precedentes) :\n" + "\n".join(
                    f"  - {m}" for m in relevant_msgs[:5]
                )
                collected_context += "\n\nIMPORTANT : Utilise ces informations pour personnaliser ton analyse."
    except Exception:
        pass

    full_ctx = build_full_user_context(db, user_id, profil)
    try:
        result = await _analyser_evenement_claude(
            description=data.description,
            objectif_desc=profil.objectif.description,
            objectif_cat=profil.objectif.categorie,
            prob_actuelle=profil.probabilite_actuelle,
            prob_calculee=profil.objectif.probabilite_calculee,
            profession=profil.profession or "",
            device_context=format_device_context(data.contexte_appareil),
            collected_context=collected_context,
            full_context=full_ctx,
        )
        return AnalyseEvenementOut(**result)
    except Exception as e:
        import traceback
        print(f"[EVENEMENT] Claude API error: {e}")
        traceback.print_exc()
        result = _analyser_evenement_local(data.description, profil.objectif.description)
        return AnalyseEvenementOut(**result)


@router.post("/confirmer", response_model=DecisionOut)
async def confirmer_evenement(
    data: ConfirmerEvenementIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Enregistre l'evenement et met a jour la probabilite."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # Anti-doublon: meme evenement deja enregistre
    existing = profil_repo._db.conn.execute(
        "SELECT id FROM decisions WHERE user_id = ? AND question = ?",
        (profil.id, f"[Evenement] {data.description}"),
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Cet evenement a deja ete enregistre.")

    # Creer une option unique representant l'evenement
    opt_event = OptionDilemme(
        description=data.description,
        impact_score=data.impact_probabilite,
        explication_impact=data.resume,
    )

    prob_avant = profil.probabilite_actuelle
    prob_apres = prob_avant + data.impact_probabilite
    prob_apres = max(0.01, min(99.9, prob_apres))

    # Creer la decision (type evenement = question prefixee)
    decision = Decision(
        user_id=profil.id,
        question=f"[Evenement] {data.description}",
        options=[opt_event],
        probabilite_avant=prob_avant,
        option_choisie_id=opt_event.id,
        probabilite_apres=prob_apres,
    )

    decision_repo.sauvegarder(decision)

    # Mettre a jour le profil
    profil.probabilite_actuelle = prob_apres
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    # Identifier et mettre a jour le sous-objectif pertinent via IA
    so_titre_impacte = None
    try:
        db = profil_repo._db
        all_so = db.conn.execute(
            "SELECT id, titre, progression, ordre, temps_estime FROM sous_objectifs WHERE user_id = ? AND progression < 100 ORDER BY ordre",
            (profil.id,),
        ).fetchall()
        if all_so:
            so_cible = await _identifier_so_pertinent(data.description, all_so)
            if so_cible is None:
                so_cible = all_so[0]  # fallback: premier par ordre
            total_te = sum(max(30, so["temps_estime"] or 180) for so in all_so)
            te = max(30, so_cible["temps_estime"] if so_cible["temps_estime"] else 180)
            # Impact signé : positif = progression, négatif = régression
            impact_so = data.impact_probabilite * (total_te / te)  # amplifie proportionnellement
            new_prog = so_cible["progression"] + impact_so

            # Plafonner entre 0 et 100
            if new_prog < 0:
                new_prog = 0

            # Si le SO dépasse 100%, redistribuer l'excédent sur les autres SO
            if new_prog >= 100:
                overflow = new_prog - 100
                new_prog = 100
                db.conn.execute(
                    "UPDATE sous_objectifs SET progression = 100 WHERE id = ?",
                    (so_cible["id"],),
                )
                # Redistribuer l'overflow sur les SO restants (non complétés)
                remaining_so = [s for s in all_so if s["id"] != so_cible["id"] and s["progression"] < 100]
                while overflow > 0.01 and remaining_so:
                    share = overflow / len(remaining_so)
                    next_remaining = []
                    for s in remaining_so:
                        current = db.conn.execute(
                            "SELECT progression FROM sous_objectifs WHERE id = ?",
                            (s["id"],),
                        ).fetchone()
                        cur_prog = current["progression"] if current else s["progression"]
                        new_p = cur_prog + share
                        if new_p >= 100:
                            overflow_part = new_p - 100
                            db.conn.execute(
                                "UPDATE sous_objectifs SET progression = 100 WHERE id = ?",
                                (s["id"],),
                            )
                            overflow = overflow_part
                        else:
                            db.conn.execute(
                                "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                                (new_p, s["id"]),
                            )
                            next_remaining.append(s)
                            overflow = 0
                    remaining_so = next_remaining
                    if not remaining_so:
                        break
            else:
                new_prog = max(0, new_prog)
                db.conn.execute(
                    "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                    (new_prog, so_cible["id"]),
                )
            db.conn.commit()
            so_titre_impacte = so_cible["titre"]
            # Persister le lien SO dans la décision
            decision.sous_objectif_id = so_cible["id"]
            decision.impact_sous_objectif = impact_so
            decision_repo.sauvegarder(decision)
    except Exception:
        pass

    return _decision_to_out(decision, sous_objectif_impacte=so_titre_impacte)
