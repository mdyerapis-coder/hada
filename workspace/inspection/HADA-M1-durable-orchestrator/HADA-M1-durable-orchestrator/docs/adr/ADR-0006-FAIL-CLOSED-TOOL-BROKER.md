# ADR-0006: Fail-Closed Tool Broker

**Status:** Proposed

## Context

Agents can generate syntactically valid but unsafe commands, exploit inherited Git configuration, escape a workspace, access secrets or open network connections.

## Decision

HADA permits only configured executable and party combinations. It rejects shells, sudo, executable paths, arbitrary environment variables, unapproved subcommands, excessive arguments and known Git helper/configuration overrides. The broker resolves binaries beneath trusted roots and binds one exact workspace into a Bubblewrap sandbox. Networkless rules require a network namespace; absence of the sandbox is a denial.

## Consequences

Some legitimate development commands require explicit rule changes and review. The broker cannot be bypassed for convenience. Additional kernel-level hardening and per-task containers remain candidates for M3/M6.
