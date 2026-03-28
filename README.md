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
| Base de données | SQLite |
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

## 📧 Contact

- **Email** : sylea.ai.assistance@gmail.com
- **GitHub** : [Clotilde563/Sylea-AI](https://github.com/Clotilde563/Sylea-AI)

---

## 📄 Licence

Ce projet est sous licence propriétaire. Tous droits réservés © 2026 Syléa.AI

---

*Développé avec ❤️ et beaucoup de ☕*
