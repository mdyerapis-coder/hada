# HADA M1 Governed Deployment Takeover

## Operator

Hermes Agent running locally on Fedora.

Provider:

tencent-tokenhub

Model:

kimi-k2.7-code

Hermes is the implementation and deployment operator. Hermes is not an
independent reviewer and must not approve its own work.

## Existing Google Cloud infrastructure

Project:

api-intergrations-501314

VM:

- Name: hada-control
- Zone: australia-southeast1-b
- OS: Ubuntu 24.04.4 LTS
- CPU: 4 vCPU
- RAM: approximately 15 GiB
- Boot disk: 30 GB
- Persistent data disk: 100 GB
- Data device: /dev/sdb
- Filesystem: ext4
- Data UUID: a1574097-cdf9-4d0a-ace0-adac63038e56
- Data mount: /var/lib/hada

Firewall:

- Rule: hada-iap-ssh
- Source: 35.235.240.0/20
- Protocol and port: TCP 22
- Target tag: hada-control

Access command:

gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

## Local source

Archive:

/home/bobthabuilda/hada-deployment/HADA-M1-durable-orchestrator.zip

Hermesctl repository:

https://github.com/mdyerapis-coder/hermesctl.git

Target branch:

main

## Governance boundary

Hermes may:

- inspect the HADA archive;
- inspect the existing infrastructure;
- prepare implementation changes;
- deploy only after explicit Phase B approval;
- run validation;
- collect deployment evidence.

Hermes may not:

- approve its own implementation;
- mark M1 approved;
- begin M2;
- develop or modify Hermesctl;
- bypass tests or governance controls;
- modify hermes-clean;
- modify home-hub;
- delete existing Google Cloud resources;
- expose services publicly;
- store secrets in source files, evidence or Git history.

The only valid successful deployment status is:

IMPLEMENTATION_CANDIDATE_AWAITING_PARTY_3

Failure or blocking statuses are:

FAILED_VALIDATION

BLOCKED_REQUIRES_HUMAN_INPUT

## Prohibited operations

Do not:

- create or recreate hada-control;
- delete, detach, resize or recreate its disks;
- format /dev/sdb;
- run mkfs against any device;
- delete or replace the hada-iap-ssh firewall rule;
- add public HTTP or HTTPS firewall rules;
- print API keys, passwords or private keys;
- commit credentials;
- run docker compose down -v;
- weaken validation to make tests pass;
- continue from Phase A into Phase B without explicit approval.

## Phase A — read-only inspection

Phase A permits read-only local and remote inspection.

Perform the following:

1. Confirm the local working directory.
2. Confirm the active gcloud identity and project.
3. Inspect the existing hada-control VM.
4. Inspect attached disks without changing them.
5. Inspect network tags and the hada-iap-ssh firewall rule.
6. Verify IAP SSH access.
7. Verify /var/lib/hada is mounted from the expected device and UUID.
8. Inspect /etc/fstab without editing it.
9. Calculate the SHA-256 checksum of the local archive.
10. List the archive contents.
11. Extract it only into a new local inspection directory.
12. Inspect all source files, scripts, Compose definitions, systemd units,
    migrations, tests and configuration templates.
13. Verify Hermesctl repository access using git ls-remote only.
14. Identify every package assumption or defect affecting deployment.
15. Determine where all Docker persistent state would reside.
16. Identify every published or remotely accessible service port.
17. Prepare a production deployment plan.
18. Prepare a rollback plan.
19. List every proposed Phase B command.
20. Produce the required evidence files.
21. Stop and request explicit human approval.

Do not modify hada-control during Phase A.

Do not use sudo during Phase A.

## Phase A evidence directory

Store evidence under:

/home/bobthabuilda/hada-deployment/evidence/phase-a/

Required files:

- infrastructure-inventory.txt
- local-archive-sha256.txt
- package-file-list.txt
- package-findings.md
- repository-access.txt
- proposed-commands.sh
- deployment-plan.md
- rollback-plan.md
- unresolved-findings.md
- SHA256SUMS

Evidence must not contain secrets.

## Mandatory Phase B design requirements

These requirements must be included in the Phase A plan but must not yet be
implemented.

### Persistent data

All persistent HADA application state must reside beneath:

/var/lib/hada/

Docker stateful service data must not be left on the 30 GB boot disk.

The deployment must account for at least:

- PostgreSQL
- Valkey
- Prometheus
- Loki
- Alloy
- Grafana
- Caddy data
- Caddy configuration
- orchestrator state
- evidence
- logs
- backups

Inspect whether bind mounts, Docker data-root relocation or another bounded
design is most appropriate. Do not assume ordinary named volumes satisfy this
requirement.

### Network exposure

Do not create public application firewall rules.

Do not remotely expose:

- PostgreSQL
- Valkey
- Prometheus
- Loki
- Alloy
- Grafana
- orchestrator administrative endpoints
- Docker daemon
- internal health endpoints

Administrative access must use IAP SSH or a separately reviewed private access
mechanism.

### Deployment validation

Phase B must eventually validate:

- persistent disk mounting;
- effective Docker Compose configuration;
- PostgreSQL health and migrations;
- governance constraints;
- authenticated Valkey operation;
- orchestrator liveness and readiness;
- immutable audit records;
- audit signing and hash-chain verification;
- bounded workspace creation;
- Hermesctl repository accessibility;
- watchdog recovery behaviour;
- service recovery following reboot;
- absence of unexpected public listeners;
- persistence of state after reboot.

## Phase A stopping condition

After creating all evidence, report:

PHASE_A_COMPLETE_AWAITING_HUMAN_REVIEW

Then stop.

Do not propose automatic approval and do not begin Phase B.
