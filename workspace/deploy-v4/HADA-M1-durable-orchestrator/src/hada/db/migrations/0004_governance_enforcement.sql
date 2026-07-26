CREATE OR REPLACE FUNCTION hada_validate_gate_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    current_stop_reason TEXT;
    approved_internal_gates INTEGER;
BEGIN
    SELECT stop_reason
      INTO current_stop_reason
      FROM milestones
     WHERE milestone_id = NEW.milestone_id
     FOR UPDATE;

    IF current_stop_reason IS NULL THEN
        RAISE EXCEPTION 'milestone does not exist: %', NEW.milestone_id;
    END IF;

    IF NEW.gate = 'external_review' THEN
        IF current_stop_reason <> 'external_review_required' THEN
            RAISE EXCEPTION
                'external review requires external_review_required stop state, found %',
                current_stop_reason;
        END IF;

        SELECT count(*)
          INTO approved_internal_gates
          FROM gate_decisions
         WHERE milestone_id = NEW.milestone_id
           AND gate IN (
               'architecture', 'security', 'test', 'documentation', 'milestone_report'
           )
           AND status = 'approved';

        IF approved_internal_gates <> 5 THEN
            RAISE EXCEPTION
                'external review requires five approved internal gates, found %',
                approved_internal_gates;
        END IF;
    ELSIF current_stop_reason <> 'none' THEN
        RAISE EXCEPTION
            'internal gate may not be recorded while milestone is stopped: %',
            current_stop_reason;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS gate_decisions_validate_insert ON gate_decisions;
CREATE TRIGGER gate_decisions_validate_insert
BEFORE INSERT ON gate_decisions
FOR EACH ROW EXECUTE FUNCTION hada_validate_gate_insert();

CREATE OR REPLACE FUNCTION hada_apply_gate_stop_reason()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    next_stop_reason TEXT;
    approved_internal_gates INTEGER;
BEGIN
    IF NEW.status IN ('rejected', 'blocked') THEN
        next_stop_reason := 'human_input_required';
    ELSIF NEW.gate = 'external_review' THEN
        next_stop_reason := 'milestone_complete';
    ELSE
        SELECT count(*)
          INTO approved_internal_gates
          FROM gate_decisions
         WHERE milestone_id = NEW.milestone_id
           AND gate IN (
               'architecture', 'security', 'test', 'documentation', 'milestone_report'
           )
           AND status = 'approved';

        IF approved_internal_gates = 5 THEN
            next_stop_reason := 'external_review_required';
        ELSE
            next_stop_reason := 'none';
        END IF;
    END IF;

    UPDATE milestones
       SET stop_reason = next_stop_reason,
           version = version + 1
     WHERE milestone_id = NEW.milestone_id
       AND stop_reason IS DISTINCT FROM next_stop_reason;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS gate_decisions_apply_stop_reason ON gate_decisions;
CREATE TRIGGER gate_decisions_apply_stop_reason
AFTER INSERT ON gate_decisions
FOR EACH ROW EXECUTE FUNCTION hada_apply_gate_stop_reason();
