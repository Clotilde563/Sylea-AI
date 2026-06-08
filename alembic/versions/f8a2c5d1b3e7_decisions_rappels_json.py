"""decisions.rappels_json — detail des rappels pour dilemmes issus du TRACKING

Revision ID: f8a2c5d1b3e7
Revises: e7c4a1f9d2b5
Create Date: 2026-06-07 00:00:00.000000

Feature (2026-06) : les dilemmes en mode TRACKING valides ou abandonnes sont
desormais enregistres dans l'historique des decisions (table `decisions`) avec
le detail periode-par-periode des rappels. Cette colonne stocke ce detail en
JSON :

  {"mode": "validated"|"abandoned", "nb_periodes": int, "nb_repondu": int,
   "periodes": [{"index": int, "label": str, "description": str,
                 "responded_at": str|None, "repondu": bool}, ...]}

NULL pour les decisions classiques (dilemme direct, action agent).

Strictement ADDITIF / backward-compat : colonne NULLABLE -> les lignes
existantes prennent NULL. IDEMPOTENT : on verifie l'existence avant d'ajouter
(la meme colonne est aussi creee par un ALTER runtime cote SQLite en dev).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a2c5d1b3e7"
down_revision: Union[str, Sequence[str], None] = "e7c4a1f9d2b5"
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
    if "rappels_json" not in _columns("decisions"):
        op.add_column(
            "decisions",
            sa.Column("rappels_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    # Downgrade defensif (ne tourne qu'en rollback manuel explicite).
    try:
        op.drop_column("decisions", "rappels_json")
    except Exception:
        pass
