"""users — presence + engagement tracking

Revision ID: c3e0f7d9a2b8
Revises: b2f9e8a4c1d3
Create Date: 2026-05-31 22:00:00.000000

Fix bug "Agent companion hallucine 'X jours sans nouvelles' alors que
l'utilisateur est connecte" — ajout de 2 colonnes sur `users` :

  - `last_seen_at`    : touche par chaque requete HTTP authentifiee
                        (presence). Source primaire pour calculer
                        `hours_since_user` dans agent_companion.
  - `last_engaged_at` : touche par les requetes mutatives (POST/PUT/
                        DELETE) authentifiees. Source pour distinguer
                        "user juste connecte qui regarde" de "user qui
                        fait quelque chose".

Ces colonnes sont alimentees par `api/presence_middleware.py` avec un
debounce in-memory de 5 min (pour eviter de hammer la DB sur chaque
requete).

Nullable + DEFAULT NULL : backward compat avec les comptes existants
qui n'ont jamais ete vus depuis la mise en prod du middleware.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3e0f7d9a2b8"
down_revision: Union[str, Sequence[str], None] = "b2f9e8a4c1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — ajoute last_seen_at + last_engaged_at sur users."""
    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_engaged_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema — drop les 2 colonnes."""
    op.drop_column("users", "last_engaged_at")
    op.drop_column("users", "last_seen_at")
