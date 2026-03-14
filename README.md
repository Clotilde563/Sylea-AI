# SYLÉA.AI — Votre assistant de vie augmenté

> *Chaque décision que vous prenez change la probabilité d'atteindre vos objectifs. Syléa.AI la rend visible.*

---

## Vision

Syléa.AI est un **assistant de vie augmenté** qui quantifie l'impact de vos décisions quotidiennes sur vos objectifs de vie à long terme.

Deux piliers :
1. **Le Conseiller prédictif** — Analyse vos dilemmes et recalcule votre probabilité de réussite après chaque choix.
2. **Le Double (agent exécutant)** — Prend en charge vos tâches déléguables pendant que vous faites autre chose.

---

## Installation

### Prérequis
- Python 3.11+
- pip

### Étapes

```bash
# 1. Cloner / ouvrir le dossier
cd "Documents/Syléa"

# 2. Créer un environnement virtuel (recommandé)
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configuration (optionnel — requis uniquement pour le mode Claude)
cp .env.example .env
# Ouvrir .env et renseigner votre ANTHROPIC_API_KEY
```

---

## Utilisation

### Lancer l'application

```bash
# Mode automatique (Claude si clé API disponible, sinon simulation)
python main.py

# Forcer le mode simulation locale (sans clé API)
python main.py --local

# Forcer le mode Claude complet (requiert ANTHROPIC_API_KEY dans .env)
python main.py --claude
```

### Script de démonstration

```bash
# Démonstration complète sans saisie utilisateur
python demo.py

# Avec affichage détaillé des rapports
python demo.py --complet
```

### Tests unitaires

```bash
# Lancer tous les tests
pytest tests/ -v

# Avec rapport de couverture
pytest tests/ -v --cov=sylea --cov-report=term-missing

# Un seul module
pytest tests/test_probability.py -v
```

---

## Architecture du projet

```
Syléa/
├── sylea/                          # Package principal
│   ├── config/
│   │   └── settings.py             # Configuration (chemins, constantes)
│   ├── core/
│   │   ├── models/
│   │   │   ├── user.py             # ProfilUtilisateur, Objectif
│   │   │   └── decision.py         # Decision, OptionDilemme, ActionAgent
│   │   ├── engine/
│   │   │   ├── probability.py      # Moteur de probabilité (déterministe)
│   │   │   └── analyzer.py         # Analyseur de dilemmes (règles)
│   │   └── storage/
│   │       ├── database.py         # Gestionnaire SQLite
│   │       └── repositories.py     # ProfilRepository, DecisionRepository
│   ├── agent/
│   │   ├── claude_agent.py         # Interface Claude API (mode avancé)
│   │   ├── validator.py            # Validation des instructions
│   │   ├── executor.py             # Orchestrateur agent
│   │   └── skills/
│   │       ├── email_skill.py      # Rédaction d'emails
│   │       ├── document_skill.py   # Structuration de documents
│   │       ├── research_skill.py   # Synthèse documentaire
│   │       ├── calendar_skill.py   # Planification
│   │       └── todo_skill.py       # Listes de tâches
│   └── interfaces/
│       └── cli/
│           ├── app.py              # Mode Claude complet
│           ├── main.py             # Mode simulation locale
│           ├── dashboard.py        # Affichage tableau de bord
│           ├── dilemma.py          # Flow de dilemme
│           ├── profile.py          # Wizard de profil
│           ├── components/ui.py    # Composants Rich réutilisables
│           └── screens/            # Écrans détaillés (mode Claude)
├── tests/
│   ├── test_models.py              # Tests des modèles de données
│   ├── test_probability.py         # Tests du moteur de probabilité
│   ├── test_validator.py           # Tests du validateur d'instructions
│   └── test_analyzer.py            # Tests de l'analyseur + agent
├── data/                           # Base de données SQLite (gitignorée)
├── main.py                         # Point d'entrée
├── demo.py                         # Script de démonstration
├── requirements.txt
└── .env.example
```

---

## Modes de fonctionnement

### Mode Simulation (sans API)

Entièrement local, aucune clé API requise.

- Probabilité calculée par un moteur déterministe (formule mathématique)
- Analyse des dilemmes par un système de règles (mots-clés + catégories)
- Toutes les fonctionnalités disponibles

### Mode Claude (avec API)

Requiert une clé API Anthropic dans `.env`.

- Analyse qualitative enrichie par Claude (points forts/faibles, conseil)
- Analyse de dilemme avec pros/cons détaillés et raisonnement nuancé
- Même moteur de probabilité déterministe (la probabilité ne change pas, seule l'explication change)

---

## Exemples d'utilisation

### Exemple 1 — Alex, entrepreneur ambitieux

```
Profil : 32 ans, entrepreneur tech, revenu 85k€, stress 8/10
Objectif : "Devenir milliardaire en 15 ans"
Probabilité initiale : ~0.7%

Dilemme : "Courir ou travailler sur mon business plan ce soir ?"
  → Courir      : +0.6% (santé, clarté mentale)
  → Travailler  : +2.8% (impact direct, déléguable)

Choix : Travailler → délégation à l'agent
Instruction : "Prépare les projections financières pour notre startup"
Nouvelle probabilité : ~3.5%
```

### Exemple 2 — Claire, athlète

```
Profil : 28 ans, coach sportive, santé 9/10, stress 3/10
Objectif : "Courir un marathon en 3h30"
Probabilité initiale : ~72%

Dilemme : "Séance fractionnée ou repos actif ?"
  → Fractionnée : +3.5% (spécifique objectif)
  → Repos actif : +1.8% (récupération)

Choix : Fractionnée
Nouvelle probabilité : ~75.5%
```

---

## Règles de l'agent exécutant

L'agent n'agit **jamais** sans :
1. ✅ Une instruction validée (≥ 4 mots, verbe d'action, pas de termes vagues)
2. ✅ Une confirmation explicite de l'utilisateur (opt-in à chaque fois)

### Instructions valides ✅
```
"Prépare le dossier client Dupont pour la réunion de demain matin"
"Rédige un email de relance pour le prospect Martin concernant le devis"
"Recherche les 5 principaux concurrents de notre marché e-commerce"
```

### Instructions invalides ❌
```
"Fais ça"                              → trop court, pas de verbe
"Prépare le truc pour le client"       → terme vague "truc"
"Travailler"                           → pas assez de contexte
```

---

## Configuration

Fichier `.env` (copie de `.env.example`) :

```env
# Clé API Anthropic (optionnel — mode Claude uniquement)
ANTHROPIC_API_KEY=sk-ant-votre-cle-api-ici

# Chemin vers la base de données SQLite
DATABASE_PATH=data/sylea.db

# Mode debug
DEBUG=False
```

---

## Technologies

| Bibliothèque | Usage |
|---|---|
| `rich` | Interface CLI colorée (tableaux, jauges, panels) |
| `sqlite3` | Persistance locale (intégré Python) |
| `python-dotenv` | Chargement du fichier `.env` |
| `anthropic` | API Claude (mode avancé uniquement) |
| `pytest` | Tests unitaires |
| `dataclasses` | Modèles de données (intégré Python) |

---

## Philosophie de conception

- **Trajectoire > chiffre** : Syléa met en avant la progression, pas la valeur absolue.
- **Opt-in systématique** : L'agent n'agit jamais sans votre confirmation explicite.
- **Local first** : Toutes vos données restent sur votre machine (SQLite).
- **Simulation fiable** : Le mode sans API reste pleinement utilisable et pertinent.
- **SOLID** : Architecture modulaire — chaque module a une responsabilité unique.
