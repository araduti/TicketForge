"""Initial schema – all 30 tables from DB_INIT_SQL.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# All CREATE TABLE statements are taken verbatim from the DB_INIT_SQL
# variable in main.py so that the Alembic history matches the schema that
# the application bootstraps on startup.
# ---------------------------------------------------------------------------

_TABLES_UP = [
    # 1. processed_tickets
    """
    CREATE TABLE IF NOT EXISTS processed_tickets (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        processed_at TEXT NOT NULL,
        category TEXT,
        priority TEXT,
        automation_score INTEGER,
        summary TEXT,
        sentiment TEXT DEFAULT 'neutral',
        detected_language TEXT DEFAULT 'en',
        ticket_status TEXT DEFAULT 'open',
        created_at TEXT DEFAULT NULL,
        updated_at TEXT DEFAULT NULL
    );
    """,
    # 2. ticket_history
    """
    CREATE TABLE IF NOT EXISTS ticket_history (
        rowid INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    # 3. audit_log
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        api_key_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        action TEXT NOT NULL,
        resource TEXT NOT NULL,
        status_code INTEGER NOT NULL DEFAULT 200,
        detail TEXT NOT NULL DEFAULT ''
    );
    """,
    # 4. kb_articles
    """
    CREATE TABLE IF NOT EXISTS kb_articles (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        tags TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # 5. csat_ratings
    """
    CREATE TABLE IF NOT EXISTS csat_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT NOT NULL,
        rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
        comment TEXT NOT NULL DEFAULT '',
        reporter_email TEXT NOT NULL DEFAULT '',
        submitted_at TEXT NOT NULL,
        UNIQUE(ticket_id)
    );
    """,
    # 6. scheduled_reports
    """
    CREATE TABLE IF NOT EXISTS scheduled_reports (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        frequency TEXT NOT NULL DEFAULT 'weekly',
        webhook_url TEXT NOT NULL,
        include_categories INTEGER NOT NULL DEFAULT 1,
        include_priorities INTEGER NOT NULL DEFAULT 1,
        include_sla INTEGER NOT NULL DEFAULT 1,
        include_csat INTEGER NOT NULL DEFAULT 1,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """,
    # 7. ticket_merges
    """
    CREATE TABLE IF NOT EXISTS ticket_merges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        primary_ticket_id TEXT NOT NULL,
        merged_ticket_id TEXT NOT NULL,
        merged_at TEXT NOT NULL,
        merged_by TEXT NOT NULL DEFAULT ''
    );
    """,
    # 8. custom_fields
    """
    CREATE TABLE IF NOT EXISTS custom_fields (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        field_type TEXT NOT NULL DEFAULT 'text',
        description TEXT NOT NULL DEFAULT '',
        required INTEGER NOT NULL DEFAULT 0,
        options TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    """,
    # 9. ticket_tags
    """
    CREATE TABLE IF NOT EXISTS ticket_tags (
        ticket_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (ticket_id, tag)
    );
    """,
    # 10. saved_filters
    """
    CREATE TABLE IF NOT EXISTS saved_filters (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        filter_criteria TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT ''
    );
    """,
    # 11. response_templates
    """
    CREATE TABLE IF NOT EXISTS response_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'en',
        tags TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    """,
    # 12. ticket_activity
    """
    CREATE TABLE IF NOT EXISTS ticket_activity (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL,
        activity_type TEXT NOT NULL DEFAULT 'comment',
        content TEXT NOT NULL DEFAULT '',
        performed_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    """,
    # 13. agent_skills
    """
    CREATE TABLE IF NOT EXISTS agent_skills (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        categories TEXT NOT NULL DEFAULT '[]',
        priorities TEXT NOT NULL DEFAULT '[]',
        languages TEXT NOT NULL DEFAULT '[]',
        max_concurrent_tickets INTEGER NOT NULL DEFAULT 10,
        created_at TEXT NOT NULL
    );
    """,
    # 14. automation_rules
    """
    CREATE TABLE IF NOT EXISTS automation_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        conditions TEXT NOT NULL DEFAULT '[]',
        actions TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """,
    # 15. ticket_approvals
    """
    CREATE TABLE IF NOT EXISTS ticket_approvals (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL,
        approver TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        decision_comment TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        decided_at TEXT
    );
    """,
    # 16. ticket_locks
    """
    CREATE TABLE IF NOT EXISTS ticket_locks (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL UNIQUE,
        agent_id TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    """,
    # 17. contacts
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        organisation TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    """,
    # 18. contact_tickets
    """
    CREATE TABLE IF NOT EXISTS contact_tickets (
        contact_id TEXT NOT NULL,
        ticket_id TEXT NOT NULL,
        PRIMARY KEY (contact_id, ticket_id)
    );
    """,
    # 19. macros
    """
    CREATE TABLE IF NOT EXISTS macros (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        actions TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    """,
    # 20. team_members
    """
    CREATE TABLE IF NOT EXISTS team_members (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        team_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TEXT NOT NULL,
        UNIQUE(agent_id, team_name)
    );
    """,
    # 21. sla_risk_thresholds
    """
    CREATE TABLE IF NOT EXISTS sla_risk_thresholds (
        id TEXT PRIMARY KEY,
        priority TEXT NOT NULL UNIQUE,
        warning_threshold REAL NOT NULL DEFAULT 0.5,
        critical_threshold REAL NOT NULL DEFAULT 0.8,
        created_at TEXT NOT NULL
    );
    """,
    # 22. custom_classifiers
    """
    CREATE TABLE IF NOT EXISTS custom_classifiers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        categories TEXT NOT NULL DEFAULT '[]',
        training_samples INTEGER NOT NULL DEFAULT 0,
        accuracy REAL NOT NULL DEFAULT 0.0,
        status TEXT NOT NULL DEFAULT 'untrained',
        created_at TEXT NOT NULL
    );
    """,
    # 23. classifier_training_data
    """
    CREATE TABLE IF NOT EXISTS classifier_training_data (
        id TEXT PRIMARY KEY,
        classifier_id TEXT NOT NULL,
        text TEXT NOT NULL,
        category TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    # 24. anomaly_rules
    """
    CREATE TABLE IF NOT EXISTS anomaly_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        metric TEXT NOT NULL,
        threshold REAL NOT NULL,
        window_hours INTEGER NOT NULL DEFAULT 24,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """,
    # 25. visual_workflows
    """
    CREATE TABLE IF NOT EXISTS visual_workflows (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        nodes TEXT NOT NULL DEFAULT '[]',
        edges TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    """,
    # 26. data_retention_policies
    """
    CREATE TABLE IF NOT EXISTS data_retention_policies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        retention_days INTEGER NOT NULL,
        action TEXT NOT NULL DEFAULT 'archive',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """,
    # 27. user_preferences
    """
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id TEXT PRIMARY KEY,
        theme TEXT NOT NULL DEFAULT 'light',
        language TEXT NOT NULL DEFAULT 'en',
        timezone TEXT NOT NULL DEFAULT 'UTC',
        notifications_enabled INTEGER NOT NULL DEFAULT 1,
        keyboard_shortcuts_enabled INTEGER NOT NULL DEFAULT 1,
        items_per_page INTEGER NOT NULL DEFAULT 25,
        accessibility_high_contrast INTEGER NOT NULL DEFAULT 0,
        accessibility_font_size TEXT NOT NULL DEFAULT 'medium',
        updated_at TEXT NOT NULL
    );
    """,
    # 28. onboarding_progress
    """
    CREATE TABLE IF NOT EXISTS onboarding_progress (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        step_id TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        UNIQUE(user_id, step_id)
    );
    """,
    # 29. troubleshooting_flows
    """
    CREATE TABLE IF NOT EXISTS troubleshooting_flows (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'general',
        steps TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    """,
    # 30. agent_profiles
    """
    CREATE TABLE IF NOT EXISTS agent_profiles (
        agent_id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        specialisations TEXT NOT NULL DEFAULT '[]',
        max_capacity INTEGER NOT NULL DEFAULT 10,
        current_load INTEGER NOT NULL DEFAULT 0,
        avg_resolution_hours REAL NOT NULL DEFAULT 0.0,
        avg_satisfaction REAL NOT NULL DEFAULT 0.0,
        categories TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    """,
]

# Reverse order for a clean teardown.
_TABLES_DOWN = [
    "agent_profiles",
    "troubleshooting_flows",
    "onboarding_progress",
    "user_preferences",
    "data_retention_policies",
    "visual_workflows",
    "anomaly_rules",
    "classifier_training_data",
    "custom_classifiers",
    "sla_risk_thresholds",
    "team_members",
    "macros",
    "contact_tickets",
    "contacts",
    "ticket_locks",
    "ticket_approvals",
    "automation_rules",
    "agent_skills",
    "ticket_activity",
    "response_templates",
    "saved_filters",
    "ticket_tags",
    "custom_fields",
    "ticket_merges",
    "scheduled_reports",
    "csat_ratings",
    "kb_articles",
    "audit_log",
    "ticket_history",
    "processed_tickets",
]


def upgrade() -> None:
    for stmt in _TABLES_UP:
        op.execute(stmt)


def downgrade() -> None:
    for table in _TABLES_DOWN:
        op.execute(f"DROP TABLE IF EXISTS {table};")
