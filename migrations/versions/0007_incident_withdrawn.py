"""Incidents: a report the reporter took back is "withdrawn", not "resolved"."""
import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

OLD_STATUSES = "status IN ('open','resolved')"
NEW_STATUSES = "status IN ('open','resolved','withdrawn')"


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch:
        batch.drop_constraint(op.f("ck_incidents_status"), type_="check")
        batch.create_check_constraint("status", NEW_STATUSES)
    # Earlier releases stored a withdrawal as resolved. Each one left a report_withdrawn audit
    # event naming the confirmed draft, and that draft's receipt names the incident it created.
    bind = op.get_bind()
    withdrawals = bind.execute(sa.text(
        "SELECT wedding_id, actor_id, entity_id FROM audit_events WHERE event_type = 'report_withdrawn'")).all()
    for wedding_id, actor_id, request_id in withdrawals:
        result = bind.execute(sa.text(
            "SELECT result FROM command_receipts WHERE wedding_id = :w AND actor_id = :a AND request_id = :r"),
            {"w": wedding_id, "a": actor_id, "r": request_id}).scalar()
        result = json.loads(result) if isinstance(result, str) else (result or {})
        if "changed" in result or not result.get("id"):
            continue  # an arrival, which is not an incident
        bind.execute(sa.text("UPDATE incidents SET status = 'withdrawn' "
                             "WHERE wedding_id = :w AND id = :i AND status = 'resolved'"),
                     {"w": wedding_id, "i": result["id"]})


def downgrade() -> None:
    # Older releases cannot read the new status; they recorded a withdrawal as resolved.
    op.execute("UPDATE incidents SET status = 'resolved' WHERE status = 'withdrawn'")
    with op.batch_alter_table("incidents") as batch:
        batch.drop_constraint(op.f("ck_incidents_status"), type_="check")
        batch.create_check_constraint("status", OLD_STATUSES)
