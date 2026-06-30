"""revoked tokens

Adds the ``revoked_tokens`` table backing logout-driven session-token
invalidation (Req 2.5) and the failed-invalidation retry record (Req 2.6),
plus its ``revocation_status`` ENUM type.

Revision ID: 0002_revoked_tokens
Revises: 0001_initial_schema
Create Date: 2024-01-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_revoked_tokens"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

revocation_status = postgresql.ENUM(
    "revoked", "retry_pending", name="revocation_status", create_type=False
)

def upgrade() -> None:
    bind = op.get_bind()
    revocation_status.create(bind, checkfirst=True)

    op.create_table(
        "revoked_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("status", revocation_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True)
    op.create_index(
        "ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"]
    )

def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    revocation_status.drop(bind, checkfirst=True)
