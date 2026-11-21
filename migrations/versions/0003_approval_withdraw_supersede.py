"""Allow approvals to be withdrawn by the reporter or superseded by a newer report."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

OLD_STATUSES = "status IN ('pending','approved','rejected','expired')"
NEW_STATUSES = "status IN ('pending','approved','rejected','expired','withdrawn','superseded')"


def upgrade() -> None:
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint(op.f("ck_approvals_status"), type_="check")
        batch.create_check_constraint("status", NEW_STATUSES)


def downgrade() -> None:
    # Older releases cannot read the new statuses; record them as expired first.
    op.execute("UPDATE approvals SET status = 'expired' WHERE status IN ('withdrawn', 'superseded')")
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint(op.f("ck_approvals_status"), type_="check")
        batch.create_check_constraint("status", OLD_STATUSES)
