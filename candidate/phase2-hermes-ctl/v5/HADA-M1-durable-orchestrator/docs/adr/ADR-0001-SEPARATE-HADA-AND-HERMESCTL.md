# ADR-0001: Separate HADA from Hermesctl

**Status:** Accepted

HADA and Hermesctl use separate repositories, release processes, credentials and runtime identities. HADA receives the Hermesctl repository URL and revision through configuration. This prevents the orchestration platform from conflating changes to its own control mechanisms with changes to the product it governs.
