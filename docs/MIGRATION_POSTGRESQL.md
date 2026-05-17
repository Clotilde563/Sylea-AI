# Migration SQLite → PostgreSQL

## État actuel (Phase 1 + Phase 2 partielle complètes — 2026-05-12)

### Phase 2 : PostgreSQL provisionné et opérationnel ✅

- **PG 16.4 installé** en mode portable : `C:\Users\busin\OneDrive\Documents\Sylea_pg\`
- **Serveur démarré** sur `localhost:5433` (DB : `sylea_prod`, user : `sylea`, mot de passe : `sylea_dev_pass`)
- **Schema créé** via Alembic (migration `4d6ae351e623_initial_pg_schema`) : 10 tables + 10 indexes
- **Données migrées** depuis SQLite : **500 rows sur 10 tables**, counts 100% identiques
- **Tests E2E passés** : connection asyncpg + SQLAlchemy async + EXPLAIN ANALYZE indexé
- **App tourne toujours sur SQLite** : aucune régression (DATABASE_URL n'est pas activé dans `.env`)

### Commandes pratiques

```powershell
# Demarrer PG
& "C:\Users\busin\OneDrive\Documents\Sylea_pg\pgsql\bin\pg_ctl.exe" `
  -D "C:\Users\busin\OneDrive\Documents\Sylea_pg\data" `
  -l "C:\Users\busin\OneDrive\Documents\Sylea_pg\pg.log" `
  -o "-p 5433" start

# Arreter PG
& "C:\Users\busin\OneDrive\Documents\Sylea_pg\pgsql\bin\pg_ctl.exe" `
  -D "C:\Users\busin\OneDrive\Documents\Sylea_pg\data" stop

# Connexion psql (interactif)
$env:PGPASSWORD = "sylea_dev_pass"
& "C:\Users\busin\OneDrive\Documents\Sylea_pg\pgsql\bin\psql.exe" `
  -h localhost -p 5433 -U sylea -d sylea_prod

# Smoke test depuis Python
$env:DATABASE_URL = "postgresql+asyncpg://sylea:sylea_dev_pass@localhost:5433/sylea_prod"
python scripts/test_pg_connection.py

# Re-migrer les donnees (idempotent : TRUNCATE + reimport)
python scripts/migrate_sqlite_to_pg.py
```

## Pour activer PostgreSQL dans l'app (Phase 2 finale)

### 1. Décommenter dans `.env`

```
DATABASE_URL=postgresql+asyncpg://sylea:sylea_dev_pass@localhost:5433/sylea_prod
```

### 2. Réécrire les routers (l'étape qui reste, ~10 jours)

Actuellement, tous les routers utilisent `DatabaseManager.conn.execute(...)` qui parle directement à SQLite. Pour activer PG, il faut migrer chaque router vers SQLAlchemy. Ordre suggéré (du moins critique au plus critique) :

1. `historique.py` — endpoints lecture
2. `profil.py` — CRUD profil
3. `bilan.py` — bilan quotidien
4. `objectifs.py` — tâches
5. `dilemme.py` — analyse choix (avec invariant SO)
6. `evenement.py` — événements (avec invariant SO)
7. `agent_companion.py` — chat Agent 1
8. `agent_assistant.py` — chat Agent 2

Pour chaque router, **2 approches possibles** :

**Approche A — Migrer vers SQLAlchemy ORM (recommandé long-terme)** :
```python
# Avant (raw SQL)
row = db.conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

# Après (SQLAlchemy)
from api.database.models import User
result = await session.execute(select(User).where(User.email == email))
user = result.scalar_one_or_none()
```

**Approche B — Couche d'adaptation avec text()** (rapide) :
```python
from sqlalchemy import text
result = await session.execute(
    text("SELECT * FROM users WHERE email = :email"), {"email": email}
)
row = result.mappings().first()
```

Approche B garde le SQL raw mais utilise SQLAlchemy async. **Pas de réécriture massive nécessaire** — juste changer `?` en `:nom`. Plus rapide à migrer, plus risqué long-terme.

## État actuel (Phase 1 complète)

### Ce qui est fait
- ✅ Libs installées : `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `aiosqlite`
- ✅ Optimisations SQLite : WAL mode, busy_timeout 5s, cache 64MB, mmap 256MB, synchronous=NORMAL
- ✅ Indexes critiques sur toutes les colonnes `auth_user_id`/`user_id`/`created_at`
- ✅ Audit isolation : 2 findings corrigés en defense-in-depth (`pending_actions` UPDATE)
- ✅ Couche d'abstraction `api/database/` : engine factory PG/SQLite via `DATABASE_URL`
- ✅ Modèles SQLAlchemy ORM (mirror du schema actuel)
- ✅ Alembic configuré, migration initiale stampée

### Ce qui n'est PAS fait (Phase 2+)
- ❌ Réécriture des 50+ raw queries (`db.conn.execute`) vers SQLAlchemy ORM
- ❌ PostgreSQL serveur installé/configuré
- ❌ Migration des données SQLite → PG
- ❌ Read replicas configurés
- ❌ Load test 50+ users concurrents

## Procédure de migration vers PostgreSQL (Phase 2)

### 1. Installer PostgreSQL serveur

**Windows** : télécharger l'installer depuis https://www.postgresql.org/download/windows/

**Linux** : `sudo apt install postgresql-15 postgresql-contrib-15`

**Docker (recommandé pour dev/test)** :
```bash
docker run -d --name sylea-pg \
  -e POSTGRES_USER=sylea \
  -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=sylea_prod \
  -p 5432:5432 \
  postgres:15
```

### 2. Configurer DATABASE_URL

Dans `.env` :
```bash
DATABASE_URL=postgresql+asyncpg://sylea:changeme@localhost:5432/sylea_prod
# Optionnel : read replica pour scale lecture
DATABASE_URL_READ=postgresql+asyncpg://sylea_ro:changeme@replica:5432/sylea_prod
```

### 3. Installer le driver psycopg2 pour Alembic
```bash
pip install psycopg2-binary
```
(Alembic utilise les drivers sync — asyncpg est seulement pour FastAPI runtime.)

### 4. Créer le schema PG

```bash
# Generer la migration complete depuis nos modeles
alembic revision --autogenerate -m "fresh_pg_schema"

# Verifier le fichier généré dans alembic/versions/
# Editer si besoin (ex: ajouter UNIQUE, CHECK constraints PG-specifiques)

# Appliquer
alembic upgrade head
```

### 5. Migrer les données depuis SQLite

Créer `scripts/migrate_sqlite_to_pg.py` :

```python
import asyncio
import sqlite3
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

SQLITE_PATH = "data/sylea.db"
PG_URL = os.environ["DATABASE_URL"]

# Tables dans l'ordre des dependances (FK first)
TABLES_ORDER = [
    "users",
    "profil_utilisateur",
    "sous_objectifs",
    "decisions",
    "bilans_quotidiens",
    "taches_quotidiennes",
    "agent_messages",
    "agent2_messages",
    "agent_collected_info",
    "agent_proposals",
    "user_plans",
    "user_quota_usage",
    "pending_actions",
    "agent3_memory",
]

async def migrate():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    pg_engine = create_async_engine(PG_URL)
    
    async with pg_engine.begin() as pg:
        for table in TABLES_ORDER:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  {table}: 0 rows (skip)")
                continue
            cols = rows[0].keys()
            cols_str = ", ".join(cols)
            placeholders = ", ".join([f":{c}" for c in cols])
            sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
            for row in rows:
                await pg.execute(text(sql), dict(row))
            print(f"  {table}: {len(rows)} rows migrated")

asyncio.run(migrate())
```

Lancer :
```bash
python scripts/migrate_sqlite_to_pg.py
```

### 6. Réécrire progressivement les raw queries

L'application actuelle utilise `db.conn.execute(...)` partout. Pour migrer progressivement :

**Avant** (compatible SQLite + PG via syntaxe `?`) :
```python
row = db.conn.execute(
    "SELECT * FROM users WHERE email = ?", (email,)
).fetchone()
```

**Après PG** (SQLAlchemy ORM, async) :
```python
from sqlalchemy import select
from api.database.models import User

result = await session.execute(
    select(User).where(User.email == email)
)
user = result.scalar_one_or_none()
```

Stratégie de migration **graduelle** :
1. Garder l'API actuelle (raw SQL) qui marche aussi sur PG (modulo quelques fixes : `?` → `%s` sur PG, ou utiliser SQLAlchemy `text()` qui supporte les deux).
2. Migrer les routers un par un vers SQLAlchemy : commencer par les moins critiques (stats), terminer par les plus critiques (agent chat, decisions).
3. Pour chaque router migré : tests E2E avant merge.

### 7. Setup Read Replicas (scale lecture)

PostgreSQL streaming replication :

```bash
# Sur le primary postgresql.conf
wal_level = replica
max_wal_senders = 3

# Sur la replica
hot_standby = on
primary_conninfo = 'host=primary user=replication password=...'
```

Dans Sylea, définir `DATABASE_URL_READ` pour pointer sur la replica. Utiliser :

```python
from api.database.engine import get_engine_read

# Pour les SELECT pure
async with get_engine_read().connect() as conn:
    result = await conn.execute(select(...))
```

### 8. Load test 50+ users concurrents

Utiliser `locust` ou `k6` :

```python
# locustfile.py
from locust import HttpUser, task, between

class SyleaUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def get_dashboard(self):
        self.client.get("/api/profil", headers={"Authorization": "Bearer ..."})

    @task
    def post_event(self):
        self.client.post("/api/evenement/analyser", json={...})
```

```bash
locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=5
```

Cibles :
- p95 latency < 500ms sur GET /api/profil
- p95 latency < 2s sur POST /api/dilemme/choisir (LLM call)
- 0% erreur 5xx

## Différences SQL SQLite ↔ PostgreSQL à gérer

| SQLite | PostgreSQL | Action |
|---|---|---|
| `?` placeholders | `%s` ou `$1` | SQLAlchemy `text()` gère les deux automatiquement |
| `AUTOINCREMENT` | `SERIAL`/`IDENTITY` | Modèles ORM utilisent `Integer, primary_key=True, autoincrement=True` |
| Pas de type `BOOLEAN` strict | `BOOLEAN` | Stocker en INT 0/1 partout (déjà fait) |
| `datetime('now')` | `now()` | Utiliser `func.now()` SQLAlchemy |
| `LIKE` case-sensitive | `LIKE` case-sensitive (utiliser `ILIKE`) | Utiliser SQLAlchemy `ilike` qui mappe correctement |
| Pas de `SCHEMA` | `public.table_name` | Pas de prefix needed |
| `IF NOT EXISTS` en `CREATE INDEX` | OK | Compatible |
| `STRFTIME` | `to_char()` | Faire les calculs côté Python plutôt qu'en SQL |

## Tests à passer avant production

- [ ] `pytest tests/` : 88/88 passent en PostgreSQL
- [ ] Test E2E manuel : signup → wizard → analyse dilemme → suppression
- [ ] Load test 50 users concurrents : 0% erreur 5xx
- [ ] Backup/restore PG : `pg_dump` puis `psql -f` 
- [ ] Failover replica → primary (si replica configurée)
- [ ] Migration data : count rows SQLite == count rows PG pour chaque table

## Rollback plan

Si la migration PG pose problème :
1. Stop FastAPI
2. Restaurer `DATABASE_URL` vers SQLite dans `.env`
3. Redémarrer FastAPI
4. SQLite est gardé intact pendant la migration → 0 perte de donnée

## Estimation effort restant (Phase 2)

- Réécriture raw queries → SQLAlchemy : 5-7 jours (350 endpoints / 50 raw queries)
- Setup PG + Alembic en prod : 0.5 jour
- Migration données : 0.5 jour
- Read replicas + load test : 2 jours
- Tests E2E + fix régressions : 2-3 jours
- **Total : ~10-12 jours**
