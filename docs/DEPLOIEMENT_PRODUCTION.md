# 🚀 Déploiement Production PostgreSQL — Guide complet Syléa.AI

> Ce guide couvre le déploiement de Syléa.AI en production multi-user avec PostgreSQL, à partir d'un repo cloné et configuré.

---

## 📐 Architecture cible

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend Web  │    │  Desktop Tauri  │    │   Mobile (à venir)
│  Vercel/Netlify │    │   Client local  │    │
│  React 19+Vite  │    │  (sur OS user)  │    │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │ HTTPS REST + WSS
                                ▼
                  ┌──────────────────────────┐
                  │   Backend FastAPI        │
                  │   Railway / Fly / Render │
                  │   uvicorn + workers      │
                  └──────────────┬───────────┘
                                 │ SQLAlchemy async
                                 ▼
                  ┌──────────────────────────┐
                  │   PostgreSQL 15+         │
                  │   Supabase/Neon/Railway  │
                  │   Multi-user isolation   │
                  └──────────────────────────┘
```

**Points clés :**
- Backend = source de vérité (PG)
- Frontend Web + Desktop = clients qui parlent REST/WS au backend
- Le desktop ne touche **PAS** directement la DB

---

## ⚙️ Étape 1 : Provisionner PostgreSQL

### Option A — Supabase (recommandé, gratuit jusqu'à 500MB)

1. Créer un projet sur [supabase.com](https://supabase.com)
2. Récupérer la connection string dans `Project Settings > Database`
3. Format : `postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres`

### Option B — Neon (serverless, scale to zero)

1. Créer un projet sur [neon.tech](https://neon.tech)
2. Récupérer le pooled connection string
3. Format : `postgresql://[user]:[pass]@[ep-id].neon.tech/sylea?sslmode=require`

### Option C — Railway PostgreSQL

1. Sur Railway, `New Project > Database > PostgreSQL`
2. Variable `DATABASE_URL` auto-injectée dans les services du projet

---

## 🔑 Étape 2 : Générer les secrets

```bash
# JWT secret (signature des tokens d'auth)
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(64))"

# Master key pour chiffrer les credentials tiers (OAuth tokens, API keys user)
python -c "from cryptography.fernet import Fernet; print('SYLEA_CREDENTIALS_MASTER_KEY=' + Fernet.generate_key().decode())"
```

⚠️ **CRITIQUE** : `JWT_SECRET_KEY` est **obligatoire** en prod PG.
L'app `crash` au démarrage si manquant (cf. `api/auth/security.py:_get_jwt_secret`).

---

## 🌐 Étape 3 : Déployer le backend FastAPI

### Option A — Railway (recommandé, déploiement Git auto)

1. Sur [railway.app](https://railway.app), `New Project > Deploy from GitHub`
2. Sélectionner le repo Syléa.AI
3. Service settings :
   - **Build command** : `pip install -r requirements.txt`
   - **Start command** : `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
4. Variables d'environnement à ajouter (`Settings > Variables`) :

```bash
# === OBLIGATOIRES ===
DATABASE_URL=postgresql://...           # Connection string PG (étape 1)
JWT_SECRET_KEY=...                       # Secret généré (étape 2)
SYLEA_CREDENTIALS_MASTER_KEY=...         # Master key Fernet (étape 2)
ANTHROPIC_API_KEY=sk-ant-...             # API Claude

# === OAUTH (si Google/GitHub login) ===
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://api.votre-app.com/auth/google/callback
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...

# === FRONTEND URL (pour CORS + redirections OAuth) ===
FRONTEND_URL=https://votre-app.vercel.app
CORS_ORIGINS=https://votre-app.vercel.app

# === STRIPE (paiements) ===
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_TEAM=price_...

# === EMAIL SMTP (verification compte) ===
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=sylea.ai.assistance@gmail.com
SMTP_PASSWORD=mot-de-passe-application  # PAS le mot de passe principal

# === OPTIONNEL : Push notifications ===
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_CLAIM_EMAIL=mailto:contact@sylea.ai

# === OPTIONNEL : Scheduler cron ===
SYLEA_SCHEDULER_ENABLED=true             # Active le scheduler en prod
SYLEA_SCHEDULER_DAILY_CAP_USD=5.0        # Cap quotidien Claude par scheduler
```

5. Déployer. Au premier démarrage, le backend va :
   - Détecter `DATABASE_URL=postgresql://...`
   - Lancer **automatiquement** `alembic upgrade head` (crée toutes les tables)
   - Démarrer FastAPI

### Option B — Fly.io

```bash
fly launch
# Editer fly.toml :
#   [http_service]
#   internal_port = 8000
fly secrets set DATABASE_URL=... JWT_SECRET_KEY=... ANTHROPIC_API_KEY=...
fly deploy
```

### Vérifier que le backend tourne

```bash
curl https://api.votre-app.com/api/health
# {"status": "ok", "db": "postgresql", "version": "..."}
```

---

## 💻 Étape 4 : Déployer le frontend (Vercel)

1. Sur [vercel.com](https://vercel.com), `Add New > Project > Import Git Repository`
2. **Root Directory** : `frontend`
3. Variables d'environnement :

```bash
VITE_API_URL=https://api.votre-app.com    # URL du backend (étape 3)
```

4. **Build settings** :
   - Framework Preset : `Vite`
   - Build command : `npm run build`
   - Output directory : `dist`
5. Déployer.

Vercel donne une URL `votre-app.vercel.app`. Ajouter cette URL dans :
- Backend Railway : `CORS_ORIGINS` + `FRONTEND_URL`
- Google OAuth Console : Authorized redirect URIs

---

## 🖥️ Étape 5 : Déployer le desktop Tauri (optionnel)

Le desktop est une app installable sur l'OS de l'utilisateur. Build :

```bash
cd desktop
echo "VITE_API_BASE=https://api.votre-app.com" > .env
npm install
npm run tauri build
```

Artefacts produits dans `src-tauri/target/release/bundle/` :
- Windows : `.msi`, `.exe`
- macOS : `.dmg`, `.app`
- Linux : `.deb`, `.AppImage`

Distribuer ces installeurs aux utilisateurs (page de download ou store).

L'utilisateur peut aussi changer l'URL backend après installation via :
```javascript
// Dans la console Tauri (Ctrl+Shift+I)
localStorage.setItem('sylea_api_base', 'https://api.autre-instance.com')
location.reload()
```

---

## 🔍 Étape 6 : Vérifications post-déploiement

### Test 1 : Health check
```bash
curl https://api.votre-app.com/api/health
```

### Test 2 : Schéma PG appliqué
```bash
# Se connecter à la DB et lister les tables
psql $DATABASE_URL -c "\dt"
# Doit lister : users, profil_utilisateur, decisions, agent3_*, etc.
```

### Test 3 : Signup + Login
```bash
# Inscription
curl -X POST https://api.votre-app.com/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPass123"}'

# Login
curl -X POST https://api.votre-app.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPass123"}'
# → {"access_token": "...", "user": {...}}
```

### Test 4 : Multi-user isolation
Créer 2 comptes, vérifier qu'un user ne voit jamais les données de l'autre (filtres `auth_user_id` partout).

### Test 5 : Frontend accessible
Visiter `https://votre-app.vercel.app`, créer un profil, faire un dilemme.

---

## 🛡️ Sécurité production checklist

- [ ] `JWT_SECRET_KEY` défini (sinon crash auto)
- [ ] `SYLEA_CREDENTIALS_MASTER_KEY` défini (chiffrement OAuth tokens)
- [ ] HTTPS partout (Vercel et Railway l'imposent)
- [ ] `CORS_ORIGINS` whitelistant SEULEMENT les domaines frontend
- [ ] `.env` jamais commité (`.gitignore` l'ignore)
- [ ] Stripe en mode **live** (pas test) avec webhook signing secret
- [ ] OAuth redirects whitelistés dans Google/GitHub console
- [ ] DB PG : backups quotidiens activés (Supabase/Neon le font auto)
- [ ] Logs : configurer Railway/Vercel logging (Sentry recommandé)
- [ ] Rate limits actifs (`api/agent3_chat_ratelimit.py` configuré)

---

## 🔄 Mises à jour futures

### Migrer le schéma PG (ajouter colonnes, tables)

```bash
# 1. Modifier les modèles dans api/database/models.py
# 2. Générer une migration Alembic
alembic revision --autogenerate -m "add new column"

# 3. Vérifier le fichier migration généré dans alembic/versions/
# 4. Commit + push
# 5. Au redémarrage du backend, alembic upgrade head s'exécute auto
```

### Redéployer

- **Backend** : Railway redéploie auto sur push Git
- **Frontend** : Vercel redéploie auto sur push Git
- **Desktop** : Build local + distribute nouveaux installeurs

---

## 💰 Coûts estimés (low traffic)

| Composant | Service | Coût gratuit | Coût prod |
|-----------|---------|--------------|-----------|
| PostgreSQL | Supabase | 500MB free | $25/mo (8GB) |
| PostgreSQL | Neon | 0.5GB free | $19/mo (10GB) |
| Backend | Railway | $5 free credit | $5–20/mo |
| Frontend | Vercel | Hobby free | $20/mo (Pro) |
| Domain | Namecheap/OVH | — | $10/an |
| Anthropic Claude | API | $5 credit | ~$50–200/mo (selon usage) |

**Total starter** : ~$30–50/mo pour démarrer.

---

## 🆘 Troubleshooting

### "JWT_SECRET_KEY non defini en mode PostgreSQL prod"
→ Vous avez oublié de définir la variable. Cf. Étape 2.

### "alembic.runtime.migration.MigrationContext: relation 'users' already exists"
→ La DB a déjà des tables (peut-être migration manuelle). Faire :
```bash
alembic stamp head  # marque la DB comme déjà à jour
```

### Frontend : "Network Error" / "CORS"
→ Vérifier `CORS_ORIGINS` et `FRONTEND_URL` côté backend.

### Desktop : "Serveur inaccessible"
→ Vérifier `VITE_API_BASE` et/ou `localStorage.setItem('sylea_api_base', ...)`.

### Logs backend : trop de "OpenClaw indisponible"
→ Normal en prod sans OpenClaw Gateway. Désactiver via :
```bash
SYLEA_OPENCLAW_DISABLED=true
```

---

## 📚 Documentation technique connexe

- `docs/MIGRATION_POSTGRESQL.md` — détails techniques de la migration
- `README.md` — installation locale dev
- `.env.example` — liste complète des variables d'environnement
- `alembic/versions/` — historique des migrations de schéma

---

*Guide rédigé après migration complète SQLite → PostgreSQL (commit `63e07e5`).*
