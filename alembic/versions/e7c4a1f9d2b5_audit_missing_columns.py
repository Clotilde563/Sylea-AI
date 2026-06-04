"""audit 2026-06 — colonnes manquantes (decisions.impact_temporel_jours, users.is_admin/disabled_at)

Revision ID: e7c4a1f9d2b5
Revises: d4f1a8b2e6c9
Create Date: 2026-06-04 00:00:00.000000

Audit securite/coherence (2026-06). Ces colonnes etaient creees UNIQUEMENT par
des ALTER runtime cote SQLite (dev) mais ABSENTES d'Alembic -> en prod
PostgreSQL (ou seul `alembic upgrade head` tourne au boot) elles n'existaient
jamais :

  - decisions.impact_temporel_jours : lue par POST /api/dilemme/choisir
    (chemin anti-doublon, declenche des impact > 0). Sans elle, le 2e dilemme a
    impact temporel levait un 500 (UndefinedColumn) EN PROD uniquement.
  - users.is_admin / users.disabled_at : sans elles, le check de compte
    desactive (get_optional_user) etait inoperant en prod (fail-open).

Strictement ADDITIF / backward-compat : colonnes NULLABLE ou DEFAULT -> les
lignes existantes prennent NULL / 0. IDEMPOTENT : on verifie l'existence avant
d'ajouter (sur-sur si une colonne a deja ete creee a la main).

Types alignes sur les ALTER runtime SQLite pour cohérence dev/prod :
  is_admin = INTEGER (le code fait `WHERE is_admin = 1` / `SET is_admin = 1` :
  un Boolean PG ferait echouer ces comparaisons int).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c4a1f9d2b5"
down_revision: Union[str, Sequence[str], None] = "d4f1a8b2e6c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    """Colonnes existantes de `table` (set vide si table absente)."""
    try:
        insp = sa.inspect(op.get_bind())
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    if "impact_temporel_jours" not in _columns("decisions"):
        op.add_column(
            "decisions",
            sa.Column("impact_temporel_jours", sa.Float(), nullable=True),
        )

    usr = _columns("users")
    if "is_admin" not in usr:
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Integer(), nullable=False, server_default="0"),
        )
    if "disabled_at" not in usr:
        op.add_column(
            "users",
            sa.Column("disabled_at", sa.String(), nullable=True),
        )


def downgrade() -> None:
    # Downgrade defensif (ne tourne qu'en rollback manuel explicite).
    for table, col in (
        ("decisions", "impact_temporel_jours"),
        ("users", "is_admin"),
        ("users", "disabled_at"),
    ):
        try:
            op.drop_column(table, col)
        except Exception:
            pass
