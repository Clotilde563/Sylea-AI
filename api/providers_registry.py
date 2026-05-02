"""
Catalogue des providers API-key supportes par Sylea Integrations.

Chaque entree decrit :
  - Comment afficher le provider (logo, description, categorie)
  - Quels champs l'user doit fournir (api_key, workspace_id, ...)
  - Les patterns regex pour reconnaitre une cle collee sans contexte
  - Le tutoriel pour obtenir la cle
  - L'endpoint de test (pour valider immediatement)
  - Les skills ClawHub qui consomment ces credentials

Fonctions utilitaires exposees :
  - `get_provider(slug) -> dict | None`
  - `all_providers() -> list[dict]`
  - `detect_provider_from_key(value) -> tuple[str, str] | None`  # (slug, field_key)
  - `search_providers(query) -> list[(slug, score)]`
"""

from __future__ import annotations

import re
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Catalogue
# ─────────────────────────────────────────────────────────────────────────────

# Structure d'un provider :
# {
#   "slug": "stripe",               # identifiant stable
#   "display_name": "Stripe",
#   "description": "Paiements, abonnements, factures",
#   "category": "payments",         # "payments"|"ai"|"comms"|"dev"|"data"|"crm"|"productivity"
#   "logo_emoji": "💳",             # fallback si pas d'asset svg
#   "aliases": ["stripe.com"],
#   "fields": [
#       {
#         "key": "api_key",
#         "label": "Cle secrete (sk_live_ ou sk_test_)",
#         "type": "password",
#         "required": True,
#         "pattern": "^sk_(live|test)_[A-Za-z0-9]{20,}$",
#         "pattern_hint": "Commence par sk_live_ (prod) ou sk_test_ (test)",
#         "metadata_from_match": {"environment": "$1"},  # capture groupe regex
#       }
#   ],
#   "tutorial_url": "...",
#   "tutorial_steps": [...],
#   "test": {
#       "method": "GET",
#       "url": "https://api.stripe.com/v1/account",
#       "auth": "bearer",           # "bearer" | "basic" | "header"
#       "auth_field": "api_key",
#       "success_status": [200],
#   },
#   "used_by_skills": ["stripe"],
# }

PROVIDERS: list[dict[str, Any]] = [
    # ═══════════════ PAIEMENTS ═══════════════
    {
        "slug": "stripe",
        "display_name": "Stripe",
        "description": "Paiements, abonnements, factures",
        "category": "payments",
        "logo_emoji": "💳",
        "aliases": ["stripe.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle secrete (sk_live_ ou sk_test_)",
                "type": "password",
                "required": True,
                "pattern": r"^sk_(live|test)_[A-Za-z0-9]{20,}$",
                "pattern_hint": "Commence par sk_live_ (prod) ou sk_test_ (test)",
                "metadata_from_match": {"environment": "$1"},
            },
            {
                "key": "webhook_secret",
                "label": "Webhook signing secret (optionnel)",
                "type": "password",
                "required": False,
                "pattern": r"^whsec_[A-Za-z0-9]{30,}$",
            },
        ],
        "tutorial_url": "https://docs.stripe.com/keys",
        "tutorial_steps": [
            "Connecte-toi sur dashboard.stripe.com",
            "Va dans Developers → API keys",
            "Clique sur 'Reveal test key' ou 'Create secret key' pour prod",
            "Copie-colle la cle ici (elle commence par sk_)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.stripe.com/v1/account",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["stripe", "stripe-subscriptions"],
    },

    # ═══════════════ IA / LLM ═══════════════
    {
        "slug": "openai",
        "display_name": "OpenAI",
        "description": "GPT-4, DALL-E, Whisper, embeddings",
        "category": "ai",
        "logo_emoji": "🤖",
        "aliases": ["openai.com", "gpt", "chatgpt"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API (commence par sk-)",
                "type": "password",
                "required": True,
                # Lookahead negatif pour eviter les conflits avec :
                #   - sk-ant- (Anthropic)
                #   - sk-or-v1- (OpenRouter)
                # Les autres LLM (groq=gsk_, mistral=32 chars nu, deepseek=sk-hex)
                # ont des patterns distincts.
                "pattern": r"^sk-(?!ant-|or-v1-)(proj-)?[A-Za-z0-9_-]{40,}$",
                "pattern_hint": "Commence par sk- ou sk-proj- (pas sk-ant-, ni sk-or-v1-)",
            },
            {
                "key": "organization_id",
                "label": "Organization ID (optionnel, org-...)",
                "type": "text",
                "required": False,
                "pattern": r"^org-[A-Za-z0-9]{20,}$",
            },
        ],
        "tutorial_url": "https://platform.openai.com/api-keys",
        "tutorial_steps": [
            "Va sur platform.openai.com/api-keys",
            "Clique 'Create new secret key'",
            "Donne un nom (ex: 'Sylea') + copie la cle",
            "Colle-la ici (elle commence par sk-)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.openai.com/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["openai", "gpt4-analyst"],
    },
    {
        "slug": "anthropic",
        "display_name": "Anthropic",
        "description": "Claude Opus, Sonnet, Haiku",
        "category": "ai",
        "logo_emoji": "🎭",
        "aliases": ["claude", "anthropic.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API (sk-ant-api03-...)",
                "type": "password",
                "required": True,
                "pattern": r"^sk-ant-api\d{2}-[A-Za-z0-9_-]{80,}$",
                "pattern_hint": "Commence par sk-ant-api03-",
            },
        ],
        "tutorial_url": "https://console.anthropic.com/settings/keys",
        "tutorial_steps": [
            "Va sur console.anthropic.com/settings/keys",
            "Clique 'Create Key'",
            "Copie-colle la cle (sk-ant-api03-...)",
        ],
        "test": {
            "method": "POST",
            "url": "https://api.anthropic.com/v1/messages",
            "auth": "header",
            "auth_field": "api_key",
            "auth_header_name": "x-api-key",
            "extra_headers": {"anthropic-version": "2023-06-01", "content-type": "application/json"},
            "body": {"model": "claude-haiku-4-5-20250929", "max_tokens": 1,
                     "messages": [{"role": "user", "content": "hi"}]},
            "success_status": [200],
        },
        "used_by_skills": ["anthropic-direct"],
    },
    {
        "slug": "groq",
        "display_name": "Groq",
        "description": "LLMs rapides (Llama, Mixtral) via Groq LPU",
        "category": "ai",
        "logo_emoji": "⚡",
        "aliases": ["groq.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API (gsk_...)",
                "type": "password",
                "required": True,
                "pattern": r"^gsk_[A-Za-z0-9]{40,}$",
            },
        ],
        "tutorial_url": "https://console.groq.com/keys",
        "tutorial_steps": [
            "Va sur console.groq.com/keys",
            "Clique 'Create API Key'",
            "Copie-colle la cle (gsk_...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.groq.com/openai/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["groq"],
    },
    {
        "slug": "perplexity",
        "display_name": "Perplexity",
        "description": "Recherche IA avec citations en temps reel",
        "category": "ai",
        "logo_emoji": "🔍",
        "aliases": ["pplx", "perplexity.ai"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API (pplx-...)",
                "type": "password",
                "required": True,
                "pattern": r"^pplx-[a-f0-9]{40,}$",
            },
        ],
        "tutorial_url": "https://www.perplexity.ai/settings/api",
        "tutorial_steps": [
            "Va sur perplexity.ai/settings/api",
            "Genere une cle API",
            "Colle-la ici (pplx-...)",
        ],
        "test": {
            "method": "POST",
            "url": "https://api.perplexity.ai/chat/completions",
            "auth": "bearer",
            "auth_field": "api_key",
            "body": {"model": "sonar", "messages": [{"role": "user", "content": "hi"}]},
            "success_status": [200],
        },
        "used_by_skills": ["perplexity-search"],
    },

    # ═══════════════ COMMUNICATION ═══════════════
    {
        "slug": "slack",
        "display_name": "Slack",
        "description": "Envoyer / lire messages, canaux, DM",
        "category": "comms",
        "logo_emoji": "💬",
        "aliases": ["slack.com"],
        "fields": [
            {
                "key": "bot_token",
                "label": "Bot User OAuth Token (xoxb-...)",
                "type": "password",
                "required": True,
                "pattern": r"^xoxb-\d+-\d+-[A-Za-z0-9]+$",
            },
        ],
        "tutorial_url": "https://api.slack.com/authentication/basics",
        "tutorial_steps": [
            "Cree une app sur api.slack.com/apps",
            "Section 'OAuth & Permissions' → ajoute les scopes 'chat:write', 'channels:read'",
            "Clique 'Install to Workspace'",
            "Copie le 'Bot User OAuth Token' (commence par xoxb-)",
        ],
        "test": {
            "method": "POST",
            "url": "https://slack.com/api/auth.test",
            "auth": "bearer",
            "auth_field": "bot_token",
            "success_status": [200],
        },
        "used_by_skills": ["slack", "slack-notifications"],
    },
    {
        "slug": "discord",
        "display_name": "Discord",
        "description": "Bot Discord : messages, serveurs",
        "category": "comms",
        "logo_emoji": "🎮",
        "aliases": ["discord.com"],
        "fields": [
            {
                "key": "bot_token",
                "label": "Bot Token",
                "type": "password",
                "required": True,
                # Discord bot tokens : 3 segments base64 separes par '.'
                "pattern": r"^[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{27,}$",
            },
        ],
        "tutorial_url": "https://discord.com/developers/applications",
        "tutorial_steps": [
            "Va sur discord.com/developers/applications",
            "Clique 'New Application' → nomme-la",
            "Section 'Bot' → 'Reset Token' → copie le token",
            "Invite le bot sur ton serveur via OAuth2 URL Generator",
        ],
        "test": {
            "method": "GET",
            "url": "https://discord.com/api/v10/users/@me",
            "auth": "header",
            "auth_field": "bot_token",
            "auth_header_name": "Authorization",
            "auth_header_format": "Bot {value}",
            "success_status": [200],
        },
        "used_by_skills": ["discord", "discord-bot"],
    },
    {
        "slug": "telegram",
        "display_name": "Telegram",
        "description": "Bot Telegram : envoi de messages, automatisations",
        "category": "comms",
        "logo_emoji": "✈️",
        "aliases": ["telegram.org"],
        "fields": [
            {
                "key": "bot_token",
                "label": "Bot token (obtenu via @BotFather)",
                "type": "password",
                "required": True,
                "pattern": r"^\d{8,10}:[A-Za-z0-9_-]{33,46}$",
            },
        ],
        "tutorial_url": "https://core.telegram.org/bots#how-do-i-create-a-bot",
        "tutorial_steps": [
            "Ouvre Telegram et parle a @BotFather",
            "Tape /newbot et suis les instructions",
            "BotFather te donne un token (format 123456789:XXX...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.telegram.org/bot{bot_token}/getMe",
            "auth": "url_template",
            "auth_field": "bot_token",
            "success_status": [200],
        },
        "used_by_skills": ["telegram", "telegram-bot"],
    },

    # ═══════════════ PRODUCTIVITE ═══════════════
    {
        "slug": "notion",
        "display_name": "Notion",
        "description": "Pages, databases, automatisations",
        "category": "productivity",
        "logo_emoji": "📓",
        "aliases": ["notion.so"],
        "fields": [
            {
                "key": "integration_token",
                "label": "Integration token (secret_...)",
                "type": "password",
                "required": True,
                "pattern": r"^(secret_|ntn_)[A-Za-z0-9]{40,}$",
            },
        ],
        "tutorial_url": "https://www.notion.so/my-integrations",
        "tutorial_steps": [
            "Va sur notion.so/my-integrations",
            "Clique 'New integration', nomme-la 'Sylea'",
            "Copie le 'Internal Integration Token' (secret_...)",
            "Ajoute cette integration a tes pages Notion pour qu'elle y ait acces",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.notion.com/v1/users/me",
            "auth": "bearer",
            "auth_field": "integration_token",
            "extra_headers": {"Notion-Version": "2022-06-28"},
            "success_status": [200],
        },
        "used_by_skills": ["notion"],
    },
    {
        "slug": "linear",
        "display_name": "Linear",
        "description": "Gestion projet, tickets, issues",
        "category": "productivity",
        "logo_emoji": "📐",
        "aliases": ["linear.app"],
        "fields": [
            {
                "key": "api_key",
                "label": "Personal API key (lin_api_...)",
                "type": "password",
                "required": True,
                "pattern": r"^lin_api_[A-Za-z0-9]{40,}$",
            },
        ],
        "tutorial_url": "https://linear.app/settings/api",
        "tutorial_steps": [
            "Linear → Settings → API → Personal API keys",
            "Clique 'Create API key'",
            "Copie-colle (lin_api_...)",
        ],
        "test": {
            "method": "POST",
            "url": "https://api.linear.app/graphql",
            "auth": "header",
            "auth_field": "api_key",
            "auth_header_name": "Authorization",
            "auth_header_format": "{value}",
            "body": {"query": "{ viewer { id } }"},
            "success_status": [200],
        },
        "used_by_skills": ["linear"],
    },
    {
        "slug": "airtable",
        "display_name": "Airtable",
        "description": "Bases de donnees spreadsheet",
        "category": "data",
        "logo_emoji": "📊",
        "aliases": ["airtable.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "Personal access token (patXXX ou keyXXX)",
                "type": "password",
                "required": True,
                "pattern": r"^(pat[A-Za-z0-9]{14,}\.[A-Za-z0-9]{40,}|key[A-Za-z0-9]{14,})$",
            },
        ],
        "tutorial_url": "https://airtable.com/create/tokens",
        "tutorial_steps": [
            "Va sur airtable.com/create/tokens",
            "Clique 'Create new token' → ajoute les scopes data.records:read/write",
            "Attache tes bases, puis copie le token (pat...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.airtable.com/v0/meta/whoami",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["airtable"],
    },

    # ═══════════════ DEV / CODE ═══════════════
    {
        "slug": "github",
        "display_name": "GitHub",
        "description": "Issues, PRs, actions, repos",
        "category": "dev",
        "logo_emoji": "🐙",
        "aliases": ["github.com"],
        "fields": [
            {
                "key": "personal_access_token",
                "label": "Personal Access Token (ghp_... ou github_pat_...)",
                "type": "password",
                "required": True,
                "pattern": r"^(gh[psu]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})$",
            },
        ],
        "tutorial_url": "https://github.com/settings/tokens",
        "tutorial_steps": [
            "github.com/settings/tokens → 'Generate new token (classic)'",
            "Donne un nom, choisis les scopes (repo, workflow, ...)",
            "Copie le token (ghp_... ou github_pat_...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.github.com/user",
            "auth": "header",
            "auth_field": "personal_access_token",
            "auth_header_name": "Authorization",
            "auth_header_format": "Bearer {value}",
            "extra_headers": {"Accept": "application/vnd.github+json"},
            "success_status": [200],
        },
        "used_by_skills": ["github"],
    },
    {
        "slug": "supabase",
        "display_name": "Supabase",
        "description": "Base Postgres + auth + storage",
        "category": "dev",
        "logo_emoji": "🗄️",
        "aliases": ["supabase.com", "supabase.io"],
        "fields": [
            {
                "key": "service_role_key",
                "label": "Service role key (secret, bypasse RLS)",
                "type": "password",
                "required": True,
                # JWT : 3 segments base64 separes par '.'
                "pattern": r"^eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
            },
            {
                "key": "project_url",
                "label": "Project URL (https://xyz.supabase.co)",
                "type": "text",
                "required": True,
                "pattern": r"^https://[a-z0-9]+\.supabase\.(co|io)$",
            },
        ],
        "tutorial_url": "https://supabase.com/dashboard/project/_/settings/api",
        "tutorial_steps": [
            "Supabase → ton projet → Settings → API",
            "Copie l'URL du projet",
            "Copie la 'service_role' key (section Project API keys)",
        ],
        "test": None,  # JWT check local suffit, pas de test endpoint
        "used_by_skills": ["supabase"],
    },

    # ═══════════════ IA / LLM SUPPLEMENTAIRES ═══════════════
    {
        "slug": "mistral",
        "display_name": "Mistral AI",
        "description": "LLMs Mistral, Codestral, Pixtral",
        "category": "ai",
        "logo_emoji": "🌬️",
        "aliases": ["mistral.ai"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API",
                "type": "password",
                "required": True,
                "pattern": r"^[A-Za-z0-9]{32}$",
                "pattern_hint": "32 caracteres alphanumeriques",
            },
        ],
        "tutorial_url": "https://console.mistral.ai/api-keys",
        "tutorial_steps": [
            "console.mistral.ai/api-keys",
            "Clique 'Create new key'",
            "Copie la cle (32 chars)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.mistral.ai/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["mistral"],
    },
    {
        "slug": "cohere",
        "display_name": "Cohere",
        "description": "LLMs + embeddings + reranking",
        "category": "ai",
        "logo_emoji": "🔮",
        "aliases": ["cohere.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API",
                "type": "password",
                "required": True,
                "pattern": r"^[A-Za-z0-9]{40,45}$",
            },
        ],
        "tutorial_url": "https://dashboard.cohere.com/api-keys",
        "tutorial_steps": [
            "dashboard.cohere.com/api-keys",
            "Create trial key (gratuit) ou production",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.cohere.com/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["cohere"],
    },
    {
        "slug": "openrouter",
        "display_name": "OpenRouter",
        "description": "Aggregator : acces a 200+ LLMs via 1 seule API",
        "category": "ai",
        "logo_emoji": "🛣️",
        "aliases": ["openrouter.ai"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API (sk-or-v1-...)",
                "type": "password",
                "required": True,
                "pattern": r"^sk-or-v1-[a-f0-9]{64}$",
            },
        ],
        "tutorial_url": "https://openrouter.ai/keys",
        "tutorial_steps": [
            "openrouter.ai/keys",
            "Create Key",
            "Charge ton credit (ou utilise free tier)",
        ],
        "test": {
            "method": "GET",
            "url": "https://openrouter.ai/api/v1/auth/key",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["openrouter"],
    },
    {
        "slug": "deepseek",
        "display_name": "DeepSeek",
        "description": "LLMs DeepSeek Chat et Coder",
        "category": "ai",
        "logo_emoji": "🔬",
        "aliases": ["deepseek.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API",
                "type": "password",
                "required": True,
                "pattern": r"^sk-[a-f0-9]{32}$",
            },
        ],
        "tutorial_url": "https://platform.deepseek.com/api_keys",
        "tutorial_steps": [
            "platform.deepseek.com/api_keys",
            "Create API Key",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.deepseek.com/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["deepseek"],
    },
    {
        "slug": "xai",
        "display_name": "xAI Grok",
        "description": "Grok 3+ pour reasoning, temps reel",
        "category": "ai",
        "logo_emoji": "🤖",
        "aliases": ["grok", "x.ai"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API (xai-...)",
                "type": "password",
                "required": True,
                "pattern": r"^xai-[A-Za-z0-9]{80,}$",
            },
        ],
        "tutorial_url": "https://console.x.ai/",
        "tutorial_steps": [
            "console.x.ai → API Keys",
            "Create Key",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.x.ai/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["xai", "grok"],
    },
    {
        "slug": "huggingface",
        "display_name": "Hugging Face",
        "description": "Modeles open-source + inference endpoints",
        "category": "ai",
        "logo_emoji": "🤗",
        "aliases": ["hf", "huggingface.co"],
        "fields": [
            {
                "key": "api_token",
                "label": "User Access Token (hf_...)",
                "type": "password",
                "required": True,
                "pattern": r"^hf_[A-Za-z0-9]{34,}$",
            },
        ],
        "tutorial_url": "https://huggingface.co/settings/tokens",
        "tutorial_steps": [
            "huggingface.co/settings/tokens",
            "New token (Read ou Write scope)",
            "Copie (hf_...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://huggingface.co/api/whoami-v2",
            "auth": "bearer",
            "auth_field": "api_token",
            "success_status": [200],
        },
        "used_by_skills": ["huggingface"],
    },
    {
        "slug": "replicate",
        "display_name": "Replicate",
        "description": "Run ML models via API (image, video, audio)",
        "category": "ai",
        "logo_emoji": "🔁",
        "aliases": ["replicate.com"],
        "fields": [
            {
                "key": "api_token",
                "label": "API Token (r8_...)",
                "type": "password",
                "required": True,
                "pattern": r"^r8_[A-Za-z0-9]{36,}$",
            },
        ],
        "tutorial_url": "https://replicate.com/account/api-tokens",
        "tutorial_steps": [
            "replicate.com/account/api-tokens",
            "Create token",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.replicate.com/v1/account",
            "auth": "header",
            "auth_field": "api_token",
            "auth_header_name": "Authorization",
            "auth_header_format": "Token {value}",
            "success_status": [200],
        },
        "used_by_skills": ["replicate"],
    },
    {
        "slug": "together",
        "display_name": "Together AI",
        "description": "LLMs open-source, fine-tuning",
        "category": "ai",
        "logo_emoji": "🤝",
        "aliases": ["together.ai"],
        "fields": [
            {
                "key": "api_key",
                "label": "Cle API",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{64}$",
            },
        ],
        "tutorial_url": "https://api.together.xyz/settings/api-keys",
        "tutorial_steps": [
            "api.together.xyz/settings/api-keys",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.together.xyz/v1/models",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["together"],
    },

    # ═══════════════ EMAIL / TRANSACTIONAL ═══════════════
    {
        "slug": "sendgrid",
        "display_name": "SendGrid",
        "description": "Email transactionnel a grande echelle",
        "category": "comms",
        "logo_emoji": "📧",
        "aliases": ["sendgrid.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (SG.XXX.YYY)",
                "type": "password",
                "required": True,
                "pattern": r"^SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$",
            },
        ],
        "tutorial_url": "https://app.sendgrid.com/settings/api_keys",
        "tutorial_steps": [
            "app.sendgrid.com/settings/api_keys",
            "Create API Key → Full Access ou Restricted",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.sendgrid.com/v3/user/account",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["sendgrid", "email-transactional"],
    },
    {
        "slug": "resend",
        "display_name": "Resend",
        "description": "Email API moderne pour dev",
        "category": "comms",
        "logo_emoji": "✉️",
        "aliases": ["resend.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (re_...)",
                "type": "password",
                "required": True,
                "pattern": r"^re_[A-Za-z0-9]{20,}_[A-Za-z0-9]{20,}$",
            },
        ],
        "tutorial_url": "https://resend.com/api-keys",
        "tutorial_steps": [
            "resend.com/api-keys → Create API Key",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.resend.com/domains",
            "auth": "bearer",
            "auth_field": "api_key",
            "success_status": [200],
        },
        "used_by_skills": ["resend"],
    },
    {
        "slug": "mailgun",
        "display_name": "Mailgun",
        "description": "Email transactionnel + validation",
        "category": "comms",
        "logo_emoji": "🔫",
        "aliases": ["mailgun.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (key-... ou commence par autre)",
                "type": "password",
                "required": True,
                "pattern": r"^(key-[a-f0-9]{32}|[a-f0-9]{32}-[a-f0-9]{8}-[a-f0-9]{8})$",
            },
            {
                "key": "domain",
                "label": "Domaine configure (ex: mg.example.com)",
                "type": "text",
                "required": True,
            },
        ],
        "tutorial_url": "https://app.mailgun.com/app/account/security/api_keys",
        "tutorial_steps": [
            "app.mailgun.com/app/account/security/api_keys",
            "Recopie la 'Private API key'",
        ],
        "test": None,
        "used_by_skills": ["mailgun"],
    },
    {
        "slug": "twilio",
        "display_name": "Twilio",
        "description": "SMS, WhatsApp, voix",
        "category": "comms",
        "logo_emoji": "📞",
        "aliases": ["twilio.com"],
        "fields": [
            {
                "key": "account_sid",
                "label": "Account SID (AC...)",
                "type": "text",
                "required": True,
                "pattern": r"^AC[a-f0-9]{32}$",
            },
            {
                "key": "auth_token",
                "label": "Auth Token",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{32}$",
            },
        ],
        "tutorial_url": "https://console.twilio.com/",
        "tutorial_steps": [
            "console.twilio.com → Account Info",
            "Copie Account SID (commence par AC) + Auth Token",
        ],
        "test": None,
        "used_by_skills": ["twilio"],
    },

    # ═══════════════ CRM / MARKETING ═══════════════
    {
        "slug": "hubspot",
        "display_name": "HubSpot",
        "description": "CRM, marketing, sales",
        "category": "crm",
        "logo_emoji": "🧲",
        "aliases": ["hubspot.com"],
        "fields": [
            {
                "key": "access_token",
                "label": "Private App Access Token (pat-...)",
                "type": "password",
                "required": True,
                "pattern": r"^pat-(na1|eu1|na2|eu2)-[a-f0-9-]+$",
            },
        ],
        "tutorial_url": "https://app.hubspot.com/private-apps/",
        "tutorial_steps": [
            "Settings → Integrations → Private Apps",
            "Create private app → scopes souhaites",
            "Copie l'Access Token (pat-na1-...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
            "auth": "bearer",
            "auth_field": "access_token",
            "success_status": [200],
        },
        "used_by_skills": ["hubspot"],
    },
    {
        "slug": "intercom",
        "display_name": "Intercom",
        "description": "Support client + messagerie in-app",
        "category": "crm",
        "logo_emoji": "💬",
        "aliases": ["intercom.com"],
        "fields": [
            {
                "key": "access_token",
                "label": "Access Token (dG9rOjxhbGc...)",
                "type": "password",
                "required": True,
                "pattern": r"^dG9rOj[A-Za-z0-9+/=]{40,}$",
            },
        ],
        "tutorial_url": "https://app.intercom.com/a/apps/_/developer-hub",
        "tutorial_steps": [
            "Developer Hub → Your apps → New app",
            "Authentication → Access Token",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.intercom.io/me",
            "auth": "bearer",
            "auth_field": "access_token",
            "extra_headers": {"Intercom-Version": "2.11"},
            "success_status": [200],
        },
        "used_by_skills": ["intercom"],
    },
    {
        "slug": "mailchimp",
        "display_name": "Mailchimp",
        "description": "Email marketing, audiences, campagnes",
        "category": "crm",
        "logo_emoji": "🐵",
        "aliases": ["mailchimp.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (xxxx-usNN)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{32}-us\d{1,3}$",
                "pattern_hint": "Format : 32 hex + '-' + server prefix (ex: us14)",
            },
        ],
        "tutorial_url": "https://mailchimp.com/help/about-api-keys/",
        "tutorial_steps": [
            "Profile → Extras → API keys",
            "Create A Key",
        ],
        "test": None,
        "used_by_skills": ["mailchimp"],
    },

    # ═══════════════ DEV / OPS / ANALYTICS ═══════════════
    {
        "slug": "vercel",
        "display_name": "Vercel",
        "description": "Deploiement, domaines, team",
        "category": "dev",
        "logo_emoji": "▲",
        "aliases": ["vercel.com"],
        "fields": [
            {
                "key": "access_token",
                "label": "Access Token",
                "type": "password",
                "required": True,
                # Exclut les tokens commencant par AC (Twilio SID) et les prefixes
                # communs pour eviter les faux positifs.
                "pattern": r"^(?!AC)[A-Za-z0-9]{24,}$",
            },
        ],
        "tutorial_url": "https://vercel.com/account/tokens",
        "tutorial_steps": [
            "vercel.com/account/tokens",
            "Create Token",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.vercel.com/v2/user",
            "auth": "bearer",
            "auth_field": "access_token",
            "success_status": [200],
        },
        "used_by_skills": ["vercel"],
    },
    {
        "slug": "sentry",
        "display_name": "Sentry",
        "description": "Error tracking, performance monitoring",
        "category": "dev",
        "logo_emoji": "🛡️",
        "aliases": ["sentry.io"],
        "fields": [
            {
                "key": "auth_token",
                "label": "Auth Token",
                "type": "password",
                "required": True,
                "pattern": r"^(sntrys_|sntryu_)[A-Za-z0-9+/=_-]+$",
            },
        ],
        "tutorial_url": "https://sentry.io/settings/account/api/auth-tokens/",
        "tutorial_steps": [
            "Settings → API → Auth Tokens",
            "Create New Token → scopes requis",
        ],
        "test": None,
        "used_by_skills": ["sentry"],
    },
    {
        "slug": "posthog",
        "display_name": "PostHog",
        "description": "Analytics produit + session replay",
        "category": "dev",
        "logo_emoji": "🦔",
        "aliases": ["posthog.com"],
        "fields": [
            {
                "key": "project_api_key",
                "label": "Project API Key (phc_...)",
                "type": "password",
                "required": True,
                "pattern": r"^phc_[A-Za-z0-9]{40,}$",
            },
        ],
        "tutorial_url": "https://app.posthog.com/project/settings",
        "tutorial_steps": [
            "Settings → Project API key",
            "Copie (phc_...)",
        ],
        "test": None,
        "used_by_skills": ["posthog"],
    },
    {
        "slug": "datadog",
        "display_name": "Datadog",
        "description": "Monitoring, logs, APM",
        "category": "dev",
        "logo_emoji": "🐶",
        "aliases": ["datadoghq.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (32 hex)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{32}$",
            },
            {
                "key": "app_key",
                "label": "Application Key (40 hex)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{40}$",
            },
        ],
        "tutorial_url": "https://app.datadoghq.com/organization-settings/api-keys",
        "tutorial_steps": [
            "Organization Settings → API Keys → New Key",
            "Application Keys → New Key",
        ],
        "test": None,
        "used_by_skills": ["datadog"],
    },
    {
        "slug": "cloudflare",
        "display_name": "Cloudflare",
        "description": "DNS, CDN, Workers, R2",
        "category": "dev",
        "logo_emoji": "🌥️",
        "aliases": ["cloudflare.com"],
        "fields": [
            {
                "key": "api_token",
                "label": "API Token (scoped)",
                "type": "password",
                "required": True,
                # Exclut prefixes communs (hf_, sk-, ghp_, pat-, phc_, xoxb-, gsk_, r8_)
                # pour eviter les faux positifs. Les vrais tokens Cloudflare n'ont pas
                # de prefixe specifique, d'ou le besoin d'exclure les autres.
                "pattern": r"^(?!(hf_|sk-|gh[psu]_|pat-|phc_|xox|gsk_|r8_|re_|SG\.|pk_|lin_|xai-|secret_))[A-Za-z0-9_-]{40}$",
            },
        ],
        "tutorial_url": "https://dash.cloudflare.com/profile/api-tokens",
        "tutorial_steps": [
            "Profile → API Tokens → Create Token",
            "Scopes granulaires (DNS, Workers, R2, ...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.cloudflare.com/client/v4/user/tokens/verify",
            "auth": "bearer",
            "auth_field": "api_token",
            "success_status": [200],
        },
        "used_by_skills": ["cloudflare"],
    },
    {
        "slug": "mixpanel",
        "display_name": "Mixpanel",
        "description": "Product analytics, cohorts, funnels",
        "category": "dev",
        "logo_emoji": "📈",
        "aliases": ["mixpanel.com"],
        "fields": [
            {
                "key": "project_token",
                "label": "Project Token (32 hex)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{32}$",
            },
        ],
        "tutorial_url": "https://mixpanel.com/settings/project",
        "tutorial_steps": [
            "Project Settings → Access Keys",
        ],
        "test": None,
        "used_by_skills": ["mixpanel"],
    },

    # ═══════════════ PRODUCTIVITE ═══════════════
    {
        "slug": "clickup",
        "display_name": "ClickUp",
        "description": "Gestion projet, tasks, docs",
        "category": "productivity",
        "logo_emoji": "✅",
        "aliases": ["clickup.com"],
        "fields": [
            {
                "key": "api_token",
                "label": "Personal API Token (pk_...)",
                "type": "password",
                "required": True,
                "pattern": r"^pk_\d+_[A-Z0-9]{30,}$",
            },
        ],
        "tutorial_url": "https://app.clickup.com/settings/apps",
        "tutorial_steps": [
            "Profile → Settings → Apps",
            "Copie le Personal Token (pk_...)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.clickup.com/api/v2/user",
            "auth": "header",
            "auth_field": "api_token",
            "auth_header_name": "Authorization",
            "auth_header_format": "{value}",
            "success_status": [200],
        },
        "used_by_skills": ["clickup"],
    },
    {
        "slug": "asana",
        "display_name": "Asana",
        "description": "Gestion projet, teams",
        "category": "productivity",
        "logo_emoji": "📋",
        "aliases": ["asana.com"],
        "fields": [
            {
                "key": "access_token",
                "label": "Personal Access Token",
                "type": "password",
                "required": True,
                "pattern": r"^\d+/\d+:[a-f0-9]{32}$",
            },
        ],
        "tutorial_url": "https://app.asana.com/0/my-apps",
        "tutorial_steps": [
            "Profile → My Apps",
            "Create new token",
        ],
        "test": {
            "method": "GET",
            "url": "https://app.asana.com/api/1.0/users/me",
            "auth": "bearer",
            "auth_field": "access_token",
            "success_status": [200],
        },
        "used_by_skills": ["asana"],
    },
    {
        "slug": "trello",
        "display_name": "Trello",
        "description": "Boards, cards, lists",
        "category": "productivity",
        "logo_emoji": "📌",
        "aliases": ["trello.com"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (32 hex)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{32}$",
            },
            {
                "key": "token",
                "label": "OAuth Token",
                "type": "password",
                "required": True,
                "pattern": r"^(ATTA)?[A-Za-z0-9]{64,}$",
            },
        ],
        "tutorial_url": "https://trello.com/power-ups/admin",
        "tutorial_steps": [
            "Power-Ups Admin → New Power-Up ou existant",
            "Generate API Key + Token",
        ],
        "test": None,
        "used_by_skills": ["trello"],
    },

    # ═══════════════ DATA ═══════════════
    {
        "slug": "pinecone",
        "display_name": "Pinecone",
        "description": "Vector DB pour RAG / semantic search",
        "category": "data",
        "logo_emoji": "🌲",
        "aliases": ["pinecone.io"],
        "fields": [
            {
                "key": "api_key",
                "label": "API Key (UUID)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            },
        ],
        "tutorial_url": "https://app.pinecone.io/organizations/-/projects/-/keys",
        "tutorial_steps": [
            "Pinecone console → API Keys",
            "Create new key",
        ],
        "test": None,
        "used_by_skills": ["pinecone", "rag-search"],
    },

    # ═══════════════ MEDIA ═══════════════
    {
        "slug": "elevenlabs",
        "display_name": "ElevenLabs",
        "description": "TTS voice cloning",
        "category": "ai",
        "logo_emoji": "🎙️",
        "aliases": ["elevenlabs.io"],
        "fields": [
            {
                "key": "api_key",
                "label": "xi-api-key (32 hex chars)",
                "type": "password",
                "required": True,
                "pattern": r"^[a-f0-9]{32}$",
            },
        ],
        "tutorial_url": "https://elevenlabs.io/app/speech-synthesis",
        "tutorial_steps": [
            "Connecte-toi sur elevenlabs.io",
            "Profil (en haut a droite) → 'API Key'",
            "Copie la cle (32 caracteres hex)",
        ],
        "test": {
            "method": "GET",
            "url": "https://api.elevenlabs.io/v1/voices",
            "auth": "header",
            "auth_field": "api_key",
            "auth_header_name": "xi-api-key",
            "auth_header_format": "{value}",
            "success_status": [200],
        },
        "used_by_skills": ["elevenlabs-tts"],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Index acces rapide
# ─────────────────────────────────────────────────────────────────────────────

_PROVIDERS_BY_SLUG: dict[str, dict] = {p["slug"]: p for p in PROVIDERS}


def get_provider(slug: str) -> dict | None:
    return _PROVIDERS_BY_SLUG.get(slug)


def all_providers(*, public: bool = True) -> list[dict]:
    """Retourne la liste de providers. Si public=True, enleve le field `test`
    (endpoint interne, evite fingerprinting des endpoints distants).
    """
    if public:
        out = []
        for p in PROVIDERS:
            safe = {k: v for k, v in p.items() if k != "test"}
            out.append(safe)
        return out
    return list(PROVIDERS)


# ─────────────────────────────────────────────────────────────────────────────
# Detection par pattern regex
# ─────────────────────────────────────────────────────────────────────────────

def detect_provider_from_key(value: str) -> list[dict]:
    """Parcourt le catalogue : pour chaque field avec regex, check si value match.

    Retourne une liste de matches (rarement > 1, mais possible en cas de patterns
    ambigus). Format : [{provider_slug, field_key, metadata}, ...].
    """
    if not value or not isinstance(value, str):
        return []
    value = value.strip()
    matches: list[dict] = []
    for p in PROVIDERS:
        for f in p.get("fields", []):
            pattern = f.get("pattern")
            if not pattern:
                continue
            m = re.match(pattern, value)
            if not m:
                continue
            # Capture les metadonnees issues des groupes regex (ex: env stripe)
            metadata: dict[str, Any] = {}
            meta_template = f.get("metadata_from_match")
            if isinstance(meta_template, dict):
                for k, v in meta_template.items():
                    if isinstance(v, str) and v.startswith("$"):
                        try:
                            idx = int(v[1:])
                            metadata[k] = m.group(idx)
                        except (ValueError, IndexError):
                            pass
            matches.append({
                "provider_slug": p["slug"],
                "field_key": f["key"],
                "provider_display_name": p["display_name"],
                "provider_logo_emoji": p.get("logo_emoji", "🔑"),
                "metadata": metadata,
            })
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# Recherche fuzzy par nom
# ─────────────────────────────────────────────────────────────────────────────

def _score_provider(provider: dict, query: str) -> float:
    """Score de matching nom/slug/aliases. 0-1."""
    q = query.lower().strip()
    if not q:
        return 0.0
    slug = provider["slug"].lower()
    name = provider["display_name"].lower()
    aliases = [a.lower() for a in provider.get("aliases", [])]

    # Match exact
    if q == slug or q == name:
        return 1.0
    # Prefix match (le plus courant : user tape "stri" -> "stripe")
    if slug.startswith(q) or name.startswith(q):
        return 0.9
    # Alias exact
    if q in aliases:
        return 0.85
    # Substring
    if q in slug or q in name:
        return 0.7
    if any(q in a for a in aliases):
        return 0.6
    # Chars communs (tres loose fallback)
    if len(q) >= 3 and sum(1 for c in q if c in slug + name) / len(q) >= 0.7:
        return 0.3
    return 0.0


def search_providers(query: str, *, limit: int = 8) -> list[tuple[str, float]]:
    """Retourne les slugs de providers classes par score decroissant."""
    if not query:
        return []
    scored = [(p["slug"], _score_provider(p, query)) for p in PROVIDERS]
    scored = [(s, sc) for s, sc in scored if sc > 0.25]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


__all__ = [
    "PROVIDERS",
    "get_provider",
    "all_providers",
    "detect_provider_from_key",
    "search_providers",
]
