CREATE TABLE IF NOT EXISTS outbox_events (
    outbox_id TEXT PRIMARY KEY,
    queue_name TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'publishing', 'published', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS outbox_publish_idx
    ON outbox_events (state, available_at, created_at);

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id TEXT PRIMARY KEY,
    consumer TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    result_digest TEXT CHECK (result_digest IS NULL OR result_digest ~ '^[0-9a-f]{64}$')
);

DROP TRIGGER IF EXISTS processed_messages_reject_update ON processed_messages;
CREATE TRIGGER processed_messages_reject_update
BEFORE UPDATE OR DELETE ON processed_messages
FOR EACH ROW EXECUTE FUNCTION hada_reject_mutation();
