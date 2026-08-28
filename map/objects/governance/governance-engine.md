---
type: object
universe: live
status: verified
date: 2026-08-26
commit: 14a1036
---

# GovernanceEngine — milestone gate state machine

## Why this shape

Encodes a fixed review protocol as code so it can't be bypassed by a caller forgetting a check: five internal gates (architecture, security, test, documentation, milestone_report) must all be `APPROVED` by Party 2 before the `external_review` gate (Party 3) is even allowed to record a decision (`_internal_gates_approved`, `engine.py:40-46`), decisions are immutable once recorded (`engine.py:55-56`), and a rejected/blocked gate forces `StopReason.HUMAN_INPUT_REQUIRED` (`engine.py:71-73`) rather than letting the milestone continue.

## Shape

- `src/hada/governance/engine.py` — `GovernanceEngine.record_decision(state, decision) -> GovernanceResult`, `_validate_parties` (subject must be Party 1; internal gates reviewed by Party 2, external_review by Party 3), `_INTERNAL_GATES` tuple
- `src/hada/models.py` — `GateName`, `GateStatus`, `StopReason` enums; `GateDecision.prevent_self_approval` validator (an approval needs non-empty `evidence` referencing `sha256:...` digests)
- `GovernanceViolation(RuntimeError)` is the single exception type for every rule breach

## Connected to

- owns: nothing persistent — pure function over a `MilestoneState` passed in and mutated in place, then returned via `GovernanceResult`
- owned-by: `objects/orchestrator/orchestrator-service.md` (`OrchestratorService.__init__` defaults to `GovernanceEngine()`) and `hada.cli`'s `audit verify`/`evidence add` flows indirectly via `GateDecision.evidence`
- joins: `objects/evidence-audit/evidence-store.md` (approvals must cite evidence digests, though `GovernanceEngine` itself never opens the evidence store — it only checks the list is non-empty)
- looks-like-but-is-not: `objects/governance/policy-broker.md` — that's runtime tool-execution sandboxing; this is milestone/gate approval bookkeeping. Same cluster name, unrelated code paths.

## If you change this

- Hits: `objects/orchestrator/orchestrator-service.md` (constructs and calls this), `models.py` (`GateName`/`GateStatus`/`StopReason` are shared), `db/postgres.py` (`record_gate_decision`)
- Does not hit: `queue/broker.py`, `evidence/store.py`'s actual file storage (only the digest reference is checked, not fetched)

## Surfaces

- called from `OrchestratorService`; no direct CLI command — governance decisions are recorded through the orchestrator, not a standalone `hada governance` command

## See

- `src/hada/governance/engine.py:28-84`
