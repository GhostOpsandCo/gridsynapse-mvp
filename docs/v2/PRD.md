# Product Requirements Document: GridSynapse AI Compute Optimization Console

**Status:** Approved for v2 implementation planning
**Branch:** `v2/compute-optimizer`
**Primary owner:** Product / solution architecture
**Initial audience:** AI platform, infrastructure, and FinOps operators
**Product stage:** Deterministic operator-console rebuild

## 1. Executive summary

GridSynapse helps AI infrastructure teams place flexible GPU workloads across available resource pools based on cost, carbon, queue conditions, latency, policy, and service-level constraints.

The v2 product is an operator workflow, not a passive monitoring dashboard:

`Detect workloads -> Meter resource pools -> Choose objective -> Optimize -> Compare -> Explain -> Approve/export`

The system should feel intelligent because it evaluates more feasible placement options than an operator can compare manually, produces an auditable recommendation, and explains the tradeoffs. The schedule itself remains deterministic and reproducible.

## 2. Problem

AI teams often manage GPU workloads across multiple clusters, providers, or regions. The data needed to make placement decisions is fragmented:

- workload requirements live in job manifests or orchestration systems;
- GPU availability and queue conditions live in cluster schedulers;
- cost data lives in cloud bills, contracts, or FinOps tools;
- carbon intensity varies by location and time;
- latency, data residency, interruptibility, deadlines, and budgets constrain placement;
- an operator still has to explain and approve the final decision.

This creates avoidable manual analysis, delayed placement, underused capacity, and decisions that optimize one dimension while silently harming another.

## 3. First-principles product thesis

The valuable object is not a chart. It is a **feasible, comparable, explainable placement plan**.

GridSynapse creates value only when it can:

1. establish the operator's current/default baseline;
2. enumerate placements that satisfy hard constraints;
3. score feasible placements using an explicit objective;
4. quantify deltas in money, emissions, delay, and risk;
5. show the data and rules behind the result;
6. preserve human approval before execution.

## 4. Primary user and initial ICP

### Primary user

An AI platform engineer, infrastructure operator, or FinOps practitioner responsible for scheduling or governing GPU workloads across at least two resource pools.

### Best initial ICP

- AI companies with meaningful batch or flexible GPU demand.
- Platform teams operating Kubernetes, Kueue, Ray, Kubeflow, Slurm, or multiple cloud GPU pools.
- Teams with measurable GPU cost pressure and at least one additional placement constraint such as deadline, carbon target, residency, or queue delay.
- Operators who need recommendation evidence before changing schedules.

### Secondary users

- Engineering leadership reviewing capacity and savings.
- Sustainability teams reviewing workload emissions.
- Finance teams validating compute efficiency.
- Security/compliance teams reviewing location and policy constraints.

## 5. Jobs to be done

### Morning operator brief

"Show me which workloads need a decision, what capacity is available, and where the largest optimization opportunity is."

### Placement decision

"Find the best feasible schedule for my selected objective without violating GPU, deadline, residency, latency, or budget constraints."

### Decision review

"Show me exactly why this schedule is better than the baseline and what tradeoffs it introduces."

### Approval and handoff

"Give me a versioned, exportable plan I can approve or pass to the scheduler without hiding assumptions."

## 6. Product promise

**GridSynapse turns flexible AI demand and fragmented infrastructure signals into an auditable compute placement plan.**

Supporting value:

- Operators compare cost, carbon, delay, and risk in one decision.
- Hard constraints are enforced before objective preferences are considered.
- Every result includes baseline, optimized schedule, deltas, and provenance.
- AI explains the result but cannot alter the schedule.

## 7. Scope

### V2.0 in scope

- Deterministic scenario loading from JSON/CSV.
- Training, fine-tuning, embeddings, and batch-inference workloads.
- Resource pools by cluster/provider/region and GPU type.
- Time-slotted capacity, pricing, carbon intensity, latency, and availability.
- Hard constraints for GPU compatibility, capacity, time window, deadline, residency, latency, and budget.
- Four objective profiles: Cost First, Balanced, Carbon First, SLA First.
- Baseline scheduler and optimized scheduler.
- Baseline-versus-optimized cost, emissions, delay, and utilization metrics.
- Placement timeline and per-workload rationale.
- Structured AI explanation behind a feature flag, with deterministic fallback.
- Human approval and JSON/CSV export.
- Data source, timestamp, freshness, and confidence display.
- Unit, integration, contract, UI, and benchmark tests.

### V2.0 explicitly out of scope

- Autonomous execution against production schedulers.
- Real-time spot-market bidding.
- Live funds, billing, or payment collection.
- Always-on latency-critical inference migration.
- Claims of guaranteed savings, uptime, or carbon reduction.
- Training an AI model on customer data.
- A national power-grid or data-center marketplace.
- SOC 2, HIPAA, FedRAMP, or other certification claims.

## 8. Workload model

Each workload must include:

- `id`, `name`, and `workloadType`;
- `gpuType` and `gpuCount`;
- `durationMinutes`;
- `earliestStart` and `deadline`;
- `priority`;
- `interruptible` and `checkpointable`;
- `latencyClass` or maximum tolerated latency where applicable;
- `dataResidency` allowlist;
- optional `maxBudgetUsd`;
- optional preferred/current resource pool for baseline comparison.

V2 rejects incomplete or infeasible workload records with field-level reasons.

## 9. Resource-pool model

Each resource pool must include:

- provider, cluster, region, and GPU type;
- time-slotted capacity;
- price in USD per GPU-hour;
- power draw in kW per GPU and PUE;
- carbon intensity in gCO2e/kWh;
- network latency and egress cost where relevant;
- availability/confidence signal;
- source, observed timestamp, and freshness state.

## 10. Operator workflow

### Screen 1: Operator Brief

- Pending workload count.
- Requested GPU-hours.
- Estimated baseline cost and emissions.
- Highest-priority workload.
- Data freshness warnings.
- Primary action: `Review optimization queue`.

### Screen 2: Workload Queue

- Workload type, GPU requirement, duration, deadline, priority, and current placement.
- Filter by workload type, GPU, priority, and feasibility.
- Select one or more workloads to optimize.

### Screen 3: Resource Meter

- Capacity by pool and time.
- Price, carbon, latency, queue, and confidence.
- Clear data source and timestamp.
- No random animation; every value comes from the loaded scenario or adapter.

### Screen 4: Objective and constraints

- Segmented objective control: Cost / Balanced / Carbon / SLA.
- Advanced weight detail available through disclosure.
- Hard constraints shown separately from preferences.
- Primary action: `Run optimization`.

### Screen 5: Optimization Result

- Baseline and optimized summary.
- Per-workload placement and start time.
- Timeline with capacity use.
- Cost, emissions, delay, and risk deltas.
- Infeasibility panel when no plan exists.

### Screen 6: GridSynapse AI Explanation

- Why each placement was selected.
- Tradeoffs versus the baseline and alternatives.
- Risks, stale inputs, and operator questions.
- Structured evidence and source references.
- AI cannot edit allocations or objective values.

### Screen 7: Approval and export

- Versioned recommendation ID.
- Input hash and solver version.
- Human approval state.
- JSON/CSV export.
- Scheduler adapter actions remain read-only in v2.

## 11. Objective profiles

Hard constraints always take precedence. Initial soft-objective weights are configuration, not universal truth:

| Profile | Cost | Carbon | Delay | Capacity risk |
| --- | ---: | ---: | ---: | ---: |
| Cost First | 0.65 | 0.10 | 0.15 | 0.10 |
| Balanced | 0.40 | 0.25 | 0.20 | 0.15 |
| Carbon First | 0.15 | 0.60 | 0.15 | 0.10 |
| SLA First | 0.20 | 0.05 | 0.55 | 0.20 |

The UI must show these as policy choices and disclose that different profiles can produce different valid schedules.

## 12. Functional requirements

### Optimization

- FR-1: Reject unsupported GPU types and malformed durations before solver execution.
- FR-2: Schedule each accepted workload exactly once or return a reason it is unscheduled.
- FR-3: Never exceed resource-pool capacity in any time slot.
- FR-4: Respect earliest start, duration, deadline, residency, latency, and budget constraints.
- FR-5: Use integer-safe time, capacity, money, and emissions values.
- FR-6: Return the same result for the same versioned request, configuration, and solver version.
- FR-7: Produce both baseline and optimized results from the same inputs.

### Data and provenance

- FR-8: Every external signal carries source, timestamp, unit, and freshness.
- FR-9: Stale or missing hard-constraint data blocks optimization where required.
- FR-10: Estimated inputs are visibly distinguished from observed inputs.

### Explanation

- FR-11: Explanation input is the immutable optimization result and its provenance.
- FR-12: AI output follows a schema: summary, reasons, tradeoffs, risks, operator actions, sources.
- FR-13: Explanation failures fall back to deterministic templates without losing the result.

### Approval

- FR-14: No export is marked approved without an explicit user action.
- FR-15: A changed input or objective invalidates previous approval.
- FR-16: Export includes recommendation ID, input hash, solver version, timestamps, and approval state.

## 13. Non-functional requirements

- Determinism: identical versioned inputs produce identical placements.
- Accessibility: keyboard-operable controls, visible focus, table semantics, non-color status cues.
- Responsiveness: operator-critical content works at 1280px and remains readable on mobile.
- Observability: request count, solve time, feasibility rate, error type, and adapter freshness metrics.
- Security: synthetic public demo data only; no secrets or scheduler credentials in the browser.
- Performance target: establish through benchmarks before publication. Initial engineering gate is p95 under 2 seconds for 100 jobs, 6 pools, and 96 time slots on the documented test machine.

## 14. Success measures

### Product measures

- Time from scenario load to first valid optimization.
- Percentage of results with complete provenance.
- Feasible-result rate by scenario class.
- Operator approval, revision, and export events.
- Explanation usefulness feedback.

### Technical measures

- Solver invariant pass rate.
- Contract-test pass rate.
- Benchmark p50/p95 by scenario size.
- Data-adapter freshness and error rate.
- Frontend error-free session rate.

### Portfolio measures

- A reviewer understands the product in under 30 seconds.
- A 60-90 second recording demonstrates a real solver result.
- Every public numerical claim links to a scenario and benchmark artifact.

## 15. Claims policy

Do not publish "40% cheaper," "60% cleaner," "sub-100ms," "1M RPS," "99.99% uptime," certification readiness, or equivalent claims unless the repository contains reproducible evidence for the exact claim.

Approved phrasing before evidence exists:

- "Optimizes a selected scenario across cost, carbon, delay, and capacity risk."
- "Illustrative result from a versioned test scenario."
- "Measured on [machine] using [scenario] at [commit]."

## 16. Acceptance criteria for v2 demo

The v2 demo is complete only when:

1. The reference scenario validates against the request schema.
2. The real CP-SAT optimizer is called through the API.
3. Every returned placement passes independent capacity and constraint checks.
4. Baseline and optimized cost/emissions calculations share the same units.
5. Switching objective profiles changes results in at least one golden scenario.
6. The UI renders queue, meters, result, timeline, explanation, and approval from API data.
7. An infeasible scenario produces specific reasons instead of a generic error.
8. Automated tests and benchmark artifacts pass in CI.
9. The public demo contains no unsupported claims or random production-looking metrics.
