# Sécurité niveau pro — Syléa.AI

Ce document décrit le dispositif de sécurité applicatif et infrastructure
mis en place pour Syléa.AI en production. Il complète la documentation
RGPD (`PrivacyPolicyPage`) et juridique (`TermsPage`) côté frontend.

## 1. Vue d'ensemble (defense in depth)

```
[ Internet ]
      │
      ▼
[ Cloudflare WAF + DDoS + Bot Management ]  ◄── couche infrastructure
      │
      ▼
[ Load balancer (TLS termination) ]
      │
      ▼
[ FastAPI + Middlewares ]                   ◄── couche applicative
   ├── IPRateLimitMiddleware (par IP)
   ├── CSRFMiddleware (POST/PUT/PATCH/DELETE)
   ├── SecurityHeadersMiddleware (CSP, HSTS, ...)
   └── CORSMiddleware
      │
      ▼
[ Routers + dépendances d'auth (JWT) ]
   └── RateLimit per-user (chat, openclaw)
      │
      ▼
[ Redis (caches + tokens buckets) ]
[ PostgreSQL (données chiffrées at rest) ]
[ Secrets : Vault / AWS SM / GCP SM ]
```

## 2. Secrets management

**Module** : `api/secrets_manager.py`

Le code applicatif lit ses secrets via `get_secret("DATABASE_URL")` sans
jamais dépendre d'un fichier `.env` en production. Backends supportés :

| Backend | Quand l'utiliser | Variable |
|---------|------------------|----------|
| `env`   | Dev local        | défaut   |
| `vault` | Auto-hébergement | `SYLEA_SECRETS_BACKEND=vault` |
| `aws`   | AWS (EKS, ECS)   | `SYLEA_SECRETS_BACKEND=aws`   |
| `gcp`   | GCP (Cloud Run)  | `SYLEA_SECRETS_BACKEND=gcp`   |

### Activation Vault

```bash
export SYLEA_SECRETS_BACKEND=vault
export VAULT_ADDR=https://vault.sylea.ai:8200
export VAULT_PATH=secret/data/sylea/prod
# Auth via AppRole (préférable au token statique)
export VAULT_ROLE_ID=...
export VAULT_SECRET_ID=...
```

Le secret Vault doit contenir un JSON :

```json
{
  "DATABASE_URL": "postgresql://...",
  "JWT_SECRET_KEY": "...",
  "ANTHROPIC_API_KEY": "...",
  "STRIPE_SECRET_KEY": "..."
}
```

### Activation AWS Secrets Manager

```bash
export SYLEA_SECRETS_BACKEND=aws
export AWS_REGION=eu-west-3
export AWS_SECRET_NAME=sylea/prod
# Credentials AWS via rôle IAM ou clés explicites
```

### Garde-fou prod

```bash
# Refuse de démarrer si SYLEA_SECRETS_BACKEND=env en production
export SYLEA_REQUIRE_REMOTE_SECRETS=true
```

### Cache

Les secrets sont mis en cache local 5 minutes (configurable) pour éviter
de marteler le backend distant à chaque requête.

## 3. WAF Cloudflare (anti-DDoS + anti-bot)

**Hors code applicatif** — à configurer dans le tableau de bord Cloudflare.

### Règles minimales recommandées

1. **DDoS protection** : `Security > DDoS > L7 sensitivity = High`
2. **Bot Fight Mode** : `Security > Bots > Bot Fight Mode = On`
3. **Managed Rules** :
   - Cloudflare Managed Ruleset = `Block`
   - OWASP Core Ruleset = `Block, Sensitivity = High`
4. **Rate limiting Cloudflare** (en plus de l'applicatif) :
   - `/api/auth/login` : 5 req / 10 min / IP
   - `/api/*` : 100 req / min / IP

### En-tête à vérifier côté FastAPI

Cloudflare envoie `CF-Connecting-IP` avec l'IP réelle du client. Activer :

```bash
export SYLEA_TRUSTED_PROXIES=true
```

→ le middleware `IPRateLimitMiddleware` utilisera cette en-tête au lieu
de l'IP TCP directe (qui serait celle de Cloudflare).

### Tunnel Argo (optionnel)

Pour éviter d'exposer l'IP du serveur d'origine :

```bash
cloudflared tunnel create sylea-api
cloudflared tunnel route dns sylea-api api.sylea.ai
cloudflared tunnel run sylea-api
```

Le serveur n'a alors **aucun port public ouvert**.

## 4. Rate limiting global par IP

**Module** : `api/ip_rate_limiter.py` (middleware FastAPI)

Couche applicative qui s'ajoute au WAF Cloudflare : protection même si
le WAF est bypassé (mauvaise config, attaque sur l'IP directe).

| Endpoint            | Capacité (burst) | Refill        |
|---------------------|------------------|---------------|
| `/api/auth/*`       | 10 req           | 0.1 req/s     |
| Autres `/api/*`     | 60 req           | 1.0 req/s     |
| `/api/health`, `/ws/*` | bypass        | —             |

### Configuration

```bash
SYLEA_IP_RATELIMIT_CAPACITY=60
SYLEA_IP_RATELIMIT_REFILL=1.0
SYLEA_IP_RATELIMIT_BURST_LOGIN=10
SYLEA_IP_RATELIMIT_REFILL_LOGIN=0.1
SYLEA_TRUSTED_PROXIES=true   # si derrière Cloudflare/nginx
```

### RGPD : pas d'IP en clair

Les IPs sont hashées (SHA-256, 16 chars) avant stockage Redis. Aucun
journal IP applicatif (Cloudflare reste responsable du log des IPs si
besoin légal). Conforme principe de minimisation RGPD art. 5.1.c.

## 5. CSRF protection

**Module** : `api/csrf_middleware.py`

Implémentation : **Double-Submit Cookie + Signed Token HMAC**.

### Flux

1. Premier `GET /api/*` : le middleware pose un cookie `sylea_csrf`
   contenant `<random>.<hmac>`. Cookie **non-HttpOnly** (lu par JS).
2. Le frontend lit le cookie et envoie `X-CSRF-Token: <même token>` sur
   chaque `POST/PUT/PATCH/DELETE`.
3. Le middleware vérifie :
   - `cookie === header` (double-submit)
   - signature HMAC valide (anti-forge côté client)
4. Si KO → `403 Forbidden`.

### Exemptions

- `/api/auth/login`, `/api/auth/signup`, `/api/auth/reset-*` — pas de
  session à protéger ; rate-limit IP suffit.
- `/api/stripe/webhook` — signature Stripe dédiée.
- `/ws/*` — auth JWT en query string.
- `/api/health`, `/static/*` — public.

### Configuration prod

```bash
export SYLEA_CSRF_COOKIE_SECURE=true       # HTTPS only
export SYLEA_CSRF_COOKIE_SAMESITE=lax      # ou strict si tout same-site
export SYLEA_CSRF_SECRET=<32+ bytes hex>   # ou dérivé de JWT_SECRET_KEY
```

### Côté frontend

```ts
// frontend/src/api/client.ts (à intégrer dans une PR séparée)
function getCsrfToken(): string {
  return document.cookie
    .split("; ")
    .find(c => c.startsWith("sylea_csrf="))
    ?.split("=")[1] || "";
}

// Sur chaque POST/PUT/PATCH/DELETE :
fetch("/api/foo", {
  method: "POST",
  headers: { "X-CSRF-Token": getCsrfToken() },
  credentials: "include",
  body: JSON.stringify(data),
});
```

## 6. CSP headers stricts

**Module** : `api/security_headers.py`

### Politique CSP (mode strict)

```
default-src 'self';
script-src 'self' https://js.stripe.com;
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob: https:;
font-src 'self' data:;
connect-src 'self' https://api.anthropic.com https://api.openai.com
           https://api.stripe.com https://api.open-meteo.com;
frame-src 'self' https://js.stripe.com https://checkout.stripe.com;
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
object-src 'none';
upgrade-insecure-requests;
```

### Autres headers

| Header | Valeur | Rôle |
|--------|--------|------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | HSTS 1 an + preload |
| `X-Content-Type-Options` | `nosniff` | Anti MIME confusion |
| `X-Frame-Options` | `DENY` | Anti clickjacking (legacy + nouveau) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Anti leak URL |
| `Permissions-Policy` | `camera=(), microphone=(self), geolocation=(self), ...` | Désactive APIs sensibles |
| `Cross-Origin-Opener-Policy` | `same-origin` | Isolation Spectre |
| `Cross-Origin-Resource-Policy` | `same-site` | Isolation cross-origin |

### Dev vs prod

- Mode `dev` (DATABASE_URL = sqlite) : autorise `'unsafe-eval'` pour Vite HMR, HSTS désactivé.
- Mode `strict` (DATABASE_URL PostgreSQL) : tout verrouillé, HSTS activé.

Override possible via `SYLEA_SECURITY_HEADERS_MODE=strict|dev`.

## 7. Pen test annuel (externe)

### Cadence

**1 fois par an + à chaque release majeure** (v2.0, v3.0...).

### Périmètre

- API REST FastAPI (routes auth, profil, dilemme, agent2, etc.)
- Web GUI React (XSS, CSRF, clickjacking, auth flow)
- Application desktop Tauri (escape sandbox, secrets storage)
- Infra : exposition serveur, IAM, segmentation réseau

### Prestataires recommandés

- **Synacktiv** (FR, expertise web + cloud)
- **NCC Group** (UK/intl, top tier)
- **Trail of Bits** (US, infra + cryptographie)

Budget indicatif : 15-30 k€ pour 5-10 jours-homme.

### Suivi

- Tous les findings `Critical`/`High` : remédiation < 30 jours.
- `Medium` : < 90 jours.
- Le rapport est conservé dans `docs/audits/YYYY-MM-pentest.pdf` (privé).

## 8. Bug bounty (HackerOne)

### Setup

1. Créer un programme **privé** sur https://hackerone.com (invitations
   ciblées de chercheurs réputés).
2. Définir le périmètre :
   - **In scope** : `*.sylea.ai`, app desktop, API publique.
   - **Out of scope** : tiers (Stripe, Anthropic), sous-domaines admin.
3. Politique de récompenses indicatives :

| Sévérité | Récompense |
|----------|------------|
| Critical | 1500-5000 € |
| High     | 500-1500 € |
| Medium   | 100-500 €  |
| Low      | swag / mention |

4. SLA de réponse :
   - 1ère réponse < 24 h
   - Triage < 7 jours
   - Patch + paiement < 30 jours (selon sévérité)

### Passage en bug bounty public

Après 6 mois sans bug critical en privé, ouvrir au public.

## 9. Effort & roadmap

| Étape | Effort | Status |
|-------|--------|--------|
| Secrets management abstraction | 0.5 j | ✅ fait |
| IP rate limiter (middleware) | 0.5 j | ✅ fait |
| CSRF middleware | 0.5 j | ✅ fait |
| CSP / HSTS / security headers | 0.5 j | ✅ fait |
| Frontend : envoi X-CSRF-Token | 0.5 j | ⏳ PR séparée |
| WAF Cloudflare config | 0.5 j | ⏳ infra |
| Pen test externe | budget + 2 sem coordination | ⏳ annuel |
| Bug bounty HackerOne | 1 j config + budget | ⏳ après v1.5 |

**Total** : ~2 semaines de dev + audit externe annuel.

## 10. Vérification post-déploiement

### Sanity check headers (depuis un client externe)

```bash
curl -I https://api.sylea.ai/api/health
# Vérifier : Strict-Transport-Security, Content-Security-Policy,
#           X-Frame-Options, etc.
```

### Endpoint de diagnostic

```bash
curl https://api.sylea.ai/api/health/security
# Retourne la config active (modes, drapeaux on/off) sans secret.
```

### Test CSRF (doit échouer)

```bash
curl -X POST https://api.sylea.ai/api/profil \
     -H "Content-Type: application/json" \
     -d '{"nom": "test"}'
# → 403 Forbidden { "code": "csrf_missing" }
```

### Test rate limit IP

```bash
for i in $(seq 1 70); do curl -s -o /dev/null -w "%{http_code}\n" \
  https://api.sylea.ai/api/profil; done
# → premiers 60 = 401 (auth manquante), reste = 429
```

### Outils tiers

- **https://securityheaders.com** : note A+ attendue.
- **https://observatory.mozilla.org** : note A+ attendue.
- **https://www.ssllabs.com/ssltest/** : note A+ attendue (TLS config).
