"""Deputy trust: draft links in memory, run-sheet notes, emergency contact, update chasing, digest items."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_turns", sa.Column("draft_id", sa.String(length=64), nullable=True))
    op.add_column("timeline_items", sa.Column("change_note", sa.Text(), nullable=False, server_default=""))
    op.add_column("weddings", sa.Column("emergency_contact", sa.String(length=200), nullable=False, server_default=""))
    op.add_column("deputy_pings", sa.Column("notification_id", sa.String(length=64), nullable=True))
    op.create_table(
        "digest_items",
        sa.Column("subject", sa.String(length=120), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("wedding_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["wedding_id"], ["weddings.id"], name=op.f("fk_digest_items_wedding_id_weddings")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_digest_items")),
        sa.UniqueConstraint("wedding_id", "id", name=op.f("uq_digest_items_wedding_id_id")),
    )
    op.create_index(op.f("ix_digest_items_wedding_id"), "digest_items", ["wedding_id"])
    op.create_index("ix_digest_items_subject", "digest_items", ["wedding_id", "subject", "reported_at"])


def downgrade() -> None:
    op.drop_index("ix_digest_items_subject", table_name="digest_items")
    op.drop_index(op.f("ix_digest_items_wedding_id"), table_name="digest_items")
    op.drop_table("digest_items")
    op.drop_column("deputy_pings", "notification_id")
    op.drop_column("weddings", "emergency_contact")
    op.drop_column("timeline_items", "change_note")
    op.drop_column("conversation_turns", "draft_id")
