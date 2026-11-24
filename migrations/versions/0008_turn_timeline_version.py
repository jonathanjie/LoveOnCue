"""Deputy memory: each reply keeps the run-sheet version it was written under."""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_turns", sa.Column("timeline_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_turns", "timeline_version")
