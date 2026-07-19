# GridSynapse v2 Planning Index

GridSynapse v2 is an **AI Compute Optimization Console** for platform, infrastructure, and FinOps operators. It turns flexible AI workloads, GPU capacity, cost, carbon, latency, and policy constraints into an auditable placement plan.

This folder is the source of truth for the rebuild. The legacy dashboard and API remain useful design and domain references, but they are not evidence that the v2 optimization workflow is implemented.

## Product thesis

An operator should be able to answer five questions in one workflow:

1. Which AI workloads are waiting for placement?
2. What GPU capacity, cost, carbon, latency, and queue conditions are available?
3. What schedule best matches the operator's objective and hard constraints?
4. How does the optimized schedule compare with the current/default baseline?
5. Why did GridSynapse make each recommendation, and what still requires human approval?

## Planning artifacts

| Artifact | Purpose |
| --- | --- |
| [PRD](./PRD.md) | User, problem, scope, requirements, success measures, and acceptance criteria |
| [Research and repo audit](./RESEARCH_AND_REPO_AUDIT.md) | Current-state findings, official ecosystem patterns, product wedge, and claim boundaries |
| [Architecture](./ARCHITECTURE.md) | Target services, contracts, optimization model, adapters, API, and AI boundary |
| [Delivery plan](./DELIVERY_PLAN.md) | Workstreams, expert ownership, critical path, QA gates, rollout, and risks |
| [Simulation and evidence](./SIMULATION_AND_EVIDENCE.md) | Deterministic scenarios, expected outcomes, benchmark gates, and portfolio proof |
| [Optimization request schema](./contracts/optimization-request.schema.json) | Canonical v2 optimizer input |
| [Optimization result schema](./contracts/optimization-result.schema.json) | Canonical baseline-versus-optimized output |
| [Reference scenario](./scenarios/reference-scenario.json) | Small deterministic scenario for implementation and tests |

## Decisions already made

- **Primary user:** AI platform, infrastructure, or FinOps operator.
- **Initial workload wedge:** flexible training, fine-tuning, embeddings, and batch inference.
- **Optimization core:** OR-Tools CP-SAT with integer time slots and hard feasibility constraints.
- **AI role:** explain, summarize, and prepare operator actions; never change the solver result.
- **Initial data:** deterministic JSON/CSV plus timestamped public carbon data snapshots.
- **Approval boundary:** GridSynapse prepares schedules and exports; the operator approves downstream action.
- **Claims policy:** publish only measured results with scenario, timestamp, units, baseline, and methodology.

## Current repository truth

The current repository contains a strong visual prototype, a FastAPI surface, a first-pass OR-Tools model, Prometheus configuration, and Docker assets. It also contains important gaps that v2 must correct:

- `/api/v1/optimize` returns a mock response instead of calling the solver.
- The solver uses the continuous GLOP backend while declaring integer variables.
- Duration, capacity, carbon, and objective units are not modeled consistently.
- The dashboard animates unsupported metrics instead of rendering source-backed results.
- The CI workflow references tests, Kubernetes manifests, and package files that do not exist.
- Several performance, security, reliability, savings, and scale claims are not backed by evidence.

## Definition of a credible v2 demo

A credible demo is not a prettier version of the legacy dashboard. It must:

1. Load a versioned scenario with source timestamps.
2. Show pending workloads and regional GPU conditions.
3. Run the real deterministic optimizer.
4. Show a feasible schedule or explicit infeasibility reasons.
5. Compare the result against a named baseline.
6. Explain the result from the same structured data.
7. Require human approval before export.
8. Reproduce the result through automated tests.
