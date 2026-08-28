---
type: object
universe: live
status: verified
date: 2026-08-26
commit: 14a1036
---

# PolicyEngine / policy broker — sandboxed tool-execution gate

## Why this shape

Agents (Party 1/2) execute tools through this broker instead of a raw shell, so every command is deny-by-default checked before it runs: no shells or path-qualified executables allowed at all (`exec.no-shell`, `policy/broker.py:128-129`), only executables named in an explicit `ExecutionConfig.rules` allowlist keyed by `(executable, actor_party)`, argument count/length/control-character limits, and agent-supplied environment variables are rejected outright if their names look secret-like or even if they're merely well-formed (`exec.environment-closed`) — the comment-equivalent rule is "use governed configuration instead" of letting an agent pass its own env. `ToolRequest.digest` (sha256 of canonical JSON) gives every request a stable id for the audit/policy-decision log before it ever executes.

## Shape

- `src/hada/policy/broker.py` — `PolicyEngine.evaluate(request) -> PolicyDecision` (rule engine), `ToolRequest`, `PolicyDecision`, `ExecutionResult`, `BrokerOutcome`
- `src/hada/models.py` — `ExecutionConfig`, `ToolRuleConfig` (the allowlist config `PolicyEngine` is constructed with)
- Regexes gate secret-shaped env var names (`_SECRET_NAME`), block a fixed list of dangerous git flags (`_GIT_DANGEROUS`), and redact secret-shaped substrings from captured output (`_OUTPUT_SECRET`)
- `PolicyDecisionRecorder` / `AuditRecorder` protocols — every decision (allow or deny) is meant to be recorded, not just enforced

## Connected to

- owns: nothing persistent — a pure rule evaluator plus a subprocess runner (uses `resource`/`signal`/`subprocess` for timeout + rlimits, not shown in the evaluate() excerpt but imported at `broker.py:2-9`)
- owned-by: whatever party-side executor calls it before running a tool on behalf of an agent (the CLI does not currently expose a `policy` command — this is a library, not a Typer subcommand)
- joins: `objects/orchestrator/orchestrator-service.md` indirectly (tool execution happens inside a task's `workspace_id`, a `WorkspaceRecord` from `objects/interfaces/workspace-manager.md`)
- looks-like-but-is-not: `objects/governance/governance-engine.md` — that's milestone-gate approval bookkeeping; this is per-command sandboxing. Different files, different failure mode (`GovernanceViolation` vs `BrokerError`/denied `PolicyDecision`)

## If you change this

- Hits: `models.py` (`ExecutionConfig`/`ToolRuleConfig` shape), any caller holding a `PolicyDecisionRecorder`/`AuditRecorder` (would need updating if the protocol signature changes)
- Does not hit: `queue/broker.py` (unrelated "broker" — name collision only), `orchestrator/*` (this evaluates one tool call, it does not touch task/milestone state)

## Surfaces

- library used by whatever executes agent tool calls inside a workspace; no direct CLI command as of this pass

## See

- `src/hada/policy/broker.py:114-160`
