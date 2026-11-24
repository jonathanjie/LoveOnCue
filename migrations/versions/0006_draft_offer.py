"""Draft offers: mark drafts offered as a one-tap button (a question, an addition, an Undo)."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_drafts", sa.Column("offer", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("action_drafts", "offer")
