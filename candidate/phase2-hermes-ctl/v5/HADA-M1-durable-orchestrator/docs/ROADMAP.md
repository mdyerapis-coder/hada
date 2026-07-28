# Roadmap

## M0 — Governed foundation

Repository structure, governance model, host bootstrap, base control-plane services, watchdog, CI and operating documentation.

**Status:** implementation produced; approval remains external.

## M1 — Durable orchestrator

PostgreSQL schema and migrations, signed audit log, content-addressed evidence, Valkey queues, leases, transactional outbox, workspace creation, task lifecycle, policy-enforced tool execution and control-plane runtime.

**Status:** implementation candidate complete; pending independent Party 3 review and live Vast.ai deployment validation.

## M2 — Local inference plane

GPU discovery, approved model profiles, vLLM/SGLang deployment, readiness and load tests, resource admission control and model fallback policy.

**Entry gate:** M1 external review approved; Vast.ai GPU/storage baseline and model licences confirmed.

## M3 — Party 1 implementation workflow

Hermesctl checkout, architecture-first task planning, patch production, deterministic test execution and evidence capture.

## M4 — Party 2 adversarial workflow

Independent context construction, threat modelling, architecture review, security review, mutation and regression testing, documentation review and rejection loops.

## M5 — Party 3 evidence exchange

Signed export bundle, external-review instructions, decision import, signer verification and immutable milestone closure.

## M6 — Production hardening

Backups and restore drills, GPU and disk pressure handling, SLOs, alerting, disaster recovery, supply-chain controls, SBOM, image signing and controlled upgrades.
