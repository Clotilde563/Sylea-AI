"""dilemmes_tracking — nouvelle table pour le mode de suivi de decisions

Revision ID: b2f9e8a4c1d3
Revises: 4d6ae351e623
Create Date: 2026-05-26 12:00:00.000000

Voir api/dilemmes_tracking.py pour le contexte fonctionnel. Cette
migration cree la table `dilemmes_tracking` + 2 indexes :
  - idx_tracking_user      : (user_id, status)        pour les listings
  - idx_tracking_next_notif: (next_notif_at) WHERE    pour le scheduler
                             status = 'tracking'

L'index partiel n'est pas supporte par SQLite < 3.8 ; on n'a donc pas a
le replicer ici, Alembic ne tourne qu'en PG (cf. api/main.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2f9e8a4c1d3"
down_revision: Union[str, Sequence[str], None] = "4d6ae351e623"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — cree la table dilemmes_tracking + indexes."""
    op.create_table(
        "dilemmes_tracking",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("etude_scientifique", sa.Text(), nullable=True),
        sa.Column("impact_temporel_jours", sa.Integer(), nullable=False),
        sa.Column("nb_periodes", sa.Integer(), nullable=False),
        sa.Column(
            "device_tz",
            sa.String(),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
        sa.Column(
            "choices_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'tracking'"),
        ),
        sa.Column("impact_final_jours", sa.Float(), nullable=True),
        sa.Column("impact_final_probabilite", sa.Float(), nullable=True),
        sa.Column("so_impactes_json", sa.Text(), nullable=True),
        sa.Column("cancellation_mode", sa.String(), nullable=True),
        sa.Column("next_notif_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("validated_at", sa.String(), nullable=True),
        sa.Column("cancelled_at", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tracking_user",
        "dilemmes_tracking",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_tracking_next_notif",
        "dilemmes_tracking",
        ["next_notif_at"],
        unique=False,
        postgresql_where=sa.text("status = 'tracking'"),
    )


def downgrade() -> None:
    """Downgrade schema — drop indexes + table."""
    op.drop_index("idx_tracking_next_notif", table_name="dilemmes_tracking")
    op.drop_index("idx_tracking_user", table_name="dilemmes_tracking")
    op.drop_table("dilemmes_tracking")
