"""add plan lifecycle foundation

Revision ID: 7f3b91c4a2de
Revises: 38c339b891cc
Create Date: 2026-09-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7f3b91c4a2de"
down_revision: str | Sequence[str] | None = "38c339b891cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema without rewriting existing migration history."""
    bind = op.get_bind()
    approval_status = postgresql.ENUM(
        "PENDING", "APPROVED", "REJECTED", name="approval_status"
    )
    approval_status.create(bind, checkfirst=True)
    request_status = postgresql.ENUM(
        "NOT_SENT",
        "SENT",
        "ON_THE_WAY",
        "IN_PROGRESS",
        "DONE",
        "CANCELLED",
        "OVERDUE",
        name="request_status",
    )
    request_status.create(bind, checkfirst=True)

    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE plan_kind RENAME VALUE 'MANUAL_REPLAN' TO 'REPLAN'")
        op.execute(
            "ALTER TYPE replanning_event_type ADD VALUE IF NOT EXISTS 'ENGINEER_AVAILABLE'"
        )

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM plan WHERE is_baseline) THEN
                    RAISE EXCEPTION
                        'Legacy baseline plans require explicit initial-plan mapping before migration';
                END IF;
            END
            $$
            """
        )
    )

    op.drop_constraint("ck_plan_event_replan_has_event", "plan", type_="check")
    op.add_column("plan", sa.Column("planning_date", sa.Date(), nullable=True))
    op.add_column(
        "plan",
        sa.Column(
            "approval_status",
            approval_status,
            server_default="APPROVED",
            nullable=False,
        ),
    )
    op.add_column("plan", sa.Column("calculation_cutoff_at", sa.DateTime(), nullable=True))
    op.add_column("plan", sa.Column("assigned_requests_count", sa.Integer(), nullable=True))
    op.add_column("plan", sa.Column("unassigned_requests_count", sa.Integer(), nullable=True))
    op.add_column("plan", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("plan", sa.Column("rejected_at", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE plan
            SET planning_date = COALESCE(
                    (
                        SELECT min(request.window_start)::date
                        FROM request
                        WHERE request.upload_id = plan.upload_id
                    ),
                    created_at::date
                ),
                calculation_cutoff_at = created_at,
                assigned_requests_count = (
                    SELECT count(*) FROM planstop WHERE planstop.plan_id = plan.id
                ),
                unassigned_requests_count = (
                    SELECT count(*) FROM planunassignedrequest
                    WHERE planunassignedrequest.plan_id = plan.id
                ),
                approved_at = created_at
            """
        )
    )
    op.alter_column("plan", "planning_date", existing_type=sa.Date(), nullable=False)
    op.alter_column(
        "plan", "calculation_cutoff_at", existing_type=sa.DateTime(), nullable=False
    )
    op.alter_column(
        "plan", "assigned_requests_count", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "plan", "unassigned_requests_count", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column("plan", "approval_status", server_default=None)
    op.drop_column("plan", "is_baseline")
    op.create_check_constraint(
        "ck_plan_kind_links",
        "plan",
        "(kind = 'INITIAL' AND based_on_plan_id IS NULL AND triggered_by_event_id IS NULL) "
        "OR (kind = 'REPLAN' AND based_on_plan_id IS NOT NULL "
        "AND triggered_by_event_id IS NULL) "
        "OR (kind = 'EVENT_REPLAN' AND based_on_plan_id IS NOT NULL "
        "AND triggered_by_event_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_plan_approval_timestamps",
        "plan",
        "(approval_status = 'PENDING' AND approved_at IS NULL AND rejected_at IS NULL) "
        "OR (approval_status = 'APPROVED' AND approved_at IS NOT NULL "
        "AND rejected_at IS NULL) "
        "OR (approval_status = 'REJECTED' AND rejected_at IS NOT NULL "
        "AND approved_at IS NULL)",
    )
    op.create_unique_constraint(
        "uq_plan_triggered_by_event_id", "plan", ["triggered_by_event_id"]
    )
    op.drop_constraint("plan_based_on_plan_id_fkey", "plan", type_="foreignkey")
    op.drop_constraint("plan_triggered_by_event_id_fkey", "plan", type_="foreignkey")
    op.create_foreign_key(
        "plan_based_on_plan_id_fkey",
        "plan",
        "plan",
        ["based_on_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "plan_triggered_by_event_id_fkey",
        "plan",
        "replanningevent",
        ["triggered_by_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "request",
        sa.Column(
            "status", request_status, server_default="NOT_SENT", nullable=False
        ),
    )
    op.alter_column("request", "status", server_default=None)
    op.drop_constraint("request_external_id_key", "request", type_="unique")
    op.create_unique_constraint(
        "uq_request_upload_external_id", "request", ["upload_id", "external_id"]
    )

    op.add_column(
        "engineer",
        sa.Column("is_available", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.alter_column("engineer", "is_available", server_default=None)

    op.drop_constraint("ck_replanning_event_target", "replanningevent", type_="check")
    op.add_column("replanningevent", sa.Column("planning_date", sa.Date(), nullable=True))
    op.add_column(
        "replanningevent",
        sa.Column(
            "approval_status",
            approval_status,
            server_default="APPROVED",
            nullable=False,
        ),
    )
    op.add_column("replanningevent", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("replanningevent", sa.Column("rejected_at", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE replanningevent
            SET planning_date = created_at::date,
                approved_at = created_at
            """
        )
    )
    op.alter_column(
        "replanningevent", "planning_date", existing_type=sa.Date(), nullable=False
    )
    op.alter_column("replanningevent", "approval_status", server_default=None)
    op.create_check_constraint(
        "ck_replanning_event_target",
        "replanningevent",
        "(event_type IN ('URGENT_REQUEST', 'REQUEST_CANCELLED') "
        "AND request_id IS NOT NULL AND engineer_id IS NULL) "
        "OR (event_type IN ('ENGINEER_UNAVAILABLE', 'ENGINEER_AVAILABLE') "
        "AND engineer_id IS NOT NULL AND request_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_replanning_event_approval_timestamps",
        "replanningevent",
        "(approval_status = 'PENDING' AND approved_at IS NULL AND rejected_at IS NULL) "
        "OR (approval_status = 'APPROVED' AND approved_at IS NOT NULL "
        "AND rejected_at IS NULL) "
        "OR (approval_status = 'REJECTED' AND rejected_at IS NOT NULL "
        "AND approved_at IS NULL)",
    )
    op.create_index(
        "uq_replanning_event_pending_region_date",
        "replanningevent",
        ["region", "planning_date"],
        unique=True,
        postgresql_where=sa.text("approval_status = 'PENDING'"),
    )
    op.drop_constraint(
        "replanningevent_request_id_fkey", "replanningevent", type_="foreignkey"
    )
    op.drop_constraint(
        "replanningevent_engineer_id_fkey", "replanningevent", type_="foreignkey"
    )
    op.create_foreign_key(
        "replanningevent_request_id_fkey",
        "replanningevent",
        "request",
        ["request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "replanningevent_engineer_id_fkey",
        "replanningevent",
        "engineer",
        ["engineer_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "baselineresult",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_requests_count", sa.Integer(), nullable=False),
        sa.Column("unassigned_requests_count", sa.Integer(), nullable=False),
        sa.Column("engineers_used_count", sa.SmallInteger(), nullable=False),
        sa.Column("total_mileage_km", sa.Numeric(9, 2), nullable=False),
        sa.Column("average_workload_with_travel", sa.Numeric(7, 2), nullable=False),
        sa.Column("average_workload_without_travel", sa.Numeric(7, 2), nullable=False),
        sa.Column("algorithm_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["initial_plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("initial_plan_id"),
    )
    op.create_table(
        "planengineerstate",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engineer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineer.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("plan_id", "engineer_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO planengineerstate (plan_id, engineer_id, is_available)
            SELECT plan.id, engineer.id, engineer.is_available
            FROM plan
            JOIN engineer ON engineer.upload_id = plan.upload_id
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION ensure_baseline_initial() RETURNS trigger AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM plan
                    WHERE id = NEW.initial_plan_id AND kind = 'INITIAL'
                ) THEN
                    RAISE EXCEPTION 'baseline result must reference an initial plan';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ck_baseline_result_initial "
        "AFTER INSERT OR UPDATE OF initial_plan_id ON baselineresult "
        "DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW "
        "EXECUTE FUNCTION ensure_baseline_initial()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION ensure_plan_links_consistent() RETURNS trigger AS $$
            DECLARE
                linked_region region;
                linked_date date;
            BEGIN
                IF NEW.based_on_plan_id IS NOT NULL THEN
                    SELECT region, planning_date INTO linked_region, linked_date
                    FROM plan WHERE id = NEW.based_on_plan_id;
                    IF linked_region IS DISTINCT FROM NEW.region
                        OR linked_date IS DISTINCT FROM NEW.planning_date THEN
                        RAISE EXCEPTION 'base plan must have the same region and planning date';
                    END IF;
                END IF;
                IF NEW.triggered_by_event_id IS NOT NULL THEN
                    SELECT region, planning_date INTO linked_region, linked_date
                    FROM replanningevent WHERE id = NEW.triggered_by_event_id;
                    IF linked_region IS DISTINCT FROM NEW.region
                        OR linked_date IS DISTINCT FROM NEW.planning_date THEN
                        RAISE EXCEPTION 'event must have the same region and planning date';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ck_plan_links_consistent "
        "AFTER INSERT OR UPDATE OF region, planning_date, based_on_plan_id, "
        "triggered_by_event_id ON plan DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW "
        "EXECUTE FUNCTION ensure_plan_links_consistent()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION prevent_plan_source_changes() RETURNS trigger AS $$
            BEGIN
                IF OLD.upload_id IS DISTINCT FROM NEW.upload_id
                    OR OLD.based_on_plan_id IS DISTINCT FROM NEW.based_on_plan_id
                    OR OLD.triggered_by_event_id IS DISTINCT FROM NEW.triggered_by_event_id THEN
                    RAISE EXCEPTION 'plan source references are immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        "CREATE TRIGGER ck_plan_source_references_immutable "
        "BEFORE UPDATE OF upload_id, based_on_plan_id, triggered_by_event_id ON plan "
        "FOR EACH ROW EXECUTE FUNCTION prevent_plan_source_changes()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION ensure_plan_request_exclusive() RETURNS trigger AS $$
            BEGIN
                PERFORM 1 FROM plan WHERE id = NEW.plan_id FOR UPDATE;
                IF TG_TABLE_NAME = 'planstop' AND EXISTS (
                    SELECT 1 FROM planunassignedrequest
                    WHERE plan_id = NEW.plan_id AND request_id = NEW.request_id
                ) THEN
                    RAISE EXCEPTION 'request is both assigned and unassigned in plan';
                ELSIF TG_TABLE_NAME = 'planunassignedrequest' AND EXISTS (
                    SELECT 1 FROM planstop
                    WHERE plan_id = NEW.plan_id AND request_id = NEW.request_id
                ) THEN
                    RAISE EXCEPTION 'request is both assigned and unassigned in plan';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ck_plan_stop_request_exclusive "
        "AFTER INSERT OR UPDATE OF plan_id, request_id ON planstop "
        "DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW "
        "EXECUTE FUNCTION ensure_plan_request_exclusive()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ck_plan_unassigned_request_exclusive "
        "AFTER INSERT OR UPDATE OF plan_id, request_id ON planunassignedrequest "
        "DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW "
        "EXECUTE FUNCTION ensure_plan_request_exclusive()"
    )


def downgrade() -> None:
    """Refuse a lossy downgrade of lifecycle and scoped identity data."""
    raise NotImplementedError("Downgrade would irreversibly discard plan lifecycle data")
