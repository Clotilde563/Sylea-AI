"""users — token revocation (tokens_invalidated_before)

Revision ID: d4f1a8b2e6c9
Revises: c3e0f7d9a2b8
Create Date: 2026-06-02 10:00:00.000000

Phase 1 sécurité (2026-06) : ajoute users.tokens_invalidated_before pour
permettre la RÉVOCATION des JWT. Avant, un token volé restait valide 7 jours
sans aucun moyen de le révoquer (sauf rotation du secret = logout global).

Mécanisme :
  - create_access_token ajoute un claim `iat` (issued-at)
  - POST /api/auth/logout pose tokens_invalidated_before = now()
  - get_optional_user rejette (401) tout token dont iat < tokens_invalidated_before

Nullable + DEFAULT NULL : backward compat (les tokens existants restent
valides tant qu'aucun logout n'a été fait).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f1a8b2e6c9"
down_revision: Union[str, Sequence[str], None] = "c3e0f7d9a2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tokens_invalidated_before", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tokens_invalidated_before")
