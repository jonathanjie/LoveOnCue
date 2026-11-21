"""Deputy agent: conversation memory, pings, standing orders, opt-out."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("wedding_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant')", name=op.f("ck_conversation_turns_role")),
        sa.ForeignKeyConstraint(["wedding_id", "member_id"], ["members.wedding_id", "members.id"],
                                name=op.f("fk_conversation_turns_wedding_id_member_id_members")),
        sa.ForeignKeyConstraint(["wedding_id"], ["weddings.id"], name=op.f("fk_conversation_turns_wedding_id_weddings")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_turns")),
        sa.UniqueConstraint("wedding_id", "id", name=op.f("uq_conversation_turns_wedding_id_id")),
    )
    op.create_index(op.f("ix_conversation_turns_wedding_id"), "conversation_turns", ["wedding_id"])
    op.create_index("ix_conversation_turns_member", "conversation_turns", ["wedding_id", "member_id", "created_at"])
    op.create_table(
        "deputy_pings",
        sa.Column("recipient_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("wedding_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["wedding_id", "recipient_id"], ["members.wedding_id", "members.id"],
                                name=op.f("fk_deputy_pings_wedding_id_recipient_id_members")),
        sa.ForeignKeyConstraint(["wedding_id"], ["weddings.id"], name=op.f("fk_deputy_pings_wedding_id_weddings")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deputy_pings")),
        sa.UniqueConstraint("wedding_id", "id", name=op.f("uq_deputy_pings_wedding_id_id")),
    )
    op.create_index(op.f("ix_deputy_pings_wedding_id"), "deputy_pings", ["wedding_id"])
    op.create_index("ix_deputy_pings_recipient", "deputy_pings", ["wedding_id", "recipient_id", "created_at"])
    op.add_column("members", sa.Column("deputy_quiet", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("weddings", sa.Column("deputy_orders", sa.Text(), nullable=False, server_default=""))
    op.add_column("weddings", sa.Column("deputy_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("weddings", "deputy_enabled")
    op.drop_column("weddings", "deputy_orders")
    op.drop_column("members", "deputy_quiet")
    op.drop_index("ix_deputy_pings_recipient", table_name="deputy_pings")
    op.drop_index(op.f("ix_deputy_pings_wedding_id"), table_name="deputy_pings")
    op.drop_table("deputy_pings")
    op.drop_index("ix_conversation_turns_member", table_name="conversation_turns")
    op.drop_index(op.f("ix_conversation_turns_wedding_id"), table_name="conversation_turns")
    op.drop_table("conversation_turns")
