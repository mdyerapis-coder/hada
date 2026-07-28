# RFC-0001: Governed Autonomous Engineering

**Status:** Accepted for M0

## Decision

HADA uses milestone-scoped autonomy. Every milestone begins with explicit scope and acceptance criteria. Implementation is performed by Party 1. Party 2 reviews without sharing approval authority with Party 1. Party 3 is external to HADA and is the final independent review gate.

## Required evidence

Each gate decision must name its reviewer party, subject party, status, findings and evidence references. Approvals without evidence are invalid. Evidence artefacts are content-addressed before they are attached to a decision.

## Stop conditions

HADA stops when:

- target repository, model or secret configuration is incomplete;
- a required independent reviewer is unavailable;
- a gate rejects or blocks the milestone;
- a critical security finding exists;
- recovery attempts are exhausted;
- proposed work exceeds milestone scope;
- a request would weaken or bypass governance;
- the milestone is complete.
