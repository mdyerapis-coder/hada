CREATE OR REPLACE FUNCTION hada_enforce_audit_continuity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_previous_hash TEXT;
    expected_sequence BIGINT;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('hada_audit_chain'));
    SELECT event_hash, sequence + 1
      INTO expected_previous_hash, expected_sequence
      FROM audit_events
     ORDER BY sequence DESC
     LIMIT 1;

    IF expected_previous_hash IS NULL THEN
        expected_previous_hash := repeat('0', 64);
        expected_sequence := 1;
    END IF;

    IF NEW.previous_hash <> expected_previous_hash THEN
        RAISE EXCEPTION
            'audit chain continuity violation: expected previous_hash %, received %',
            expected_previous_hash,
            NEW.previous_hash;
    END IF;

    NEW.sequence := expected_sequence;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS audit_events_enforce_continuity ON audit_events;
CREATE TRIGGER audit_events_enforce_continuity
BEFORE INSERT ON audit_events
FOR EACH ROW EXECUTE FUNCTION hada_enforce_audit_continuity();

CREATE OR REPLACE FUNCTION hada_reject_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'immutable HADA record may not be updated or deleted: %', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'audit_events',
        'evidence_artifacts',
        'gate_decisions',
        'policy_decisions'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', table_name || '_reject_update', table_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION hada_reject_mutation()',
            table_name || '_reject_update',
            table_name
        );
    END LOOP;
END;
$$;
