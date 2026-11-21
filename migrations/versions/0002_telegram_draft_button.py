"""Keep a report draft reference with its queued Telegram reply."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("telegram_draft_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "telegram_draft_id")
