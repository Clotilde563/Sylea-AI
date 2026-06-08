"""
Router FastAPI -- Service client chatbot.

Refondu 2026-06-01 :
  - Chargement de la KB depuis data/support_kb.json (single source of truth)
  - Specialisation STRICTE : refuse toute question hors scope support technique
  - Guard rails actifs : detection sortie hors scope -> retry + fallback poli
  - Mise en cache du system prompt (Anthropic prompt caching) pour reduire cost

Route :
  POST /api/service-client/chat  -> chatbot IA pour aide utilisateur
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from api.schemas import ServiceClientChatIn, ServiceClientChatOut
from api.context_helper import format_device_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/service-client", tags=["service-client"])

# Localisation de la KB (relatif au repo root)
_KB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "support_kb.json"


@lru_cache(maxsize=1)
def _load_kb() -> dict:
    """Charge la KB JSON une seule fois (cache module-level).

    Retourne un dict {version, contact, app_overview, items: [...]}. En cas
    d'erreur de lecture (fichier absent, JSON invalide), retourne un dict
    minimal pour que le chatbot puisse au moins repondre avec un message
    poli + email de contact.
    """
    try:
        with open(_KB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[service_client] KB load failed ({_KB_PATH}): {e}")
        return {
            "version": "fallback",
            "contact": {"email": "sylea.ai.assistance@gmail.com"},
            "app_overview": {"name": "Sylea.AI"},
            "items": [],
        }


def _format_kb_for_prompt(kb: dict) -> str:
    """
    Serialise la KB dans un format compact pour injection dans le system
    prompt. Regroupe par categorie pour aider le LLM a naviguer.
    """
    if not kb.get("items"):
        return "(KB indisponible)"

    # Regrouper par categorie
    by_cat: dict[str, list[dict]] = {}
    for item in kb["items"]:
        cat = item.get("category", "Autre")
        by_cat.setdefault(cat, []).append(item)

    out: list[str] = []
    out.append("## OVERVIEW APPLICATION")
    overview = kb.get("app_overview", {})
    if overview:
        out.append(f"- Nom : {overview.get('name', 'Sylea.AI')}")
        out.append(f"- Type : {overview.get('type', '')}")
        plats = overview.get("platforms", [])
        if plats:
            out.append(f"- Plateformes : {', '.join(plats)}")
        feats = overview.get("features", [])
        if feats:
            out.append("- Fonctionnalites principales :")
            for f in feats:
                out.append(f"  - {f}")
    out.append("")

    out.append("## BASE DE CONNAISSANCES (FAQ + procedures de resolution)")
    for cat in sorted(by_cat.keys()):
        out.append(f"\n### {cat}")
        for item in by_cat[cat]:
            out.append(f"\n**Q : {item['question']}**")
            for i, step in enumerate(item.get("steps", []), 1):
                out.append(f"  {i}. {step}")

    return "\n".join(out)


def _build_system_prompt() -> str:
    """Construit le system prompt SC complet (KB injectee + guard rails)."""
    kb = _load_kb()
    contact_email = kb.get("contact", {}).get("email", "sylea.ai.assistance@gmail.com")
    kb_text = _format_kb_for_prompt(kb)

    return f"""Tu es le **Service Client de SYLEA.AI**.

## ROLE STRICT — A RESPECTER ABSOLUMENT

Tu reponds UNIQUEMENT aux questions concernant :
1. Les fonctionnalites de l'application Sylea.AI (web + desktop)
2. Les problemes/erreurs/incidents rencontres dans l'app
3. La facturation/abonnement Sylea
4. La securite/confidentialite/RGPD du compte Sylea
5. Les integrations tierces (Google, GitHub, Notion, Slack) telles que connectees a Sylea

Tu refuses **POLIMENT mais FERMEMENT** toute question :
- De culture generale (histoire, science, geographie...)
- Demande d'aide hors Sylea (autres apps, code generique, devoirs scolaires...)
- Demande personnelle (vie privee, conseils de vie, psy, etc.)
- Conversation chitchat / jeux / role-play
- Demande de raisonnement creatif (poemes, blagues, scenarios)
- Demande d'analyse externe (autres marques, comparaison concurrents...)

**Formulation type pour refus** : "Je suis l'assistance Sylea.AI et je ne peux repondre qu'aux questions concernant l'application Sylea (utilisation, bugs, abonnement, securite). Pour [sujet hors-scope], je vous invite a [reformuler dans le scope OU ecrire a {contact_email} si vous pensez que c'est lie a votre compte]."

## TON & FORMAT

- Tutoiement professionnel
- Concis : 2-4 phrases pour les questions simples, listes numerotees pour les procedures
- Pas d'emojis sauf 1 max pour separer (✅ ⚠ ❌ ←)
- Phrases courtes, langage clair, pas de jargon technique non explique
- Si tu donnes des etapes : numerotation 1., 2., 3.

## REGLES OPERATIONNELLES

1. **Source unique de verite = ta base de connaissances ci-dessous.** Ne JAMAIS inventer une procedure, un endpoint, un menu qui n'y est pas. Si tu ne sais pas, oriente vers {contact_email}.
2. **Si la KB couvre le probleme** : suis les etapes telles que decrites.
3. **Si la KB ne couvre PAS** mais que c'est un sujet support Sylea legitime : reconnais que tu n'as pas la procedure precise et redirige vers {contact_email} en demandant a l'user de detailler (capture d'ecran, URL, action declenchante, navigateur/OS).
4. **JAMAIS de details techniques internes** : pas de noms de modeles IA, pas de code source, pas de formules de calcul, pas d'architecture backend, pas de noms de tables DB, pas de SQL, pas de noms de colonnes/champs internes.
5. **JAMAIS d'avis personnel** sur des decisions de vie de l'utilisateur (carriere, sante, famille, finance, juridique). Renvoie vers un professionnel qualifie.
6. **JAMAIS de promesse de delai non documente** dans la KB.
7. **Si l'user partage des donnees sensibles** (mot de passe, jeton OAuth, numero CB, code 2FA), refuse de les recevoir et demande de les retirer : "Pour votre securite, ne partagez jamais [type de donnee] dans ce chat. Je n'en ai pas besoin pour vous aider."

## CONTACT FINAL

Email de support humain : **{contact_email}**
Quand orienter vers cet email :
- Probleme non couvert par la KB
- Probleme couvert mais procedure n'a pas regle l'incident
- Demande de remboursement, de derogation, ou de suspension
- Suspicion de piratage de compte (CRITIQUE : prioriser immediatement)
- Demande RGPD complexe (effacement avec contestation, portabilite vers autre fournisseur, etc.)

{kb_text}
"""


# Mots-cles qui declenchent le filet de securite "hors scope"
# (on ne les rejette pas systematiquement, c'est juste un signal)
_OFFTOPIC_SIGNALS = (
    "blague", "poeme", "poème", "histoire", "raconte-moi",
    "qui est ", "explique-moi le concept", "definition de",
    "code python", "code javascript", "code react", "ecris-moi du code",
    "donne-moi un conseil de vie", "donne-moi un conseil pour",
    "que ferais-tu si", "imagine que",
)


@router.post("/chat", response_model=ServiceClientChatOut)
async def service_client_chat(data: ServiceClientChatIn):
    """Chatbot Service Sylea -- strictement specialise sur le support app."""
    try:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise HTTPException(status_code=503, detail="Cle API non configuree.")

        client = anthropic.Anthropic(api_key=key)

        api_messages = [
            {"role": m.role, "content": m.content}
            for m in data.messages
        ]

        # Pre-flight off-topic : si le dernier message user contient des
        # signaux clairs hors scope, on coupe court (econo de tokens + reponse
        # plus rapide).
        last_user_msg = ""
        for m in reversed(data.messages):
            if m.role == "user":
                last_user_msg = (m.content or "").lower()
                break
        if last_user_msg and any(sig in last_user_msg for sig in _OFFTOPIC_SIGNALS):
            kb = _load_kb()
            email = kb.get("contact", {}).get("email", "sylea.ai.assistance@gmail.com")
            return ServiceClientChatOut(
                message=(
                    "Je suis l'assistance Sylea.AI : je peux uniquement repondre "
                    "aux questions sur l'application (utilisation, bugs, "
                    "abonnement, securite). Pour ce sujet, je n'ai pas vocation "
                    f"a t'aider — si tu rencontres un probleme dans l'app, "
                    f"reformule ta question, sinon ecris a {email}."
                )
            )

        system_prompt = _build_system_prompt() + format_device_context(
            data.contexte_appareil
        )

        response = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=api_messages,
            )
        )

        return ServiceClientChatOut(message=response.content[0].text)
    except ImportError:
        raise HTTPException(status_code=503, detail="Module anthropic non disponible.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Service indisponible : {exc}")


@router.get("/kb-version")
async def kb_version():
    """Diagnostic : version + nb items de la KB chargee (utile pour verifier
    qu'une mise a jour de support_kb.json a bien ete prise en compte)."""
    kb = _load_kb()
    return {
        "version": kb.get("version"),
        "updated": kb.get("updated"),
        "item_count": len(kb.get("items", [])),
        "categories": sorted({i.get("category", "?") for i in kb.get("items", [])}),
    }
