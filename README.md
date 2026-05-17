# 🔮 Syléa.AI — Votre assistant de vie augmenté

> Le premier assistant IA qui calcule votre probabilité de réussite et analyse chaque décision de votre vie.

🌐 **[Essayer gratuitement →](https://sylea-ai.vercel.app)**

---

## ✨ Fonctionnalités

### 📊 Moteur de probabilité
Calcul déterministe de la probabilité de réussite de votre objectif de vie, basé sur votre profil complet (compétences, finances, bien-être, temps disponible).

### 🧠 Analyse IA de chaque décision
Soumettez un dilemme → l'IA analyse les pros/cons avec des études scientifiques et calcule l'impact temporel sur votre objectif.

### 🤖 Agent Syléa 1 — Votre compagnon personnel
- Messages vocaux bidirectionnels (votre voix persistée)
- Mémoire longue entre sessions
- Extraction automatique d'informations personnelles
- Messages proactifs tous les 3 jours
- Gardien de contexte pour des analyses plus précises

### 📈 Statistiques en temps réel
- Graphique de progression avec mode Dynamique (lissé)
- Suivi multi-lignes des sous-objectifs
- Zoom temporel (7J, 30J, 90J, MAX)

### 🌍 Multi-langue
13 langues complètes : FR, EN, ES, DE, PT, AR, ZH, IT, RU, JA, KO, TR, HI

### 🔒 Sécurité & RGPD
- Authentification email + code de vérification
- OAuth Google/GitHub
- Conformité RGPD complète
- Politique de confidentialité + CGU

---

## 🚀 Démo en ligne

👉 **[sylea-ai.vercel.app](https://sylea-ai.vercel.app)**

---

## 🛠️ Stack technique

| Composant | Technologie |
|-----------|-------------|
| Frontend | React 19 + TypeScript + Vite |
| Backend | Python 3.13 + FastAPI |
| IA | Claude API (Anthropic) + OpenAI TTS |
| Base de données | SQLite (dev) / PostgreSQL (prod) |
| Auth | JWT + bcrypt + OAuth |
| Déploiement | Vercel (frontend) + Railway (backend) |
| Desktop | Tauri 2 + Rust (en développement) |
| Tests | pytest (150+) + Vitest (55+) |

---

## 📦 Installation locale

### Prérequis
- Python 3.11+
- Node.js 18+
- Clé API Anthropic ([console.anthropic.com](https://console.anthropic.com))

### 1. Cloner le projet
```bash
git clone https://github.com/Clotilde563/Sylea-AI.git
cd Sylea-AI
```

### 2. Configuration
```bash
cp .env.example .env
# Éditer .env avec votre clé API Anthropic
```

### 3. Backend
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

### 4. Frontend
```bash
cd frontend
npm install
npm run dev
```

### 5. Ouvrir
👉 http://localhost:5173

---

## 🧪 Tests

```bash
# Backend (150+ tests)
python -m pytest tests/ -v

# Frontend (55+ tests)
cd frontend && npm test
```

---

## 🚀 Déploiement production (PostgreSQL multi-user)

### 1. Provisionner PostgreSQL

Exemple avec Railway/Supabase/Neon — exposer la connection string :
```
postgresql://user:password@host:5432/sylea
```

### 2. Variables d'environnement critiques

```bash
# Voir .env.example pour la liste complete
DATABASE_URL=postgresql://user:pass@host:5432/sylea
JWT_SECRET_KEY=<generer avec: python -c "import secrets; print(secrets.token_urlsafe(64))">
SYLEA_CREDENTIALS_MASTER_KEY=<generer avec: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
ANTHROPIC_API_KEY=sk-ant-...
# OAuth (si besoin)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://votre-app.com/auth/callback
# Stripe (paiements)
STRIPE_SECRET_KEY=sk_live_...
```

### 3. Demarrage

```bash
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

L'application detecte automatiquement `DATABASE_URL=postgresql://...` et :
- Lance `alembic upgrade head` au demarrage (cree le schema PG)
- Utilise `RawDBProxy` (SQLAlchemy) au lieu de `sqlite3.Connection`
- Tous les endpoints async basculent sur PG via `session_factory`
- Repositories sync (CLI) deleguent vers async PG via `_run_async`

### 4. Securite

- **JWT_SECRET_KEY** est OBLIGATOIRE en prod : l'app crash au demarrage si absent (evite les tokens predictibles).
- **SYLEA_CREDENTIALS_MASTER_KEY** : chiffrement Fernet des tokens OAuth tiers.
- Multi-user isolation : filtres `auth_user_id` partout, audite manuellement.
- Voir `docs/MIGRATION_POSTGRESQL.md` pour les details techniques.

---

## 📧 Contact

- **Email** : sylea.ai.assistance@gmail.com
- **GitHub** : [Clotilde563/Sylea-AI](https://github.com/Clotilde563/Sylea-AI)

---

## 📄 Licence

Ce projet est sous licence propriétaire. Tous droits réservés © 2026 Syléa.AI

---

*Développé avec ❤️ et beaucoup de ☕*
