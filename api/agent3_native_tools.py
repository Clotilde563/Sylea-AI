"""
Agent 3 — Native Tool Calling + Agentic Loop.

Ce module remplace progressivement le parsing regex `[ACTION:X]{json}[/ACTION]`
par l'API tool calling native d'Anthropic, et enveloppe l'appel LLM dans une
boucle agentique multi-tours (tool_use -> executer -> tool_result -> LLM).

Objectifs :
  1. Supprimer les hallucinations d'actions (le LLM ne peut plus inventer d'actions,
     il doit passer par l'API structuree).
  2. Permettre l'iteration : le LLM observe le resultat de chaque outil et
     ajuste sa strategie, appelle d'autres outils, ou conclut.
  3. Remonter les erreurs au LLM (is_error=True) pour qu'il puisse reessayer
     ou changer d'approche.

Architecture :
  - `build_tool_schemas()` -> [tool_definition] pour `client.messages.create(tools=...)`
  - `AgenticLoop` -> classe qui orchestre la boucle LLM <-> tools
  - `ActionDispatcher` -> protocole que doit implementer tout executeur d'actions
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

logger = logging.getLogger("agent3.native_tools")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Tool Schemas — mapping action_type -> Anthropic tool definition
# ══════════════════════════════════════════════════════════════════════════════

# Descriptions riches pour chaque outil. Le LLM choisit un outil en lisant ces
# descriptions, donc il faut etre precis sur quand chaque outil s'applique.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "SEARCH": "Recherche web generale via DuckDuckGo. Utilise pour actualites, "
              "informations factuelles, recherches rapides. Retourne une liste de resultats.",
    "X_SEARCH": "Recherche sur X/Twitter via xAI Grok. Utilise pour opinions, "
                "tendances, actualites en temps reel sur les reseaux sociaux.",
    "WEB_FETCH": "Recupere le contenu d'une URL specifique (HTML, markdown, JSON). "
                 "Utilise quand tu connais deja l'URL exacte a lire.",
    "BROWSER": "Charge une URL dans un navigateur Chromium headless (Playwright) et "
               "execute une action : 'read' (texte rendu apres JS), 'screenshot' (PNG), "
               "'html' (DOM complet), 'eval' (execute JS). Utilise quand `web_fetch` ne "
               "suffit pas (sites SPA, contenu charge dynamiquement, login persistant).",
    "SCREENSHOT": "Capture d'ecran d'une page web via Chromium headless. Retourne PNG "
                  "en base64 + URL servable. Idem `browser` action=screenshot mais plus "
                  "simple pour le LLM.",
    "MEMORY": "Sauvegarde une information importante pour s'en souvenir dans les "
              "sessions futures. Prend une cle semantique et une valeur.",
    "MEMORY_SEARCH": "Cherche dans la memoire long-terme de l'utilisateur par mot-cle.",
    "PDF": "Genere un rapport PDF structure avec titre et sections. Utilise pour "
           "rapports formels, documents a partager.",
    "IMAGE": "Genere une image via un modele de diffusion a partir d'un prompt textuel. "
             "Utilise pour illustrations, visualisations.",
    "EMAIL": "Envoie un email via SMTP ou Gmail API. ACTION DESTRUCTIVE. "
             "Utilise uniquement si l'utilisateur a explicitement demande d'envoyer un mail.",
    "GMAIL_SEND": "Envoie un email via l'API Gmail (OAuth). ACTION DESTRUCTIVE. "
                  "Preferable a EMAIL quand l'utilisateur est connecte a Gmail.",
    "GMAIL_READ": "Lit les emails recents de la boite Gmail de l'utilisateur.",
    "CALENDAR_EVENT": "Cree un evenement dans le calendrier Google. ACTION DESTRUCTIVE.",
    "CALENDAR_LIST": "Liste les prochains evenements du calendrier Google.",
    "FILE_CREATE": "Cree un fichier dans le workspace de l'utilisateur. ACTION DESTRUCTIVE "
                   "(ecrit sur disque). Le champ 'path' est relatif au workspace.",
    "FILE_READ": "Lit le contenu d'un fichier du workspace de l'utilisateur.",
    "DRIVE_SAVE": "Sauvegarde un fichier dans Google Drive. ACTION DESTRUCTIVE.",
    "CRON": "Cree une tache recurrente programmee. ACTION DESTRUCTIVE. "
            "Utilise uniquement pour automatiser une action future.",
    "CODE": "Genere et affiche un bloc de code avec coloration syntaxique. "
            "Pas d'execution — juste rendu pour l'utilisateur.",
    "COMPUTER_USE": "Controle autonome du navigateur via l'API Anthropic Computer Use. "
                    "ACTION DESTRUCTIVE ET COUTEUSE. Utilise UNIQUEMENT pour des taches "
                    "qui necessitent vraiment une navigation visuelle (formulaires "
                    "complexes, apps sans API, scraping avec interaction). Prompt descriptif "
                    "de l'objectif attendu.",
    "SCREENSHOT": "Prend une capture d'ecran d'une URL donnee. Utile pour apercu visuel "
                  "d'un site, extraction de mise en page.",
    "CANVAS": "Affiche un element interactif (graphique, diagramme, visualisation) dans "
              "le chat. Pas d'execution externe.",
    "SPAWN_AGENT": "[**TOOL OFFICIEL** pour deleguer ou paralleliser des recherches/analyses] "
                   "Delegue une OU plusieurs sous-taches a des agents enfants autonomes "
                   "(lecture seule, Haiku 4.5). DEUX MODES :\n"
                   "  1) SINGLE : `description` + `task` -> 1 sous-agent.\n"
                   "  2) PARALLEL : `tasks: [{description, task, max_turns?}, ...]` "
                   "(2-8 items). Les agents tournent en parallele via asyncio.gather, "
                   "latence = max(latence_i) et non somme. Resultats agreges.\n"
                   "**A UTILISER SYSTEMATIQUEMENT** des que l'utilisateur dit 'en parallele', "
                   "'plusieurs recherches simultanees', 'lance N sous-agents', 'compare X et "
                   "Y et Z' (multi-cibles), 'cherche A B C en meme temps'. **NE PAS** utiliser "
                   "PYTHON_EXEC pour scripter des appels paralleles : SPAWN_AGENT.tasks le "
                   "fait nativement avec retry, timeout et agregation gratuites.\n"
                   "L'enfant ne peut pas utiliser d'actions destructives ni se re-spawn.",
    "TODO_WRITE": "Cree ou met a jour une liste de taches (todos) partagee avec "
                  "l'utilisateur. A utiliser pour planifier et suivre l'execution "
                  "d'une demande multi-etapes (3+ etapes). Modes : "
                  "'create' (cree une liste), 'start' (passe un todo en running), "
                  "'complete' (marque un todo comme fait), 'fail' (marque comme echoue), "
                  "'skip' (marque comme saute), 'list' (retourne l'etat courant).",
    # Phase 7 — RAG + sandbox Python + Deep Research
    "SEMANTIC_SEARCH": "[RAG INDEX SYLEA] Recherche dans le contenu indexe automatiquement "
                       "par Sylea : pages web fetchees, fichiers PDF/Word/Excel uploades, "
                       "documents longs. Utilise des embeddings vectoriels + cosine similarity. "
                       "**A UTILISER en PRIORITE** quand l'utilisateur demande de retrouver des "
                       "infos dans un document, un site, ou un fichier qu'il a deja partage. "
                       "Exemples: 'qu'avons-nous vu dans la doc FastAPI ?', 'le PDF parlait de "
                       "quoi ?', 'cherche dans nos documents'. NE PAS confondre avec memory_search "
                       "(qui cherche les souvenirs explicites en SQL LIKE) ni oc_memory_search "
                       "(qui cherche dans la memoire OpenClaw Gateway, pas dans les docs Sylea).",
    "PYTHON_EXEC": "[SANDBOX SAFE — UTILISE EN PRIORITE pour TOUT calcul/analyse Python] "
                   "Execute du code Python dans un sandbox isole (subprocess Sylea, timeout 30s, "
                   "sans acces reseau ni filesystem). Supporte numpy, pandas, matplotlib, scipy, "
                   "math, statistics. Les figures matplotlib sont auto-sauvees + URLs retournees. "
                   "**A UTILISER SYSTEMATIQUEMENT pour** : calculs precis (interets composes, "
                   "stats, mediane, ecart-type, percentiles), generation de nombres aleatoires, "
                   "histogrammes/courbes/plots, traitement de listes/CSV inline, conversions, "
                   "simulations Monte-Carlo, etc. **NE JAMAIS confondre avec `exec` (OpenClaw, "
                   "destructif, lance des commandes shell systeme — DERNIER RECOURS uniquement). "
                   "Pour Python pur dans un sandbox safe, c'est PYTHON_EXEC qu'il faut.**",
    "DEEP_RESEARCH": "Lance un sous-agent specialise pour une recherche approfondie "
                     "multi-tours (search + fetch + cross-reference + synthese avec "
                     "citations). COUTEUX : chaque appel consomme un budget de tokens "
                     "(~$0.50 par defaut). Utilise UNIQUEMENT pour des questions qui "
                     "necessitent un rapport structure avec sources multiples.",
    # Phase 8 — Vision & File analyze
    "VISION_ANALYZE": "Analyse une image deja uploadee par l'utilisateur via Claude Vision. "
                      "Utilise quand l'utilisateur pose une question precise sur une image "
                      "(ex: 'qu'est-ce qui est ecrit sur ce graphique', 'quelle couleur "
                      "domine', 'extraits le texte de cette capture'). Passe le file_id "
                      "et un prompt specifique.",
    "OPENCLAW_SESSION": "Spawn une session OpenClaw autonome avec acces COMPLET aux outils "
                        "d'exploration (search/web/browser/screenshot/file/calendar/gmail/"
                        "python/clawhub/vision). Utilise quand l'utilisateur demande "
                        "explicitement une session OpenClaw complete pour explorer un "
                        "projet, faire un audit, ou un rapport multi-sources. Plus puissant "
                        "que SPAWN_AGENT (Sonnet 4.5 + 18 tools vs Haiku + 8). "
                        "COUTEUX : ~$0.50-2.00 par session selon turns.",
    "IMAGE_GEN": "[**TOOL OFFICIEL** generation image] Genere une image avec OpenAI DALL-E 3. "
                 "Utilise OPENAI_API_KEY (deja configuree). **PREFERE ce tool a `image_generate` "
                 "ou aux skills `ai-image`/`skill_*image*`** qui peuvent necessiter des cles API "
                 "tierces non configurees. Cout : ~$0.04 (standard) ou $0.08 (hd) par image. "
                 "Retourne un filename + URL servi via /api/agent3/image/<filename>.",
    "TTS_GEN": "[**TOOL OFFICIEL** synthese vocale] Genere de l'audio avec OpenAI TTS-1 "
               "(voix Nova par defaut). Utilise OPENAI_API_KEY. **PREFERE ce tool aux skills "
               "TTS tierces** qui peuvent necessiter des cles API non configurees. Cout : "
               "~$0.00001 par caractere (~$0.0001 pour une phrase de 100 chars). Retourne "
               "un filename MP3 + URL servi via /api/agent3/audio/<filename>.",
}

# Mapping input schema par action_type. Base sur REQUIRED_FIELDS de ActionValidator
# mais enrichi (types precis, enums, champs optionnels utiles).
_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requete de recherche en langage naturel."},
            "max_results": {"type": "integer", "description": "Nombre max de resultats (1-10).", "default": 5},
        },
        "required": ["query"],
    },
    "X_SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requete X/Twitter. Ex: 'AI agents trends 2025'."},
        },
        "required": ["query"],
    },
    "WEB_FETCH": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL HTTP(S) complete a recuperer."},
        },
        "required": ["url"],
    },
    # Phase 14I : tool BROWSER natif (Playwright Chromium headless).
    # Pour pages JS-heavy (SPA, contenu dynamique) ou simulation utilisateur
    # (clic, scroll, screenshot, lecture DOM apres render).
    "BROWSER": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL a charger (HTTP/HTTPS)."},
            "action": {
                "type": "string",
                "description": "Type d'action : 'read' (texte de la page), 'screenshot' (PNG), 'html' (DOM brut), 'eval' (JS). Defaut: 'read'.",
                "enum": ["read", "screenshot", "html", "eval"],
            },
            "script": {"type": "string", "description": "JS a evaluer si action='eval'."},
            "wait_for": {"type": "string", "description": "Selector CSS a attendre avant lecture (optionnel)."},
            "timeout_ms": {"type": "integer", "description": "Timeout en ms (defaut 15000, max 60000).", "default": 15000},
        },
        "required": ["url"],
    },
    # Tool SCREENSHOT raccourci (= BROWSER avec action='screenshot').
    # Plus simple a invoquer pour le LLM quand il veut juste capturer une page.
    "SCREENSHOT": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL de la page a capturer."},
            "full_page": {"type": "boolean", "description": "Si true, capture toute la page (scroll). Defaut: viewport seul.", "default": False},
            "timeout_ms": {"type": "integer", "description": "Timeout en ms (defaut 15000).", "default": 15000},
        },
        "required": ["url"],
    },
    "MEMORY": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Cle semantique courte, ex: 'preference_langue'."},
            "value": {"type": "string", "description": "Valeur a memoriser."},
        },
        "required": ["key", "value"],
    },
    "MEMORY_SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Mot-cle ou phrase a chercher dans la memoire."},
        },
        "required": ["query"],
    },
    # Phase 7 — RAG + sandbox + research
    "SEMANTIC_SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requete semantique en langage naturel."},
            "top_k": {"type": "integer", "description": "Nombre max de resultats (1-20).", "default": 5},
            "source_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filtre par type de source (ex: ['web_fetch', 'upload']). Optionnel.",
            },
        },
        "required": ["query"],
    },
    "PYTHON_EXEC": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Code Python a executer. Max 50000 chars."},
        },
        "required": ["code"],
    },
    "DEEP_RESEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Question de recherche structuree."},
            "max_iterations": {"type": "integer", "description": "Nb max de tours du sous-agent (3-25).", "default": 10},
            "budget_usd": {"type": "number", "description": "Budget $ (0.10-2.00).", "default": 0.50},
        },
        "required": ["query"],
    },
    "VISION_ANALYZE": {
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Id du fichier image uploade (renvoye par /upload).",
            },
            "prompt": {
                "type": "string",
                "description": "Question precise sur l'image. Ex: 'Quel est le texte dans l'en-tete ?'",
            },
        },
        "required": ["file_id", "prompt"],
    },
    "PDF": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "description": "Liste de sections {heading, content}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["heading", "content"],
                },
            },
            "color": {"type": "string", "description": "Couleur primaire hex, ex: '#2563eb'.", "default": "#2563eb"},
        },
        "required": ["title", "sections"],
    },
    "IMAGE": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Description textuelle de l'image a generer."},
        },
        "required": ["prompt"],
    },
    "EMAIL": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Adresse email du destinataire."},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Corps du message en texte brut."},
        },
        "required": ["to", "subject", "body"],
    },
    "GMAIL_SEND": {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    },
    "GMAIL_READ": {
        "type": "object",
        "properties": {
            "mailbox": {"type": "string", "description": "Boite a lire.", "default": "INBOX"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": [],
    },
    "CALENDAR_EVENT": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "ISO 8601 debut, ex: '2026-04-20T14:00:00'."},
            "end": {"type": "string", "description": "ISO 8601 fin (optionnel)."},
            "description": {"type": "string"},
        },
        "required": ["title", "start"],
    },
    "CALENDAR_LIST": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 7},
        },
        "required": [],
    },
    "FILE_CREATE": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Nom de fichier avec extension, ex: 'rapport.md'."},
            "content": {"type": "string"},
            "path": {"type": "string", "description": "Chemin relatif optionnel dans le workspace."},
        },
        "required": ["filename", "content"],
    },
    "FILE_READ": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
        },
        "required": ["filename"],
    },
    "DRIVE_SAVE": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["filename", "content"],
    },
    "CRON": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "instruction": {"type": "string", "description": "Instruction a executer lors du declenchement."},
            "cron_expr": {"type": "string", "description": "Expression cron standard a 5 champs."},
        },
        "required": ["label", "instruction", "cron_expr"],
    },
    "REMINDER": {
        "type": "object",
        "description": "Programme un rappel ponctuel (one-shot). Utilise delay_minutes pour 'dans Xh/Xmin' ou reminder_date+reminder_time pour une date precise.",
        "properties": {
            "message": {"type": "string", "description": "Texte du rappel a afficher."},
            "delay_minutes": {"type": "integer", "description": "Delai en minutes a partir de maintenant. Ex: 120 pour 'dans 2h', 60 pour 'dans 1h', 30 pour 'dans 30 min'. Prioritaire sur reminder_date/time."},
            "reminder_date": {"type": "string", "description": "Date au format YYYY-MM-DD (ex: 2026-04-29). Optionnel si delay_minutes fourni."},
            "reminder_time": {"type": "string", "description": "Heure au format HH:MM (ex: 14:30). Optionnel si delay_minutes fourni."},
        },
        "required": ["message"],
    },
    "CODE": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "language": {"type": "string", "default": "python"},
        },
        "required": ["content"],
    },
    "COMPUTER_USE": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Objectif en langage naturel pour le Computer Use agent."},
        },
        "required": ["prompt"],
    },
    "SCREENSHOT": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
        },
        "required": ["url"],
    },
    "CANVAS": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Markdown ou HTML du canvas."},
        },
        "required": ["title", "content"],
    },
    "SPAWN_AGENT": {
        "type": "object",
        "description": (
            "Soit (mode single) : remplir description+task. "
            "Soit (mode parallel) : remplir tasks=[{description,task,max_turns?},...] "
            "(2-8 items). Au moins UN des deux est requis."
        ),
        "properties": {
            "description": {
                "type": "string",
                "description": "[MODE SINGLE] Description courte de l'agent enfant (3-5 mots). Ex: 'Recherche concurrents IA'.",
            },
            "task": {
                "type": "string",
                "description": "[MODE SINGLE] Instruction detaillee que l'agent enfant doit accomplir. "
                               "Doit etre auto-suffisante : l'enfant n'a pas acces a la conversation parente.",
            },
            "max_turns": {
                "type": "integer",
                "description": "[MODE SINGLE] Plafond de tours pour l'enfant (1-10).",
                "default": 5,
            },
            "tasks": {
                "type": "array",
                "description": "[MODE PARALLEL] Liste de 2-8 taches independantes a executer "
                               "EN PARALLELE via asyncio.gather. UTILISE ce mode des que "
                               "l'utilisateur demande plusieurs recherches/analyses simultanees "
                               "('compare X et Y', 'cherche A, B et C en meme temps', "
                               "'lance 3 sous-agents'). Format de chaque item : "
                               "{description, task, max_turns?}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "task": {"type": "string"},
                        "max_turns": {"type": "integer", "default": 5},
                    },
                    "required": ["description", "task"],
                },
            },
        },
        # PAS de "required" top-level : le dispatcher valide qu'au moins UN mode est fourni.
    },
    "OPENCLAW_SESSION": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Description complete de la mission de la session OpenClaw "
                               "(ex: 'Audit du projet X', 'Explorer le codebase de Y', "
                               "'Synthese multi-sources sur Z'). Doit etre auto-suffisante.",
            },
            "max_turns": {
                "type": "integer",
                "description": "Plafond de tours pour la session OpenClaw (1-15, defaut 8).",
                "default": 8,
            },
        },
        "required": ["prompt"],
    },
    "IMAGE_GEN": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Description detaillee de l'image a generer (en anglais "
                               "ou francais, DALL-E comprend les deux). Plus le prompt est "
                               "riche en details visuels, plus le resultat sera precis.",
            },
            "size": {
                "type": "string",
                "enum": ["1024x1024", "1792x1024", "1024x1792"],
                "description": "Dimensions de l'image (carre par defaut, paysage 16:9, ou portrait 9:16).",
                "default": "1024x1024",
            },
            "quality": {
                "type": "string",
                "enum": ["standard", "hd"],
                "description": "standard (~$0.04) ou hd (~$0.08, details fins).",
                "default": "standard",
            },
        },
        "required": ["prompt"],
    },
    "TTS_GEN": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Texte a vocaliser (max 4096 chars). Idealement en francais "
                               "ou anglais. Ponctuation respectee pour le rythme.",
            },
            "voice": {
                "type": "string",
                "enum": ["nova", "alloy", "echo", "fable", "onyx", "shimmer"],
                "description": "Voix OpenAI : nova (feminine, francais OK), alloy (neutre), "
                               "echo (masculine), fable (anglais brit), onyx (grave), shimmer (douce).",
                "default": "nova",
            },
            "speed": {
                "type": "number",
                "description": "Vitesse de parole 0.25-4.0 (1.0 = normal).",
                "default": 1.0,
            },
        },
        "required": ["text"],
    },
    "TODO_WRITE": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["create", "start", "complete", "fail", "skip", "list"],
                "description": "Operation a effectuer sur le tracker de todos.",
            },
            "items": {
                "type": "array",
                "description": "Pour 'create' : liste de {title, active_form, group}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "active_form": {"type": "string"},
                        "group": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
            "item_id": {
                "type": "string",
                "description": "Id du todo cible pour start/complete/fail/skip.",
            },
            "result": {
                "type": "string",
                "description": "Resultat/commentaire pour complete/skip.",
            },
            "error": {
                "type": "string",
                "description": "Raison d'echec pour fail.",
            },
        },
        "required": ["mode"],
    },
}


def build_tool_schemas(
    enabled_actions: set[str] | None = None,
    *,
    include_clawhub_skills: bool = False,
    enabled_clawhub_slugs: set[str] | None = None,
    include_clawhub_meta_tools: bool = False,
    clawhub_include_bundled: bool = True,
    clawhub_include_user: bool = True,
    auth_user_id: str | None = None,
    include_openclaw_direct_tools: bool = False,
    enabled_openclaw_tools: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Construit la liste des tool definitions pour client.messages.create(tools=...).

    Args:
      enabled_actions: si fourni, filtre les tools natifs pour ne garder que
        ces action types.
      include_clawhub_skills: si True, fusionne les skills ClawHub (bundled +
        installees pour le user courant) sous forme de tools `skill_<slug>`.
        Chaque skill expose un parametre `instruction` en langage naturel.
      enabled_clawhub_slugs: filtre les skills ClawHub a inclure (None = toutes).
      include_clawhub_meta_tools: si True, ajoute les 3 meta-tools de gestion
        ClawHub : `clawhub_search`, `clawhub_install`, `clawhub_publish`.
        Ces meta-tools permettent a l'agent d'etendre ses capacites en cours
        d'execution (self-extending agent).
      clawhub_include_bundled: inclure les 54 skills bundled avec OpenClaw npm.
      clawhub_include_user: inclure les skills installees pour le user courant.
      auth_user_id: si fourni, isoler les skills user au dossier
        `~/.sylea/users/{id}/.openclaw/skills/`. Sinon fallback legacy partage.
      include_openclaw_direct_tools: si True, expose les 38 outils OpenClaw
        directement au LLM (browser, exec, fs.read/write, image_generate, ...).
        Chaque outil est invoquable par son nom (`browser`, `exec`, ...) et
        route vers `openclaw_invoke_tool()` du Gateway.
      enabled_openclaw_tools: filtre des noms Anthropic (ex: {"browser", "exec"}).
        None = les 38.

    Returns:
      Liste de dicts {"name": str, "description": str, "input_schema": dict}
      L'ordre est : tools natifs -> meta-tools clawhub -> skills clawhub ->
      outils OpenClaw directs.
    """
    tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # 1) Tools natifs Agent 3 (SEARCH, WEB_FETCH, MEMORY, PDF, ...)
    for action_type, schema in _INPUT_SCHEMAS.items():
        if enabled_actions is not None and action_type not in enabled_actions:
            continue
        description = _TOOL_DESCRIPTIONS.get(action_type, f"Action {action_type}.")
        # Les noms de tool Anthropic : [a-zA-Z0-9_-], max 64 chars.
        tool_name = action_type.lower()
        tools.append({
            "name": tool_name,
            "description": description,
            "input_schema": schema,
        })
        seen_names.add(tool_name)

    # 2) Meta-tools ClawHub (gestion du registre a chaud)
    if include_clawhub_meta_tools:
        try:
            from api.agent3_skills.clawhub_meta_tools import CLAWHUB_META_TOOL_SCHEMAS
            for mt in CLAWHUB_META_TOOL_SCHEMAS:
                if mt["name"] in seen_names:
                    logger.warning(f"Meta-tool name collision: {mt['name']}")
                    continue
                tools.append(mt)
                seen_names.add(mt["name"])
        except ImportError:
            logger.debug("clawhub_meta_tools not available yet (Part C pending)")

    # 3) Skills ClawHub (bundled + installees)
    if include_clawhub_skills:
        try:
            from api.agent3_skills.clawhub_loader import load_all_tool_schemas
            skill_schemas = load_all_tool_schemas(
                enabled_slugs=enabled_clawhub_slugs,
                include_bundled=clawhub_include_bundled,
                include_user=clawhub_include_user,
                auth_user_id=auth_user_id,
            )
            for ss in skill_schemas:
                if ss["name"] in seen_names:
                    logger.warning(f"Skill tool name collision: {ss['name']}")
                    continue
                tools.append(ss)
                seen_names.add(ss["name"])
        except Exception as e:
            logger.warning(f"Failed to load ClawHub skills: {e}")

    # 4) Outils OpenClaw directs (38) — opt-in via prefs user.
    # Le LLM peut invoquer browser/exec/fs.read/image_generate/... directement,
    # le dispatcher route vers openclaw_invoke_tool(name, action, args, session_key).
    if include_openclaw_direct_tools:
        try:
            from api.openclaw_tool_schemas import build_openclaw_tool_schemas
            oc_schemas = build_openclaw_tool_schemas(enabled_tools=enabled_openclaw_tools)
            for oc in oc_schemas:
                if oc["name"] in seen_names:
                    logger.warning(f"OpenClaw tool name collision: {oc['name']}")
                    continue
                tools.append(oc)
                seen_names.add(oc["name"])
        except Exception as e:
            logger.warning(f"Failed to load OpenClaw direct tool schemas: {e}")

    return tools


def tool_name_to_action_type(tool_name: str) -> str:
    """Convertit un tool_name (snake_case) en action_type (UPPER_SNAKE)."""
    return tool_name.upper()


# ══════════════════════════════════════════════════════════════════════════════
# Smart model routing — reduit les couts en choisissant Haiku pour les taches
# simples (lecture, recherche, classification) et Sonnet pour le raisonnement
# complexe (dilemmes, plans multi-etapes, generation de code).
# ══════════════════════════════════════════════════════════════════════════════

# Tarifs Anthropic (USD par million de tokens, maj avril 2026).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    # Fallback par defaut : Sonnet 4.5 pricing
}

# Mots-cles qui SIGNALENT un besoin de raisonnement profond (=> Sonnet).
# Sonnet 4.6 est aussi BIEN MEILLEUR pour selectionner les bons tools (python_exec
# vs exec, semantic_search vs memory_search, etc.) — donc on route vers lui des
# qu'il y a un calcul, du Python, des stats, ou du tool_use complexe a faire.
_COMPLEX_KEYWORDS = (
    "dilemm", "analyse", "analys", "raisonn", "plan ", "planifi",
    "strateg", "decision", "decid", "compar", "evalu", "reflechis",
    "pourquoi", "explique pourquoi", "code", "programme", "script",
    "algorithm", "pseudocode", "refactor", "architecture", "conception",
    "debug", "resoud", "demonstre", "prouve", "theoreme",
    # Phase 14 : tout ce qui implique Python/calcul/stats -> Sonnet
    "calcul", "calcule", "calculer", "compute",
    "python", "pandas", "numpy", "scipy", "matplotlib",
    "mediane", "moyenne", "ecart", "variance", "histogramme",
    "graphique", "courbe", "plot", "chart",
    "interet", "intérêt", "compose", "investis", "rendement",
    "simulation", "monte-carlo", "regression", "correlation",
    "tri", "sort", "filtre", "aggregat",
)

# Tool simples qui peuvent tourner sur Haiku sans perte de qualite notable.
_HAIKU_FRIENDLY_TOOLS = frozenset({
    "SEARCH", "WEB_FETCH", "FILE_READ", "MEMORY_SEARCH",
    "CALENDAR_LIST", "GMAIL_READ", "TODO_WRITE",
})


def pick_model_for_request(
    user_message: str,
    *,
    has_long_history: bool = False,
    thinking_enabled: bool = False,
    force_model: str | None = None,
) -> str:
    """Choisit le modele le moins cher capable de traiter la requete.

    Regles :
      - force_model != None -> retourne tel quel (override utilisateur).
      - thinking_enabled -> Sonnet (Haiku n'a pas extended thinking).
      - historique long (> N messages) -> Sonnet (contexte a tenir).
      - keyword complexe (dilemme/analyse/code/...) -> Sonnet.
      - message court sans keyword complexe -> Haiku 4.5.
      - defaut -> Haiku 4.5 (66% moins cher).

    Returns: model id Anthropic.
    """
    if force_model:
        return force_model

    sonnet = "claude-sonnet-4-6"
    haiku = "claude-haiku-4-5-20251001"

    if thinking_enabled:
        return sonnet
    if has_long_history:
        return sonnet

    msg_low = (user_message or "").lower()
    # Message long -> probablement complexe
    if len(msg_low) > 500:
        return sonnet
    # Keywords complexes
    if any(kw in msg_low for kw in _COMPLEX_KEYWORDS):
        return sonnet
    # Par defaut : Haiku (moins cher, rapide, suffit pour la majorite des tours)
    return haiku


def pricing_for_model(model: str) -> tuple[float, float]:
    """Retourne (input_usd_per_mtok, output_usd_per_mtok) pour un modele."""
    return MODEL_PRICING.get(model, (3.0, 15.0))


# ══════════════════════════════════════════════════════════════════════════════
# 2. Protocol pour l'executeur d'actions
# ══════════════════════════════════════════════════════════════════════════════


class ActionExecutor(Protocol):
    """Interface que doit implementer tout executeur d'actions.

    L'AgenticLoop appelle `execute(action_type, action_input)` pour chaque
    tool_use recu du LLM, et attend un dict resultat.

    Le resultat doit contenir :
      - `content`: str (ce que le LLM verra comme tool_result)
      - `is_error`: bool (True si l'action a echoue)
      - `raw`: Any (donnees arbitraires pour le frontend, pas vues par le LLM)
    """

    async def execute(self, action_type: str, action_input: dict) -> dict:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# 3. Compaction automatique du contexte
# ══════════════════════════════════════════════════════════════════════════════


def compact_messages(
    messages: list[dict[str, Any]],
    keep_last_n: int = 4,
    max_tool_result_chars: int = 300,
) -> tuple[list[dict[str, Any]], int]:
    """Compresse les anciens tool_results volumineux pour reduire les tokens.

    Strategie sans casser la validite Anthropic :
      - Garde intactes les `keep_last_n` derniers messages de l'historique.
      - Pour les messages plus anciens, tronque le `content` de chaque bloc
        `tool_result` a `max_tool_result_chars` caracteres avec un marqueur
        "[...tronque par compaction...]".
      - Ne touche JAMAIS aux blocs `tool_use` (IDs et inputs preserves pour
        l'appairage tool_use ↔ tool_result).
      - Ne touche pas au texte assistant/user (souvent peu volumineux).

    Returns:
      (nouveaux_messages, chars_economises)
    """
    if len(messages) <= keep_last_n:
        return messages, 0

    cutoff = len(messages) - keep_last_n
    new_messages: list[dict[str, Any]] = []
    chars_saved = 0
    marker = "\n\n[...tronque par compaction...]"

    for idx, msg in enumerate(messages):
        if idx >= cutoff:
            new_messages.append(msg)
            continue

        content = msg.get("content")
        # content peut etre str (user messages simples) ou list (tool results, etc.)
        if isinstance(content, list):
            new_content: list[dict[str, Any]] = []
            for block in content:
                if (isinstance(block, dict)
                        and block.get("type") == "tool_result"):
                    raw_c = block.get("content", "")
                    if isinstance(raw_c, str) and len(raw_c) > max_tool_result_chars:
                        truncated = raw_c[:max_tool_result_chars] + marker
                        chars_saved += len(raw_c) - len(truncated)
                        new_block = dict(block)
                        new_block["content"] = truncated
                        new_content.append(new_block)
                    else:
                        new_content.append(block)
                else:
                    new_content.append(block)
            new_messages.append({"role": msg["role"], "content": new_content})
        else:
            new_messages.append(msg)

    return new_messages, chars_saved


# ══════════════════════════════════════════════════════════════════════════════
# 4. Boucle agentique
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class LoopEvent:
    """Event emis pendant la boucle agentique (pour SSE)."""
    type: str  # "turn_start" | "tool_use" | "tool_result" | "thinking" | "done" | "error"
                # | "auto_extension_start" | "auto_extension_found"
                # | "auto_extension_ready" | "auto_extension_error"
                # | "action_done" (feedback visuel apres action destructive reussie)
    data: dict[str, Any] = field(default_factory=dict)


def _build_openclaw_card_payload(
    action_type: str,
    action_card: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any] | None:
    """Convertit une `action_card` de shape_openclaw_result en payload
    uniforme pour le SSE event `action_done`.

    La card vient du shaper (kind/url/screenshot_url/count/...). On la projette
    sur le schema du frontend : {action_type, title, subtitle, download_url,
    external_url, method}.
    """
    kind = str(action_card.get("kind", ""))

    # Navigation / browser : URL + screenshot
    if kind == "browser":
        url = str(action_card.get("url") or "")
        screenshot = str(action_card.get("screenshot_url") or "")
        return {
            "action_type": action_type,
            "title": f"Navigateur : {url}" if url else "Navigateur",
            "subtitle": "Capture disponible" if screenshot else None,
            "external_url": url or None,
            "download_url": screenshot or None,
        }

    # Web fetch : URL + status
    if kind == "web_fetch":
        url = str(action_card.get("url") or "")
        status = action_card.get("status")
        size = action_card.get("size")
        subtitle = f"{status} — {size} octets" if status and size else (f"{status}" if status else None)
        return {
            "action_type": action_type,
            "title": f"Page consultee : {url}" if url else "Page consultee",
            "subtitle": subtitle,
            "external_url": url or None,
        }

    # Generation image
    if kind == "image_generate":
        url = str(action_card.get("image_url") or "")
        cost = action_card.get("cost_usd")
        return {
            "action_type": action_type,
            "title": "Image generee",
            "subtitle": f"Cout ~${cost}" if cost else None,
            "download_url": url or None,
            "external_url": url or None,
        }

    # Generation media (musique, video, voix)
    if kind in {"music_generate", "video_generate", "voice_generate"}:
        url = str(action_card.get("media_url") or "")
        duration = action_card.get("duration_s")
        cost = action_card.get("cost_usd")
        labels = {
            "music_generate": "Musique generee",
            "video_generate": "Video generee",
            "voice_generate": "Voix synthetisee",
        }
        sub_parts = []
        if duration:
            sub_parts.append(f"{duration}s")
        if cost:
            sub_parts.append(f"~${cost}")
        return {
            "action_type": action_type,
            "title": labels.get(kind, "Media genere"),
            "subtitle": " | ".join(sub_parts) or None,
            "download_url": url or None,
            "external_url": url or None,
        }

    # Exec / bash / process
    if kind == "exec":
        cmd = str(action_card.get("command") or "")
        code = action_card.get("exit_code")
        has_stderr = action_card.get("has_stderr")
        subtitle_parts = []
        if code is not None:
            subtitle_parts.append(f"exit {code}")
        if has_stderr:
            subtitle_parts.append("stderr !=  vide")
        return {
            "action_type": action_type,
            "title": f"Commande : {cmd[:80]}" if cmd else "Commande executee",
            "subtitle": " | ".join(subtitle_parts) or None,
        }

    # Filesystem read/write
    if kind in {"fs_read", "fs_write"}:
        path = str(action_card.get("path") or "")
        size = action_card.get("size") or action_card.get("bytes")
        return {
            "action_type": action_type,
            "title": f"{'Lecture' if kind == 'fs_read' else 'Ecriture'} : {path}" if path else "Fichier",
            "subtitle": f"{size} octets" if size else None,
        }

    # Messagerie multi-canal
    if kind == "message_sent":
        channel = str(action_card.get("channel") or "")
        recipient = str(action_card.get("recipient") or "")
        ok = action_card.get("ok", True)
        title = f"Message {channel} envoye" if channel else "Message envoye"
        return {
            "action_type": action_type,
            "title": title,
            "subtitle": recipient or None,
            "method": channel or None,
        } if ok else None

    # Sessions OpenClaw
    if kind == "sessions_spawn":
        sid = str(action_card.get("session_id") or "")
        return {
            "action_type": action_type,
            "title": f"Sous-agent lance : {sid}" if sid else "Sous-agent lance",
            "subtitle": str(action_card.get("status") or "") or None,
        }

    # Recherche web (generique)
    if kind == "search_results":
        count = action_card.get("count", 0)
        first_url = str(action_card.get("first_url") or "")
        tool = action_card.get("tool", action_type)
        return {
            "action_type": action_type,
            "title": f"Recherche {tool} : {count} resultats",
            "subtitle": first_url[:120] or None,
            "external_url": first_url or None,
        }

    # Moderation / safety
    if kind == "moderation":
        flagged = action_card.get("flagged", False)
        return {
            "action_type": action_type,
            "title": "Moderation : FLAGGED" if flagged else "Moderation : OK",
            "subtitle": None,
        }
    if kind == "url_safety":
        safe = action_card.get("safe", True)
        return {
            "action_type": action_type,
            "title": "URL safe" if safe else "URL DANGEREUSE",
            "subtitle": None,
        }

    # Fallback : pas d'action_done cote UI pour ce tool
    return None


def _build_action_done_payload(
    action_type: str,
    action_input: dict[str, Any],
    exec_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Construit le payload de l'event `action_done` pour une action destructive.

    Retourne None si l'action a echoue ou si le type n'est pas affichable dans
    une card utilisateur (ex: SEARCH, FILE_READ, etc.). Le frontend utilise
    ce payload pour afficher une card cliquable dans le chat.

    Keys du payload :
      - `action_type` : EMAIL | FILE_CREATE | CALENDAR_EVENT | DRIVE_SAVE | CRON | GMAIL_SEND | COMPUTER_USE
      - `title` : ligne principale (ex: "Email envoye a alice@example.com")
      - `subtitle` : complement (objet, chemin, lien)
      - `download_url` : optionnel, si fichier telechargeable
      - `external_url` : optionnel, lien externe (Google Calendar, Drive, etc.)
    """
    if exec_result.get("is_error"):
        return None
    raw = exec_result.get("raw") or {}
    if not isinstance(raw, dict):
        raw = {}

    # Tools OpenClaw directs : l'action_card est deja shape'e dans raw.action_card.
    # On la convertit en payload uniforme pour le frontend.
    action_card = raw.get("action_card") if isinstance(raw, dict) else None
    if action_card and isinstance(action_card, dict):
        return _build_openclaw_card_payload(action_type, action_card, raw)

    if action_type in {"EMAIL", "GMAIL_SEND"}:
        to = str(action_input.get("to") or raw.get("to") or "")
        subject = str(action_input.get("subject") or "")
        method = str(raw.get("method") or "")
        return {
            "action_type": action_type,
            "title": f"Email envoye a {to}" if to else "Email envoye",
            "subtitle": subject[:120] or None,
            "method": method,
        }
    if action_type == "FILE_CREATE":
        filename = str(raw.get("workspace_path") or raw.get("stored_filename") or action_input.get("filename") or "")
        dl = raw.get("download_url")
        if not dl and raw.get("workspace_path"):
            fname = str(raw.get("workspace_path")).rsplit("/", 1)[-1]
            dl = f"/api/agent3/workspace-files/{fname}"
        size = raw.get("size")
        return {
            "action_type": action_type,
            "title": f"Fichier {filename} cree" if filename else "Fichier cree",
            "subtitle": f"{size} octets" if isinstance(size, int) else None,
            "download_url": dl,
        }
    if action_type == "CALENDAR_EVENT":
        title = str(action_input.get("title") or "")
        start = str(action_input.get("start") or "")
        link = raw.get("event_link")
        return {
            "action_type": action_type,
            "title": f"Evenement '{title}' cree" if title else "Evenement cree",
            "subtitle": start[:16] or None,
            "external_url": link,
        }
    if action_type == "DRIVE_SAVE":
        filename = str(raw.get("filename") or action_input.get("filename") or "")
        file_id = raw.get("file_id")
        external = f"https://drive.google.com/file/d/{file_id}/view" if file_id else None
        return {
            "action_type": action_type,
            "title": f"{filename} sauvegarde sur Drive" if filename else "Fichier sauvegarde sur Drive",
            "external_url": external,
        }
    if action_type == "CRON":
        label = str(raw.get("label") or action_input.get("label") or "")
        cron_expr = str(raw.get("cron_expr") or action_input.get("cron_expr") or "")
        return {
            "action_type": action_type,
            "title": f"Tache programmee : {label}" if label else "Tache programmee",
            "subtitle": cron_expr or None,
        }
    if action_type == "COMPUTER_USE":
        steps = raw.get("steps") or 0
        cost = raw.get("cost_usd")
        cost_str = f" ({cost} $)" if isinstance(cost, (int, float)) and cost > 0 else ""
        return {
            "action_type": action_type,
            "title": f"Computer Use termine en {steps} etape(s){cost_str}",
            "subtitle": str(raw.get("last_action") or "")[:80] or None,
        }
    return None


@dataclass
class LoopResult:
    """Resultat final d'une boucle agentique."""
    final_text: str
    turns: int
    actions_executed: list[dict[str, Any]]
    stop_reason: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error: str | None = None


class AgenticLoop:
    """Boucle LLM <-> Tools a la Claude Code.

    Usage :
        loop = AgenticLoop(
            client=anthropic.AsyncAnthropic(...),
            system_prompt="...",
            tools=build_tool_schemas(),
            executor=my_executor,
            max_turns=15,
        )
        async for event in loop.run(user_message="...", history=[]):
            # forward en SSE
            ...
        final = loop.result
    """

    # Claude 4.5 family. Sonnet pour la qualite de raisonnement, Haiku pour
    # les petites taches. La facturation agentique peut etre elevee — on cap
    # a max_turns pour limiter l'explosion de cout.
    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_MAX_TURNS = 15

    # Actions qui modifient l'etat externe (envoi, ecriture, programmation) et
    # necessitent une confirmation explicite de l'utilisateur avant execution.
    # En mode "bypass" (voir permission_mode), ce gate est desactive et toutes
    # les actions s'executent automatiquement.
    DESTRUCTIVE_ACTIONS: set[str] = {
        "EMAIL", "GMAIL_SEND",
        "CALENDAR_EVENT",
        "FILE_CREATE",
        "DRIVE_SAVE",
        "CRON",
        "COMPUTER_USE",
        # Phase 4 : meta-tools ClawHub destructifs
        # CLAWHUB_INSTALL : telecharge du code tiers depuis le registre
        # CLAWHUB_PUBLISH : publie un skill genere par le LLM (effet externe visible)
        # CLAWHUB_SEARCH reste non-destructif (read-only).
        "CLAWHUB_INSTALL",
        "CLAWHUB_PUBLISH",
        # Phase 5 : outils OpenClaw directs destructifs (noms UPPER).
        # Source canonique : api.openclaw_tool_schemas.DESTRUCTIVE_OPENCLAW_TOOLS
        # (mappage lowercase -> UPPER ici pour matcher tool_name_to_action_type).
        "EXEC", "BASH", "PROCESS",
        "FS_WRITE", "FS_EDIT", "FS_APPLY_PATCH",
        "BROWSER",
        "MESSAGE",
        "IMAGE_GENERATE", "MUSIC_GENERATE", "VIDEO_GENERATE",
        "OC_CRON", "GATEWAY",
        "SESSIONS_SPAWN",
    }

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        system_prompt: str,
        tools: list[dict[str, Any]],
        executor: ActionExecutor,
        model: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        pre_approved_tool_ids: set[str] | None = None,
        auto_compact_threshold: int = 120_000,
        tool_timeout_s: float = 120.0,
        max_llm_retries: int = 3,
        retry_backoff_base_s: float = 1.5,
        stream: bool = False,
        thinking_enabled: bool = False,
        thinking_budget_tokens: int = 4000,
        cancel_event: Any = None,  # asyncio.Event | None
        hook_registry: Any = None,  # api.agent3_hooks.HookRegistry | None
        hook_user_id: str = "",
        hook_user_msg: str = "",
        hook_session_key: str = "",
        cache_tools: bool = True,
        interleaved_thinking: bool = False,
        cost_hard_cap_usd: float | None = None,
        input_usd_per_mtok: float = 3.0,     # Sonnet 4.5 pricing (avril 2026)
        output_usd_per_mtok: float = 15.0,
        event_logger: Any = None,  # Callable[[dict], None] | None — persist loop events
        permission_mode: str = "default",    # "default" (confirmation) | "bypass" (auto)
        tools_rebuild_fn: Any = None,  # Callable[[], list[dict]] | None — regenere self.tools
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools
        self.executor = executor
        self.model = model or self.DEFAULT_MODEL
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        # IDs de tool_use deja approuves par l'utilisateur (pour le resume apres
        # confirmation). Vide au premier appel ; rempli dans les reprises.
        self.pre_approved_tool_ids: set[str] = set(pre_approved_tool_ids or [])
        self.result: LoopResult | None = None
        # Etat de confirmation en attente (pour que le router puisse stocker la
        # session et la reprendre apres validation).
        self.pending_confirmation: dict[str, Any] | None = None
        # Seuil de tokens d'entree cumules au-dessus duquel la boucle compresse
        # les anciens tool_results volumineux pour eviter de saturer la fenetre
        # de contexte du modele (200k chez Claude Sonnet). 120k laisse ~80k de
        # marge pour la suite de la conversation.
        self.auto_compact_threshold = auto_compact_threshold
        self._compacted_once: bool = False
        # Plafond de temps pour un tool_use : au-dela, on injecte une erreur
        # artificielle ("tool timeout") pour que le LLM puisse pivoter sans
        # bloquer toute la boucle.
        self.tool_timeout_s = tool_timeout_s
        # Retry avec backoff exponentiel sur erreurs LLM transitoires (429, 500,
        # network). Evite d'abandonner la boucle sur un simple rate-limit.
        self.max_llm_retries = max_llm_retries
        self.retry_backoff_base_s = retry_backoff_base_s
        # Streaming : si True, la boucle emet des events `token_delta` (texte
        # partiel) et `thinking_delta` (raisonnement partiel) au fur et a mesure
        # que le LLM genere, au lieu d'attendre la reponse complete. L'UX s'en
        # trouve radicalement transformee (feedback immediat).
        self.stream = stream
        # Extended thinking : si True, le modele raisonne ~`thinking_budget_tokens`
        # tokens avant de repondre (blocs `thinking` serializes). Ideal pour les
        # dilemmes de vie ou la qualite du raisonnement compte plus que la
        # vitesse. Requis pour preserver les blocs thinking dans l'historique
        # assistant pour maintenir la continuite.
        self.thinking_enabled = thinking_enabled
        self.thinking_budget_tokens = thinking_budget_tokens
        # Interrupt : un asyncio.Event que l'appelant peut set() pour demander
        # l'arret immediat de la boucle. Verifie entre chaque tour et apres
        # chaque event de streaming.
        self.cancel_event = cancel_event
        # Hooks pre/post tool_use. Si fourni, chaque tool_use passe par
        # run_pre (peut MODIFY input ou BLOCK) et run_post (audit, enrichissement).
        self.hook_registry = hook_registry
        self.hook_user_id = hook_user_id
        self.hook_user_msg = hook_user_msg
        self.hook_session_key = hook_session_key
        # Cache prompt tools : ajoute cache_control: ephemeral sur la liste d'outils
        # pour eviter de les re-tokeniser a chaque tour. Gain : -30 a -50% sur
        # les sessions longues.
        self.cache_tools = cache_tools
        # Interleaved thinking : permet au modele de re-raisonner ENTRE les
        # tool_use au sein d'un meme tour. Necessite le beta header.
        self.interleaved_thinking = interleaved_thinking
        # Budget hard-cap : arret immediat de la boucle si le cout cumule
        # depasse ce seuil. Protege contre les runs cher qui tournent en
        # rond.
        self.cost_hard_cap_usd = cost_hard_cap_usd
        self.input_usd_per_mtok = input_usd_per_mtok
        self.output_usd_per_mtok = output_usd_per_mtok
        # Logger optionnel : callable invoque pour chaque LoopEvent emis.
        # Permet de persister les logs d'execution en DB pour replay / audit.
        self.event_logger = event_logger
        # Mode de permission pour actions destructives (Phase 4 Part D) :
        #  - "default" : gate de confirmation user pour tout DESTRUCTIVE_ACTIONS
        #  - "bypass"  : execute automatiquement tout (utile pour runs autonomes /
        #    CI / crons pre-approuves par l'utilisateur). A utiliser avec prudence.
        self.permission_mode = permission_mode if permission_mode in ("default", "bypass") else "default"
        # Callable pour regenerer la liste de tools (apres auto-extension ClawHub).
        # Typiquement : lambda: build_tool_schemas(enabled_actions=..., include_clawhub_skills=True, ...)
        # Appele apres un CLAWHUB_INSTALL reussi pour que `skill_<slug>` soit
        # immediatement visible au prochain tour sans redemarrer la session.
        self.tools_rebuild_fn = tools_rebuild_fn
        # Phase 14C : tool_choice forcing pour le PREMIER tour uniquement.
        # Permet de forcer l'usage d'un tool specifique au demarrage (ex: math
        # question -> force python_exec). Apres le tour 1, on revient au mode
        # "auto" pour laisser le LLM finir naturellement (synthese, format, etc.).
        # Format Anthropic : {"type": "tool", "name": "python_exec"} ou
        # {"type": "any"} (force un tool sans en specifier un) ou
        # {"type": "auto"} (defaut, choix libre).
        self.force_tool_choice_first_turn: dict[str, Any] | None = None
        self._current_turn: int = 0

    def _refresh_tools_after_install(self) -> dict[str, Any]:
        """Regenere self.tools apres un CLAWHUB_INSTALL pour que le skill
        fraichement installe soit immediatement visible au tour suivant.

        Strategie :
          1. Invalidate le cache du loader (mtime-based cache des SKILL.md)
          2. Si tools_rebuild_fn fourni, appelle la closure pour avoir la
             nouvelle liste (qui inclut skill_<slug> nouvellement installe)
          3. Calcule le diff (nouveaux slugs) pour le log / event

        Retourne un dict { "added": [slugs], "total_before": N, "total_after": M, "ok": bool }.
        Best-effort : swallow les erreurs pour ne jamais casser la boucle.
        """
        info: dict[str, Any] = {"added": [], "total_before": len(self.tools or []), "total_after": 0, "ok": False}
        try:
            # 1) Invalider le cache du loader
            try:
                from api.agent3_skills.clawhub_loader import invalidate_cache
                invalidate_cache()
            except Exception as e:
                logger.debug(f"Cache invalidation lookup failed: {e}")

            # 2) Rebuild tools si closure fournie
            if callable(self.tools_rebuild_fn):
                before_names = {t.get("name") for t in (self.tools or []) if isinstance(t, dict)}
                new_tools = self.tools_rebuild_fn() or []
                if isinstance(new_tools, list) and new_tools:
                    after_names = {t.get("name") for t in new_tools if isinstance(t, dict)}
                    added = sorted(after_names - before_names)
                    # Extraire les slugs (tool names skill_<slug> -> slug)
                    added_slugs = [n[len("skill_"):].replace("_", "-") for n in added if n and n.startswith("skill_")]
                    self.tools = new_tools
                    info["added"] = added_slugs
                    info["total_after"] = len(new_tools)
                    info["ok"] = True
                else:
                    logger.debug("tools_rebuild_fn returned empty list; keeping current tools")
                    info["total_after"] = info["total_before"]
            else:
                # Pas de closure : on garde la liste actuelle mais le cache est
                # deja invalide, donc le prochain load_all_skills verra le nouveau.
                info["total_after"] = info["total_before"]
        except Exception as e:
            logger.warning(f"_refresh_tools_after_install failed: {e}")
        return info

    def _build_create_kwargs(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Construit les kwargs communs pour messages.create / messages.stream.

        Optimisations de coût/qualité :
          - cache_control ephemeral sur system_prompt (toujours)
          - cache_control ephemeral sur le dernier tool (caching de TOUTE la liste)
          - extra_headers: anthropic-beta pour interleaved-thinking si active
        """
        # Cache prompt tools : on met cache_control sur le DERNIER tool de la
        # liste. Anthropic met automatiquement en cache tout ce qui est AVANT
        # ce marqueur dans la sequence system + tools. Donc un seul marker
        # couvre la liste entiere.
        tools_list = self.tools
        if self.cache_tools and tools_list:
            # Shallow-copy pour ne pas muter l'objet partage (plusieurs AgenticLoop
            # peuvent reutiliser le meme self.tools).
            tools_list = [dict(t) for t in tools_list]
            tools_list[-1] = {**tools_list[-1], "cache_control": {"type": "ephemeral"}}

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": messages,
            "tools": tools_list,
        }
        # Phase 14C : tool_choice forcing pour le 1er tour uniquement.
        # Si le router a detecte une question math, il aura set
        # force_tool_choice_first_turn = {"type": "tool", "name": "python_exec"}.
        # On l'applique au tour 1 puis on revient en mode auto pour ne pas
        # bloquer la synthese finale (qui n'a pas besoin d'outil).
        # NB : Anthropic exige que le tool reference existe dans `tools`.
        if self.force_tool_choice_first_turn and self._current_turn <= 1:
            forced = self.force_tool_choice_first_turn
            tool_name = forced.get("name") if isinstance(forced, dict) else None
            tool_exists = (
                tool_name is None
                or any(t.get("name") == tool_name for t in tools_list)
            )
            if tool_exists:
                kwargs["tool_choice"] = forced
        if self.thinking_enabled:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget_tokens,
            }
        # Interleaved thinking beta : permet des blocs `thinking` entre
        # plusieurs tool_use du meme tour, et entre tool_result et suite
        # de la generation. Qualite accrue sur les dilemmes multi-etapes.
        if self.thinking_enabled and self.interleaved_thinking:
            kwargs["extra_headers"] = {
                "anthropic-beta": "interleaved-thinking-2025-05-14",
            }
        return kwargs

    def _estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Coût estimé en USD pour (input, output) tokens. Base : tarifs Sonnet 4.5."""
        return (
            input_tokens * self.input_usd_per_mtok / 1_000_000.0
            + output_tokens * self.output_usd_per_mtok / 1_000_000.0
        )

    def _is_cost_exceeded(self, input_tokens: int, output_tokens: int) -> bool:
        """True si le cout cumule depasse le hard-cap (si defini)."""
        if self.cost_hard_cap_usd is None:
            return False
        return self._estimate_cost_usd(input_tokens, output_tokens) >= self.cost_hard_cap_usd

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Forward vers event_logger si configure (best-effort, swallow errors)."""
        if self.event_logger is None:
            return
        try:
            self.event_logger({"type": event_type, "data": data})
        except Exception as e:
            logger.debug(f"event_logger failed: {e}")

    async def _call_llm_with_retry(
        self,
        messages: list[dict[str, Any]],
        turn: int,
    ) -> Any:
        """Appelle messages.create avec retry exponentiel sur erreurs transitoires.

        Retry sur :
          - RateLimitError (HTTP 429)
          - APIError avec status 5xx
          - Timeout, connection errors (via classname heuristique)
        Propage immediatement les autres erreurs (authentication, bad request…).
        """
        import random
        last_exc: Exception | None = None
        for attempt in range(self.max_llm_retries + 1):
            try:
                return await self.client.messages.create(**self._build_create_kwargs(messages))
            except Exception as e:
                last_exc = e
                # Determine si l'erreur est transitoire
                cls_name = type(e).__name__.lower()
                status = getattr(e, "status_code", None) or getattr(e, "status", None)
                is_rate_limit = ("ratelimit" in cls_name) or status == 429
                is_server_err = isinstance(status, int) and 500 <= status < 600
                is_network = any(tok in cls_name for tok in (
                    "timeout", "connection", "network", "apiconnection",
                ))
                transient = is_rate_limit or is_server_err or is_network

                if not transient or attempt >= self.max_llm_retries:
                    raise

                # Backoff exponentiel avec jitter
                delay = self.retry_backoff_base_s * (2 ** attempt)
                delay += random.uniform(0, 0.5)
                logger.warning(
                    f"LLM transient error at turn {turn} attempt {attempt + 1}: "
                    f"{type(e).__name__} — retry in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
        # Inatteignable mais rassurer le type checker
        raise last_exc  # type: ignore[misc]

    def _is_cancelled(self) -> bool:
        """Retourne True si l'appelant a demande l'arret de la boucle."""
        return bool(self.cancel_event is not None and self.cancel_event.is_set())

    async def _stream_llm_turn(
        self,
        messages: list[dict[str, Any]],
        turns: int,
    ) -> AsyncIterator[LoopEvent]:
        """Streame un tour LLM : yield `token_delta` pour chaque morceau de
        texte, `thinking_delta` pour chaque morceau de raisonnement. A la fin
        du stream, stocke le Message final dans `self._last_stream_response`
        (a consommer par run()).
        """
        self._last_stream_response = None
        try:
            stream_cm = self.client.messages.stream(**self._build_create_kwargs(messages))
        except Exception as e:
            # Propagation propre : run() le transformera en event 'error'.
            raise
        async with stream_cm as stream:
            async for event in stream:
                if self._is_cancelled():
                    yield LoopEvent("cancelled", {"turn": turns, "phase": "stream"})
                    return
                etype = getattr(event, "type", None)
                if etype != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None) if delta is not None else None
                if dtype == "text_delta":
                    txt = getattr(delta, "text", "") or ""
                    if txt:
                        yield LoopEvent("token_delta", {"turn": turns, "text": txt})
                elif dtype == "thinking_delta":
                    tk = getattr(delta, "thinking", "") or ""
                    if tk:
                        yield LoopEvent("thinking_delta", {"turn": turns, "text": tk})
                elif dtype == "input_json_delta":
                    # Stream partiel des inputs de tool_use : l'UI peut afficher
                    # les parametres JSON se construire en live (meilleur UX,
                    # aucun impact cout). Le message final contient toujours
                    # l'input assemble valide.
                    partial = getattr(delta, "partial_json", "") or ""
                    idx = getattr(event, "index", None)
                    if partial:
                        yield LoopEvent("tool_input_delta", {
                            "turn": turns,
                            "block_index": idx,
                            "partial_json": partial,
                        })
            self._last_stream_response = await stream.get_final_message()

    async def _run_pre_hooks(
        self,
        action_type: str,
        action_input: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Applique la chaine pre-hook. Retourne (input_final, block_info_or_None).

        Si block_info est non None, la tool call doit etre court-circuitee avec
        un tool_result is_error=True dont le contenu est block_info["content"].
        """
        if self.hook_registry is None:
            return action_input, None
        try:
            pre_result = await self.hook_registry.run_pre(
                action_type=action_type,
                action_data=action_input,
                user_id=self.hook_user_id,
                user_msg=self.hook_user_msg,
                session_key=self.hook_session_key,
            )
        except Exception as e:
            logger.warning(f"Pre-hook chain failed for {action_type}: {e}")
            return action_input, None
        if pre_result is None:
            return action_input, None
        if getattr(pre_result, "blocked", False):
            reason = getattr(pre_result, "block_reason", "") or "politique interne"
            return action_input, {
                "content": f"Action bloquee par un hook : {reason}",
                "is_error": True,
                "raw": {
                    "hook_block": True,
                    "hook_name": getattr(pre_result, "hook_name", ""),
                },
                "_hook_name": getattr(pre_result, "hook_name", ""),
                "_reason": reason,
            }
        if getattr(pre_result, "modified", False) and getattr(pre_result, "modified_data", None):
            return pre_result.modified_data, None
        return action_input, None

    async def _run_post_hooks(
        self,
        action_type: str,
        action_input: dict[str, Any],
        exec_result: dict[str, Any],
    ) -> None:
        """Applique la chaine post-hook. N'altere pas exec_result (log/audit only)."""
        if self.hook_registry is None:
            return
        try:
            await self.hook_registry.run_post(
                action_type=action_type,
                action_data=action_input,
                execution_result=exec_result,
                user_id=self.hook_user_id,
                user_msg=self.hook_user_msg,
                session_key=self.hook_session_key,
            )
        except Exception as e:
            logger.warning(f"Post-hook chain failed for {action_type}: {e}")

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LoopEvent]:
        """Execute la boucle agentique. Yield des LoopEvent au fur et a mesure.

        history: liste de messages {role, content} au format Anthropic.
                 Sera completee avec user_message puis les echanges de la boucle.
        """
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": user_message})

        turns = 0
        actions_executed: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        final_text = ""
        stop_reason = "unknown"
        error_msg: str | None = None

        try:
            while turns < self.max_turns:
                if self._is_cancelled():
                    stop_reason = "cancelled"
                    yield LoopEvent("cancelled", {"turn": turns, "phase": "between_turns"})
                    break
                turns += 1
                self._current_turn = turns
                yield LoopEvent("turn_start", {"turn": turns})

                # Auto-compaction : si on approche du plafond de tokens du
                # modele, on compresse les anciens tool_results volumineux.
                # On ne le fait qu'une fois par run pour eviter de boucler.
                if (not self._compacted_once
                        and total_input >= self.auto_compact_threshold
                        and len(messages) > 6):
                    messages, chars_saved = compact_messages(
                        messages, keep_last_n=4, max_tool_result_chars=300,
                    )
                    self._compacted_once = True
                    yield LoopEvent("context_compacted", {
                        "turn": turns,
                        "chars_saved": chars_saved,
                        "threshold_tokens": self.auto_compact_threshold,
                        "total_input_tokens_at_trigger": total_input,
                    })

                t0 = time.perf_counter()
                cancelled_mid_stream = False
                try:
                    if self.stream:
                        async for sev in self._stream_llm_turn(messages, turns):
                            if sev.type == "cancelled":
                                cancelled_mid_stream = True
                            yield sev
                        response = self._last_stream_response
                        if cancelled_mid_stream or response is None:
                            stop_reason = "cancelled"
                            break
                    else:
                        response = await self._call_llm_with_retry(messages, turns)
                except Exception as e:
                    error_msg = f"LLM call failed at turn {turns}: {e}"
                    logger.exception(error_msg)
                    yield LoopEvent("error", {"message": error_msg, "turn": turns})
                    break

                dt = time.perf_counter() - t0
                total_input += getattr(response.usage, "input_tokens", 0)
                total_output += getattr(response.usage, "output_tokens", 0)
                stop_reason = response.stop_reason or "unknown"

                # Cache stats (Anthropic prompt caching). Permet de mesurer
                # concretement l'efficacite du cache_control: ephemeral.
                _cache_create = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                _cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
                turn_done_data = {
                    "turn": turns,
                    "stop_reason": stop_reason,
                    "latency_ms": int(dt * 1000),
                    "input_tokens": getattr(response.usage, "input_tokens", 0),
                    "output_tokens": getattr(response.usage, "output_tokens", 0),
                    "cache_creation_input_tokens": _cache_create,
                    "cache_read_input_tokens": _cache_read,
                    "cum_cost_usd": round(self._estimate_cost_usd(total_input, total_output), 4),
                }
                yield LoopEvent("turn_llm_done", turn_done_data)
                self._log_event("turn_llm_done", turn_done_data)

                # Hard cap de cout : si le cumule depasse le seuil, on arrete
                # immediatement. Emet un event explicite pour l'UI.
                if self._is_cost_exceeded(total_input, total_output):
                    cost = self._estimate_cost_usd(total_input, total_output)
                    cap_data = {
                        "turn": turns,
                        "cost_usd": round(cost, 4),
                        "cap_usd": self.cost_hard_cap_usd,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                    }
                    yield LoopEvent("cost_exceeded", cap_data)
                    self._log_event("cost_exceeded", cap_data)
                    stop_reason = "cost_exceeded"
                    error_msg = (
                        f"Budget cost hard-cap atteint: ${cost:.4f} >= "
                        f"${self.cost_hard_cap_usd:.4f}. Boucle arretee."
                    )
                    logger.warning(error_msg)
                    break

                # Collecter le texte et les tool_use du message assistant.
                assistant_content: list[dict[str, Any]] = []
                tool_uses: list[dict[str, Any]] = []
                turn_text_parts: list[str] = []

                for block in response.content:
                    btype = getattr(block, "type", None)
                    if btype == "thinking":
                        # Bloc de raisonnement (extended thinking). Doit etre
                        # preserve AVEC sa signature dans l'historique assistant
                        # pour que l'API Anthropic accepte les tours suivants.
                        thinking_text = getattr(block, "thinking", "") or ""
                        signature = getattr(block, "signature", "")
                        assistant_content.append({
                            "type": "thinking",
                            "thinking": thinking_text,
                            "signature": signature,
                        })
                        yield LoopEvent("thinking_block", {
                            "turn": turns,
                            "text": thinking_text,
                            "length": len(thinking_text),
                        })
                    elif btype == "text":
                        text = getattr(block, "text", "")
                        turn_text_parts.append(text)
                        assistant_content.append({"type": "text", "text": text})
                        if text.strip():
                            yield LoopEvent("thinking", {"text": text, "turn": turns})
                    elif btype == "tool_use":
                        tool_use_block = {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                        assistant_content.append(tool_use_block)
                        tool_uses.append(tool_use_block)

                # Ajouter le message assistant complet a l'historique.
                messages.append({"role": "assistant", "content": assistant_content})

                # Si pas de tool_use -> fin de boucle.
                if stop_reason != "tool_use" or not tool_uses:
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                # Sinon, executer chaque tool_use et batcher les results.
                tool_results: list[dict[str, Any]] = []
                needs_confirmation_for: list[dict[str, Any]] = []
                for tu in tool_uses:
                    action_type = tool_name_to_action_type(tu["name"])
                    action_input = tu["input"] if isinstance(tu["input"], dict) else {}

                    yield LoopEvent("tool_use", {
                        "turn": turns,
                        "tool_use_id": tu["id"],
                        "name": tu["name"],
                        "action_type": action_type,
                        "input": action_input,
                    })

                    # Gate confirmation : action destructive non pre-approuvee -> on pause.
                    # En mode "bypass", le gate est desactive (auto-execution).
                    if (self.permission_mode != "bypass"
                            and action_type in self.DESTRUCTIVE_ACTIONS
                            and tu["id"] not in self.pre_approved_tool_ids):
                        needs_confirmation_for.append({
                            "tool_use_id": tu["id"],
                            "name": tu["name"],
                            "action_type": action_type,
                            "input": action_input,
                        })
                        yield LoopEvent("confirmation_needed", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "name": tu["name"],
                            "action_type": action_type,
                            "input": action_input,
                            "reason": f"Action destructive ({action_type}) — confirmation utilisateur requise avant execution.",
                        })
                        continue  # on passe aux autres tool_uses, mais on stoppera la boucle apres
                    # Bypass mode : on trace pour l'audit
                    if (self.permission_mode == "bypass"
                            and action_type in self.DESTRUCTIVE_ACTIONS
                            and tu["id"] not in self.pre_approved_tool_ids):
                        yield LoopEvent("auto_approved_bypass", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "name": tu["name"],
                            "action_type": action_type,
                        })

                    # Pre-hooks : possibilite de MODIFY ou BLOCK avant execution.
                    action_input, blocked = await self._run_pre_hooks(action_type, action_input)
                    if blocked is not None:
                        yield LoopEvent("hook_blocked", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "hook_name": blocked.get("_hook_name", ""),
                            "reason": blocked.get("_reason", ""),
                        })
                        exec_result = {
                            "content": blocked["content"],
                            "is_error": True,
                            "raw": blocked.get("raw", {}),
                        }
                        actions_executed.append({
                            "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "input": action_input,
                            "result": exec_result,
                        })
                        yield LoopEvent("tool_result", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "is_error": True,
                            "content_preview": str(exec_result["content"])[:200],
                            "raw": exec_result.get("raw"),
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": str(exec_result["content"]),
                            "is_error": True,
                        })
                        continue

                    # ── Phase 4 : feedback live auto-extension ClawHub ─────────
                    # Avant chaque meta-tool CLAWHUB_*, on annonce la phase en
                    # cours pour que l'UI affiche un indicateur live "l'agent
                    # cherche/installe un nouveau skill" sans attendre le result.
                    _is_clawhub_meta = action_type in {
                        "CLAWHUB_SEARCH", "CLAWHUB_INSTALL", "CLAWHUB_PUBLISH",
                    }
                    if _is_clawhub_meta:
                        _phase_map = {
                            "CLAWHUB_SEARCH": "search",
                            "CLAWHUB_INSTALL": "install",
                            "CLAWHUB_PUBLISH": "publish",
                        }
                        _trigger_summary = str(
                            action_input.get("query")
                            or action_input.get("slug")
                            or action_input.get("name")
                            or ""
                        )[:120]
                        yield LoopEvent("auto_extension_start", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "phase": _phase_map[action_type],
                            "action_type": action_type,
                            "trigger": _trigger_summary,
                        })

                    try:
                        # SPAWN_AGENT spawn child AgenticLoop entiere → tres long.
                        # Override timeout pour ces cas specifiques (5 min).
                        _eff_timeout = (
                            300.0 if action_type in ("SPAWN_AGENT", "OPENCLAW_SESSION", "COMPUTER_USE")
                            else self.tool_timeout_s
                        )
                        exec_result = await asyncio.wait_for(
                            self.executor.execute(action_type, action_input),
                            timeout=_eff_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Tool {action_type} hit timeout after {self.tool_timeout_s}s"
                        )
                        exec_result = {
                            "content": (
                                f"L'outil '{action_type}' a depasse le delai de "
                                f"{int(self.tool_timeout_s)}s et a ete interrompu. "
                                "Propose une alternative ou un perimetre plus restreint."
                            ),
                            "is_error": True,
                            "raw": {"timeout_s": self.tool_timeout_s},
                        }
                    except Exception as e:
                        logger.exception(f"Executor crashed on {action_type}: {e}")
                        exec_result = {
                            "content": f"Erreur technique: {str(e)[:500]}",
                            "is_error": True,
                            "raw": {"exception": str(e)},
                        }

                    # Post-hooks : audit/log uniquement (ne modifie pas le resultat).
                    await self._run_post_hooks(action_type, action_input, exec_result)

                    actions_executed.append({
                        "tool_use_id": tu["id"],
                        "action_type": action_type,
                        "input": action_input,
                        "result": exec_result,
                    })

                    yield LoopEvent("tool_result", {
                        "turn": turns,
                        "tool_use_id": tu["id"],
                        "action_type": action_type,
                        "is_error": bool(exec_result.get("is_error")),
                        "content_preview": str(exec_result.get("content", ""))[:200],
                        "raw": exec_result.get("raw"),
                    })

                    # ── Phase 4 : feedback live auto-extension (post-execution) ─
                    # Apres chaque meta-tool CLAWHUB_* reussi, on emet un event
                    # specialise pour piloter l'UI :
                    #   - auto_extension_found : search OK, liste des candidats
                    #   - auto_extension_ready : install/publish OK, skill actif
                    # En cas d'echec, on emet auto_extension_error.
                    if _is_clawhub_meta:
                        _ok = not bool(exec_result.get("is_error"))
                        _raw = exec_result.get("raw") or {}
                        if not _ok:
                            yield LoopEvent("auto_extension_error", {
                                "turn": turns,
                                "tool_use_id": tu["id"],
                                "phase": _phase_map[action_type],
                                "action_type": action_type,
                                "message": str(exec_result.get("content", ""))[:300],
                            })
                        elif action_type == "CLAWHUB_SEARCH":
                            _candidates: list[dict[str, Any]] = []
                            if isinstance(_raw, dict):
                                _skills_raw = (
                                    _raw.get("results")
                                    or _raw.get("skills")
                                    or _raw.get("data")
                                    or []
                                )
                                for s in _skills_raw[:5]:
                                    if isinstance(s, dict):
                                        _candidates.append({
                                            "slug": s.get("slug") or s.get("name", ""),
                                            "name": s.get("name", ""),
                                            "description": (s.get("description") or "")[:120],
                                            "author": s.get("author") or s.get("owner") or "",
                                            "version": s.get("version") or s.get("latestVersion") or "",
                                        })
                            yield LoopEvent("auto_extension_found", {
                                "turn": turns,
                                "tool_use_id": tu["id"],
                                "query": _trigger_summary,
                                "candidates": _candidates,
                                "count": len(_candidates),
                            })
                        elif action_type == "CLAWHUB_INSTALL":
                            _slug = str(action_input.get("slug") or "")
                            _tool_alias = (
                                f"skill_{_slug.replace('-', '_')}"
                                if _slug else ""
                            )
                            yield LoopEvent("auto_extension_ready", {
                                "turn": turns,
                                "tool_use_id": tu["id"],
                                "phase": "install",
                                "slug": _slug,
                                "tool_alias": _tool_alias,
                            })
                            # Regenere self.tools pour que skill_<slug> soit
                            # visible des le prochain tour LLM (sinon le modele
                            # ne verra pas le nouveau tool et devra attendre
                            # une nouvelle session).
                            _refresh_info = self._refresh_tools_after_install()
                            yield LoopEvent("tools_refreshed", {
                                "turn": turns,
                                "tool_use_id": tu["id"],
                                "trigger": "clawhub_install",
                                "slug": _slug,
                                "added_slugs": _refresh_info.get("added", []),
                                "total_before": _refresh_info.get("total_before", 0),
                                "total_after": _refresh_info.get("total_after", 0),
                                "ok": bool(_refresh_info.get("ok", False)),
                            })
                        elif action_type == "CLAWHUB_PUBLISH":
                            yield LoopEvent("auto_extension_ready", {
                                "turn": turns,
                                "tool_use_id": tu["id"],
                                "phase": "publish",
                                "slug": str(action_input.get("slug") or ""),
                            })

                    # ── Feedback visuel : card cliquable apres action destructive ──
                    # Emis UNIQUEMENT pour les actions destructives reussies (non-clawhub).
                    # Le frontend affiche une card dans le chat avec titre/sous-titre
                    # et eventuellement download_url ou external_url.
                    if (
                        action_type in self.DESTRUCTIVE_ACTIONS
                        and action_type not in {"CLAWHUB_INSTALL", "CLAWHUB_PUBLISH"}
                        and not bool(exec_result.get("is_error"))
                    ):
                        _action_payload = _build_action_done_payload(
                            action_type, action_input, exec_result,
                        )
                        if _action_payload is not None:
                            _action_payload.update({
                                "turn": turns,
                                "tool_use_id": tu["id"],
                            })
                            yield LoopEvent("action_done", _action_payload)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": str(exec_result.get("content", "")),
                        "is_error": bool(exec_result.get("is_error", False)),
                    })

                # Si des tool_uses destructifs attendent confirmation, on arrete
                # la boucle ici. Le router va serialiser l'etat et attendre la
                # reponse de l'utilisateur avant de reprendre via /chat/native/resume.
                if needs_confirmation_for:
                    self.pending_confirmation = {
                        "messages": messages,  # inclut le assistant turn avec tool_use
                        "pending_tool_uses": needs_confirmation_for,
                        "already_executed_results": tool_results,  # tool_results des tool_uses non-destructifs deja faits ce tour
                        "turn": turns,
                        "actions_executed": actions_executed,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                    }
                    stop_reason = "awaiting_confirmation"
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                # Feed tous les tool_results en un seul message user.
                messages.append({"role": "user", "content": tool_results})
            else:
                # max_turns atteint sans end_turn naturel.
                error_msg = f"Max turns ({self.max_turns}) atteint — boucle interrompue."
                logger.warning(error_msg)
                yield LoopEvent("error", {"message": error_msg})

        except Exception as e:
            error_msg = f"AgenticLoop crashed: {e}"
            logger.exception(error_msg)
            yield LoopEvent("error", {"message": error_msg})

        self.result = LoopResult(
            final_text=final_text,
            turns=turns,
            actions_executed=actions_executed,
            stop_reason=stop_reason,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            error=error_msg,
        )
        done_data = {
            "turns": turns,
            "actions_count": len(actions_executed),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "final_text_preview": final_text[:200],
            "total_cost_usd": round(self._estimate_cost_usd(total_input, total_output), 4),
            "model": self.model,
            "error": error_msg,
        }
        yield LoopEvent("done", done_data)
        self._log_event("done", done_data)

    async def resume_from_confirmation(
        self,
        pending_state: dict[str, Any],
        approvals: dict[str, bool],
    ) -> AsyncIterator[LoopEvent]:
        """Reprend une boucle apres qu'un event `confirmation_needed` a ete leve.

        pending_state : le dict stocke dans self.pending_confirmation au pause.
        approvals : {tool_use_id: bool} — True approuve, False refuse.

        Pour chaque tool_use en attente :
          - approved=True  -> on execute l'action via l'executor
          - approved=False -> on emet un tool_result is_error=True expliquant le refus
        Puis on continue la boucle LLM<->tools normalement.
        """
        messages = [dict(m) for m in pending_state["messages"]]
        pending_uses = pending_state["pending_tool_uses"]
        already_executed = pending_state.get("already_executed_results", [])
        start_turn = pending_state["turn"]
        actions_executed: list[dict[str, Any]] = list(pending_state.get("actions_executed", []))
        total_input = pending_state.get("total_input_tokens", 0)
        total_output = pending_state.get("total_output_tokens", 0)

        # 1) Construire les tool_results pour chaque tool_use en attente.
        tool_results: list[dict[str, Any]] = list(already_executed)
        for tu in pending_uses:
            tu_id = tu["tool_use_id"]
            action_type = tu["action_type"]
            action_input = tu["input"]
            approved = bool(approvals.get(tu_id, False))

            # ── Phase 4 : feedback live auto-extension (chemin resume) ─────
            # Si l'utilisateur a confirme un CLAWHUB_INSTALL/PUBLISH destructif,
            # on annonce la phase juste avant l'execution (symetrique au chemin
            # principal pour que l'UI affiche la meme live banner).
            _is_clawhub_meta = action_type in {
                "CLAWHUB_SEARCH", "CLAWHUB_INSTALL", "CLAWHUB_PUBLISH",
            }
            _phase_map = {
                "CLAWHUB_SEARCH": "search",
                "CLAWHUB_INSTALL": "install",
                "CLAWHUB_PUBLISH": "publish",
            }
            _trigger_summary = str(
                action_input.get("query")
                or action_input.get("slug")
                or action_input.get("name")
                or ""
            )[:120]
            if approved and _is_clawhub_meta:
                yield LoopEvent("auto_extension_start", {
                    "turn": start_turn,
                    "tool_use_id": tu_id,
                    "phase": _phase_map[action_type],
                    "action_type": action_type,
                    "trigger": _trigger_summary,
                })

            if approved:
                try:
                    exec_result = await asyncio.wait_for(
                        self.executor.execute(action_type, action_input),
                        timeout=self.tool_timeout_s,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Confirmed tool {action_type} hit timeout after {self.tool_timeout_s}s"
                    )
                    exec_result = {
                        "content": (
                            f"L'outil '{action_type}' a depasse le delai de "
                            f"{int(self.tool_timeout_s)}s et a ete interrompu."
                        ),
                        "is_error": True,
                        "raw": {"timeout_s": self.tool_timeout_s},
                    }
                except Exception as e:
                    logger.exception(f"Executor crashed on confirmed {action_type}: {e}")
                    exec_result = {
                        "content": f"Erreur technique: {str(e)[:500]}",
                        "is_error": True,
                        "raw": {"exception": str(e)},
                    }
                # Post-hooks (audit/log) apres execution destructive approuvee.
                await self._run_post_hooks(action_type, action_input, exec_result)
            else:
                exec_result = {
                    "content": f"L'utilisateur a refuse l'execution de {action_type}. "
                               f"Explique pourquoi tu voulais le faire et propose une alternative non destructive.",
                    "is_error": True,
                    "raw": {"user_denied": True},
                }

            actions_executed.append({
                "tool_use_id": tu_id,
                "action_type": action_type,
                "input": action_input,
                "result": exec_result,
                "user_approved": approved,
            })

            yield LoopEvent("tool_result", {
                "turn": start_turn,
                "tool_use_id": tu_id,
                "action_type": action_type,
                "is_error": bool(exec_result.get("is_error")),
                "content_preview": str(exec_result.get("content", ""))[:200],
                "raw": exec_result.get("raw"),
                "user_approved": approved,
            })

            # ── Phase 4 : feedback live auto-extension (post-resume) ───────
            # Apres execution d'un CLAWHUB_* approuve, on emet le meme
            # ready/found/error que dans le chemin principal.
            if approved and _is_clawhub_meta:
                _ok = not bool(exec_result.get("is_error"))
                _raw = exec_result.get("raw") or {}
                if not _ok:
                    yield LoopEvent("auto_extension_error", {
                        "turn": start_turn,
                        "tool_use_id": tu_id,
                        "phase": _phase_map[action_type],
                        "action_type": action_type,
                        "message": str(exec_result.get("content", ""))[:300],
                    })
                elif action_type == "CLAWHUB_SEARCH":
                    _candidates: list[dict[str, Any]] = []
                    if isinstance(_raw, dict):
                        _skills_raw = (
                            _raw.get("results")
                            or _raw.get("skills")
                            or _raw.get("data")
                            or []
                        )
                        for s in _skills_raw[:5]:
                            if isinstance(s, dict):
                                _candidates.append({
                                    "slug": s.get("slug") or s.get("name", ""),
                                    "name": s.get("name", ""),
                                    "description": (s.get("description") or "")[:120],
                                    "author": s.get("author") or s.get("owner") or "",
                                    "version": s.get("version") or s.get("latestVersion") or "",
                                })
                    yield LoopEvent("auto_extension_found", {
                        "turn": start_turn,
                        "tool_use_id": tu_id,
                        "query": _trigger_summary,
                        "candidates": _candidates,
                        "count": len(_candidates),
                    })
                elif action_type == "CLAWHUB_INSTALL":
                    _slug = str(action_input.get("slug") or "")
                    _tool_alias = (
                        f"skill_{_slug.replace('-', '_')}"
                        if _slug else ""
                    )
                    yield LoopEvent("auto_extension_ready", {
                        "turn": start_turn,
                        "tool_use_id": tu_id,
                        "phase": "install",
                        "slug": _slug,
                        "tool_alias": _tool_alias,
                    })
                    _refresh_info = self._refresh_tools_after_install()
                    yield LoopEvent("tools_refreshed", {
                        "turn": start_turn,
                        "tool_use_id": tu_id,
                        "trigger": "clawhub_install",
                        "slug": _slug,
                        "added_slugs": _refresh_info.get("added", []),
                        "total_before": _refresh_info.get("total_before", 0),
                        "total_after": _refresh_info.get("total_after", 0),
                        "ok": bool(_refresh_info.get("ok", False)),
                    })
                elif action_type == "CLAWHUB_PUBLISH":
                    yield LoopEvent("auto_extension_ready", {
                        "turn": start_turn,
                        "tool_use_id": tu_id,
                        "phase": "publish",
                        "slug": str(action_input.get("slug") or ""),
                    })

            # ── Feedback visuel : card cliquable apres action destructive ──
            if (
                action_type in self.DESTRUCTIVE_ACTIONS
                and action_type not in {"CLAWHUB_INSTALL", "CLAWHUB_PUBLISH"}
                and not bool(exec_result.get("is_error"))
            ):
                _action_payload = _build_action_done_payload(
                    action_type, action_input, exec_result,
                )
                if _action_payload is not None:
                    _action_payload.update({
                        "turn": start_turn,
                        "tool_use_id": tu_id,
                    })
                    yield LoopEvent("action_done", _action_payload)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": str(exec_result.get("content", "")),
                "is_error": bool(exec_result.get("is_error", False)),
            })

        # 2) Injecter tous les tool_results comme un seul message user.
        messages.append({"role": "user", "content": tool_results})

        # 3) Reset pending state — la confirmation est traitee.
        self.pending_confirmation = None

        # 4) Relancer la boucle principale a partir du tour suivant.
        turns = start_turn
        final_text = ""
        stop_reason = "unknown"
        error_msg: str | None = None

        try:
            while turns < self.max_turns:
                if self._is_cancelled():
                    stop_reason = "cancelled"
                    yield LoopEvent("cancelled", {"turn": turns, "phase": "between_turns"})
                    break
                turns += 1
                self._current_turn = turns
                yield LoopEvent("turn_start", {"turn": turns})

                # Auto-compaction : si on approche du plafond de tokens du
                # modele, on compresse les anciens tool_results volumineux.
                # On ne le fait qu'une fois par run pour eviter de boucler.
                if (not self._compacted_once
                        and total_input >= self.auto_compact_threshold
                        and len(messages) > 6):
                    messages, chars_saved = compact_messages(
                        messages, keep_last_n=4, max_tool_result_chars=300,
                    )
                    self._compacted_once = True
                    yield LoopEvent("context_compacted", {
                        "turn": turns,
                        "chars_saved": chars_saved,
                        "threshold_tokens": self.auto_compact_threshold,
                        "total_input_tokens_at_trigger": total_input,
                    })

                t0 = time.perf_counter()
                cancelled_mid_stream = False
                try:
                    if self.stream:
                        async for sev in self._stream_llm_turn(messages, turns):
                            if sev.type == "cancelled":
                                cancelled_mid_stream = True
                            yield sev
                        response = self._last_stream_response
                        if cancelled_mid_stream or response is None:
                            stop_reason = "cancelled"
                            break
                    else:
                        response = await self._call_llm_with_retry(messages, turns)
                except Exception as e:
                    error_msg = f"LLM call failed at turn {turns}: {e}"
                    logger.exception(error_msg)
                    yield LoopEvent("error", {"message": error_msg, "turn": turns})
                    break

                dt = time.perf_counter() - t0
                total_input += getattr(response.usage, "input_tokens", 0)
                total_output += getattr(response.usage, "output_tokens", 0)
                stop_reason = response.stop_reason or "unknown"

                turn_done_data = {
                    "turn": turns,
                    "stop_reason": stop_reason,
                    "latency_ms": int(dt * 1000),
                    "input_tokens": getattr(response.usage, "input_tokens", 0),
                    "output_tokens": getattr(response.usage, "output_tokens", 0),
                    "cum_cost_usd": round(self._estimate_cost_usd(total_input, total_output), 4),
                }
                yield LoopEvent("turn_llm_done", turn_done_data)
                self._log_event("turn_llm_done", turn_done_data)

                if self._is_cost_exceeded(total_input, total_output):
                    cost = self._estimate_cost_usd(total_input, total_output)
                    cap_data = {
                        "turn": turns,
                        "cost_usd": round(cost, 4),
                        "cap_usd": self.cost_hard_cap_usd,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                    }
                    yield LoopEvent("cost_exceeded", cap_data)
                    self._log_event("cost_exceeded", cap_data)
                    stop_reason = "cost_exceeded"
                    error_msg = (
                        f"Budget cost hard-cap atteint: ${cost:.4f} >= "
                        f"${self.cost_hard_cap_usd:.4f}. Reprise interrompue."
                    )
                    logger.warning(error_msg)
                    break

                assistant_content: list[dict[str, Any]] = []
                tool_uses: list[dict[str, Any]] = []
                turn_text_parts: list[str] = []

                for block in response.content:
                    btype = getattr(block, "type", None)
                    if btype == "thinking":
                        # Bloc de raisonnement (extended thinking). Doit etre
                        # preserve AVEC sa signature dans l'historique assistant
                        # pour que l'API Anthropic accepte les tours suivants.
                        thinking_text = getattr(block, "thinking", "") or ""
                        signature = getattr(block, "signature", "")
                        assistant_content.append({
                            "type": "thinking",
                            "thinking": thinking_text,
                            "signature": signature,
                        })
                        yield LoopEvent("thinking_block", {
                            "turn": turns,
                            "text": thinking_text,
                            "length": len(thinking_text),
                        })
                    elif btype == "text":
                        text = getattr(block, "text", "")
                        turn_text_parts.append(text)
                        assistant_content.append({"type": "text", "text": text})
                        if text.strip():
                            yield LoopEvent("thinking", {"text": text, "turn": turns})
                    elif btype == "tool_use":
                        tool_use_block = {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                        assistant_content.append(tool_use_block)
                        tool_uses.append(tool_use_block)

                messages.append({"role": "assistant", "content": assistant_content})

                if stop_reason != "tool_use" or not tool_uses:
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                # Nouveau batch de tool_uses -> on applique le meme gate que dans run().
                new_results: list[dict[str, Any]] = []
                needs_confirmation_for: list[dict[str, Any]] = []
                for tu in tool_uses:
                    action_type = tool_name_to_action_type(tu["name"])
                    action_input = tu["input"] if isinstance(tu["input"], dict) else {}

                    yield LoopEvent("tool_use", {
                        "turn": turns, "tool_use_id": tu["id"], "name": tu["name"],
                        "action_type": action_type, "input": action_input,
                    })

                    if (self.permission_mode != "bypass"
                            and action_type in self.DESTRUCTIVE_ACTIONS
                            and tu["id"] not in self.pre_approved_tool_ids):
                        needs_confirmation_for.append({
                            "tool_use_id": tu["id"], "name": tu["name"],
                            "action_type": action_type, "input": action_input,
                        })
                        yield LoopEvent("confirmation_needed", {
                            "turn": turns, "tool_use_id": tu["id"], "name": tu["name"],
                            "action_type": action_type, "input": action_input,
                            "reason": f"Action destructive ({action_type}) — confirmation utilisateur requise.",
                        })
                        continue
                    if (self.permission_mode == "bypass"
                            and action_type in self.DESTRUCTIVE_ACTIONS
                            and tu["id"] not in self.pre_approved_tool_ids):
                        yield LoopEvent("auto_approved_bypass", {
                            "turn": turns, "tool_use_id": tu["id"], "name": tu["name"],
                            "action_type": action_type,
                        })

                    # Pre-hooks (MODIFY / BLOCK) aussi cote resume.
                    action_input, blocked = await self._run_pre_hooks(action_type, action_input)
                    if blocked is not None:
                        yield LoopEvent("hook_blocked", {
                            "turn": turns, "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "hook_name": blocked.get("_hook_name", ""),
                            "reason": blocked.get("_reason", ""),
                        })
                        exec_result = {
                            "content": blocked["content"], "is_error": True,
                            "raw": blocked.get("raw", {}),
                        }
                        actions_executed.append({
                            "tool_use_id": tu["id"], "action_type": action_type,
                            "input": action_input, "result": exec_result,
                        })
                        yield LoopEvent("tool_result", {
                            "turn": turns, "tool_use_id": tu["id"], "action_type": action_type,
                            "is_error": True,
                            "content_preview": str(exec_result["content"])[:200],
                            "raw": exec_result.get("raw"),
                        })
                        new_results.append({
                            "type": "tool_result", "tool_use_id": tu["id"],
                            "content": str(exec_result["content"]), "is_error": True,
                        })
                        continue

                    try:
                        # SPAWN_AGENT spawn child AgenticLoop entiere → tres long.
                        # Override timeout pour ces cas specifiques (5 min).
                        _eff_timeout = (
                            300.0 if action_type in ("SPAWN_AGENT", "OPENCLAW_SESSION", "COMPUTER_USE")
                            else self.tool_timeout_s
                        )
                        exec_result = await asyncio.wait_for(
                            self.executor.execute(action_type, action_input),
                            timeout=_eff_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Tool {action_type} hit timeout after {self.tool_timeout_s}s (resume)"
                        )
                        exec_result = {
                            "content": f"L'outil '{action_type}' a depasse le delai de {int(self.tool_timeout_s)}s.",
                            "is_error": True,
                            "raw": {"timeout_s": self.tool_timeout_s},
                        }
                    except Exception as e:
                        logger.exception(f"Executor crashed on {action_type}: {e}")
                        exec_result = {"content": f"Erreur technique: {str(e)[:500]}", "is_error": True, "raw": {"exception": str(e)}}

                    await self._run_post_hooks(action_type, action_input, exec_result)

                    actions_executed.append({
                        "tool_use_id": tu["id"], "action_type": action_type,
                        "input": action_input, "result": exec_result,
                    })
                    yield LoopEvent("tool_result", {
                        "turn": turns, "tool_use_id": tu["id"], "action_type": action_type,
                        "is_error": bool(exec_result.get("is_error")),
                        "content_preview": str(exec_result.get("content", ""))[:200],
                        "raw": exec_result.get("raw"),
                    })
                    new_results.append({
                        "type": "tool_result", "tool_use_id": tu["id"],
                        "content": str(exec_result.get("content", "")),
                        "is_error": bool(exec_result.get("is_error", False)),
                    })

                if needs_confirmation_for:
                    self.pending_confirmation = {
                        "messages": messages, "pending_tool_uses": needs_confirmation_for,
                        "already_executed_results": new_results, "turn": turns,
                        "actions_executed": actions_executed,
                        "total_input_tokens": total_input, "total_output_tokens": total_output,
                    }
                    stop_reason = "awaiting_confirmation"
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                messages.append({"role": "user", "content": new_results})
            else:
                error_msg = f"Max turns ({self.max_turns}) atteint — boucle interrompue."
                logger.warning(error_msg)
                yield LoopEvent("error", {"message": error_msg})

        except Exception as e:
            error_msg = f"AgenticLoop.resume crashed: {e}"
            logger.exception(error_msg)
            yield LoopEvent("error", {"message": error_msg})

        self.result = LoopResult(
            final_text=final_text, turns=turns, actions_executed=actions_executed,
            stop_reason=stop_reason, total_input_tokens=total_input,
            total_output_tokens=total_output, error=error_msg,
        )
        yield LoopEvent("done", {
            "turns": turns, "actions_count": len(actions_executed),
            "input_tokens": total_input, "output_tokens": total_output,
            "final_text_preview": final_text[:200], "error": error_msg,
        })


# ══════════════════════════════════════════════════════════════════════════════
# 4. Utilitaires de test
# ══════════════════════════════════════════════════════════════════════════════


class MockExecutor:
    """Executeur fake pour les tests — retourne ce qu'on lui dit."""

    def __init__(self, responses: dict[str, dict] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, action_type: str, action_input: dict) -> dict:
        self.calls.append((action_type, action_input))
        return self.responses.get(action_type, {
            "content": f"[mock] {action_type} executed",
            "is_error": False,
            "raw": {},
        })


__all__ = [
    "build_tool_schemas",
    "tool_name_to_action_type",
    "compact_messages",
    "ActionExecutor",
    "AgenticLoop",
    "LoopEvent",
    "LoopResult",
    "MockExecutor",
]
