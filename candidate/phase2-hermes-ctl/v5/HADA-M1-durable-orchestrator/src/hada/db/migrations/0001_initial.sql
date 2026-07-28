CREATE OR REPLACE FUNCTION hada_valid_evidence_refs(refs JSONB)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(refs) <> 'array' THEN FALSE
        ELSE NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(refs) AS item(value)
            WHERE jsonb_typeof(value) <> 'string'
               OR trim(BOTH '"' FROM value::TEXT) !~ '^sha256:[0-9a-f]{64}$'
        )
    END;
$$;

CREATE TABLE IF NOT EXISTS milestones (
    milestone_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    scope JSONB NOT NULL CHECK (jsonb_typeof(scope) = 'array'),
    out_of_scope JSONB NOT NULL CHECK (jsonb_typeof(out_of_scope) = 'array'),
    implementation_party SMALLINT NOT NULL DEFAULT 1 CHECK (implementation_party = 1),
    stop_reason TEXT NOT NULL DEFAULT 'none',
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestones(milestone_id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'proposed', 'ready', 'leased', 'running', 'awaiting_review',
        'rejected', 'completed', 'failed', 'cancelled'
    )),
    assigned_party SMALLINT NOT NULL CHECK (assigned_party IN (1, 2)),
    acceptance_criteria JSONB NOT NULL CHECK (jsonb_typeof(acceptance_criteria) = 'array'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    workspace_id TEXT,
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_milestone_status_idx ON tasks (milestone_id, status);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestones(milestone_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE RESTRICT,
    owner_party SMALLINT NOT NULL CHECK (owner_party = 1),
    path TEXT NOT NULL UNIQUE,
    repository_url TEXT NOT NULL,
    requested_ref TEXT NOT NULL,
    resolved_commit TEXT NOT NULL CHECK (resolved_commit ~ '^[0-9a-f]{40,64}$'),
    status TEXT NOT NULL CHECK (status IN ('active', 'sealed', 'retired', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sealed_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ
);

ALTER TABLE tasks
    ADD CONSTRAINT tasks_workspace_fk
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS evidence_artifacts (
    digest TEXT PRIMARY KEY CHECK (digest ~ '^[0-9a-f]{64}$'),
    algorithm TEXT NOT NULL CHECK (algorithm = 'sha256'),
    logical_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    object_path TEXT NOT NULL UNIQUE,
    manifest JSONB NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    signer_key_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS gate_decisions (
    decision_id TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestones(milestone_id) ON DELETE RESTRICT,
    gate TEXT NOT NULL CHECK (gate IN (
        'architecture', 'security', 'test', 'documentation',
        'milestone_report', 'external_review'
    )),
    status TEXT NOT NULL CHECK (status IN ('approved', 'rejected', 'blocked')),
    reviewer_party SMALLINT NOT NULL CHECK (reviewer_party BETWEEN 1 AND 3),
    subject_party SMALLINT NOT NULL CHECK (subject_party BETWEEN 1 AND 3),
    evidence JSONB NOT NULL CHECK (hada_valid_evidence_refs(evidence)),
    findings JSONB NOT NULL CHECK (jsonb_typeof(findings) = 'array'),
    decision_digest TEXT NOT NULL UNIQUE CHECK (decision_digest ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (milestone_id, gate),
    CHECK (status <> 'approved' OR reviewer_party <> subject_party),
    CHECK (status <> 'approved' OR jsonb_array_length(evidence) > 0),
    CHECK ((gate = 'external_review' AND reviewer_party = 3 AND subject_party = 1) OR
           (gate <> 'external_review' AND reviewer_party = 2 AND subject_party = 1))
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    policy_decision_id TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestones(milestone_id) ON DELETE RESTRICT,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    workspace_id TEXT REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
    actor_party SMALLINT NOT NULL CHECK (actor_party BETWEEN 1 AND 3),
    rule_id TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (NOT allowed OR actor_party IN (1, 2))
);
CREATE INDEX IF NOT EXISTS policy_decisions_task_idx ON policy_decisions (task_id, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
    sequence BIGINT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    stream TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_party SMALLINT CHECK (actor_party BETWEEN 1 AND 3),
    occurred_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    previous_hash TEXT NOT NULL CHECK (previous_hash ~ '^[0-9a-f]{64}$'),
    event_hash TEXT NOT NULL UNIQUE CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    signer_key_id TEXT NOT NULL,
    signature TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_stream_idx ON audit_events (stream, sequence);

CREATE OR REPLACE FUNCTION hada_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS milestones_set_updated_at ON milestones;
CREATE TRIGGER milestones_set_updated_at
BEFORE UPDATE ON milestones
FOR EACH ROW EXECUTE FUNCTION hada_set_updated_at();

DROP TRIGGER IF EXISTS tasks_set_updated_at ON tasks;
CREATE TRIGGER tasks_set_updated_at
BEFORE UPDATE ON tasks
FOR EACH ROW EXECUTE FUNCTION hada_set_updated_at();
