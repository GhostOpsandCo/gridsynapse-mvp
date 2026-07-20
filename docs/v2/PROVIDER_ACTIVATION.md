# Provider Activation Boundary

GridSynapse's portfolio build proves the compute procurement workflow without creating billable infrastructure. It converts an approved recommendation into a typed compute commitment, generates an inspectable SkyPilot manifest, verifies safety and evidence checks, simulates the run lifecycle, and reconciles the result.

## What Works Now

- Public catalog pricing and source provenance are normalized into comparable placement evidence.
- Capacity that is not backed by a credentialed inventory source is labeled modeled and non-executable.
- The optimizer enforces workload, GPU, region, deadline, latency, budget, and capacity constraints.
- Human approval is bound to the exact recommendation and input hash.
- Procurement creates an idempotent, spend-capped commitment and a SkyPilot task for every placement.
- Verification checks recommendation approval, hashes, feasibility, workload fields, spend, evidence freshness, credential absence, and the live-execution lock.
- Lifecycle and reconciliation are deterministic simulations. They do not contact a provider.

## Portfolio-Safe Configuration

```bash
GRIDSYNAPSE_PROCUREMENT_ENABLED=true
GRIDSYNAPSE_EXECUTION_ENABLED=false
```

`GRIDSYNAPSE_EXECUTION_ENABLED=false` is the required portfolio setting. The current service deliberately reports `live_launch_allowed=false` even if someone changes the flag; no provider launch implementation is reachable from the API.

## Required Before Paid Activation

Paid compute should not be activated by changing one flag. A production operator must first provide and verify all of the following:

1. **Provider identity and credentials** stored in an approved server-side secret manager.
2. **Account-specific pricing** or a contractual quote instead of public planning prices.
3. **Executable inventory evidence** from a credentialed provider or scheduler API.
4. **Durable procurement storage** for plans, idempotency keys, lifecycle events, and reconciliation records.
5. **Identity, RBAC, and approval policy** that bind a named operator to an exact input hash and spend ceiling.
6. **Provider adapter** that performs a dry run before any launch and maps provider receipts back to the commitment.
7. **Backend kill switch and spend limits** independent of browser state.
8. **Usage and invoice reconciliation** sourced from provider billing records rather than modeled values.
9. **Cancellation, timeout, and partial-failure handling** with an auditable recovery path.
10. **Independent security and release review** before any credential or billable call reaches production.

## Intended Live Sequence

```text
validated recommendation
  -> human approval bound to input hash
  -> fresh account quote and inventory check
  -> spend and policy authorization
  -> provider dry run
  -> explicit launch confirmation
  -> provider receipt
  -> status monitoring
  -> billing reconciliation
```

The portfolio build implements the contracts and workflow around this sequence. The credentialed provider call, durable procurement repository, and provider-billing reconciliation are intentionally not enabled or represented as complete.
