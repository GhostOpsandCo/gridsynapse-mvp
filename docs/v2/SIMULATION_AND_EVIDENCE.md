# GridSynapse v2 Simulation and Evidence Plan

## 1. Purpose

GridSynapse should demonstrate optimization through reproducible scenarios, not decorative metrics. This document defines the reference simulation, expected directional outcomes, validation gates, benchmarks, and public evidence.

## 2. Reference scenario

The versioned source is [`scenarios/reference-scenario.json`](./scenarios/reference-scenario.json).

### Workloads

| Workload | Type | GPU requirement | Duration | Window | Baseline |
| --- | --- | ---: | ---: | --- | --- |
| Foundation model train | Training | 8 A100 | 4h | 8h | US West |
| Support model tune | Fine-tuning | 4 A100 | 2h | 6h | US West |
| Embedding refresh | Batch inference | 2 A100 | 1h | 4h | US West |

Total demand: **42 A100 GPU-hours**.

### Resource pools

| Pool | Price | Carbon | Latency | Capacity | PUE |
| --- | ---: | ---: | ---: | ---: | ---: |
| US West | $3.10/GPUh | 410 gCO2e/kWh | 18ms | 16 A100 | 1.18 |
| US Central | $2.55/GPUh | 620 gCO2e/kWh | 38ms | 16 A100 | 1.20 |
| US East | $3.35/GPUh | 180 gCO2e/kWh | 52ms | 16 A100 | 1.15 |

These values are synthetic and intentionally create a real tradeoff: Central is cheaper but more carbon intensive; East is cleaner but more expensive.

## 3. Hand-calculated reference points

Assume A100 power draw of 0.4 kW and no egress cost for this controlled scenario.

### Baseline: all workloads in US West

```text
cost = 42 GPUh * $3.10 = $130.20
energy = 42 GPUh * 0.4 kW * 1.18 PUE = 19.824 kWh
emissions = 19.824 kWh * 410 g/kWh / 1000 = 8.128 kgCO2e
```

### Cost-only reference: all workloads in US Central

```text
cost = 42 * $2.55 = $107.10
cost delta = -17.7%
energy = 42 * 0.4 * 1.20 = 20.160 kWh
emissions = 20.160 * 620 / 1000 = 12.499 kgCO2e
emissions delta = +53.8%
```

This is a valid example of why "cheapest" is not automatically "best."

### Carbon-only reference: all workloads in US East

```text
cost = 42 * $3.35 = $140.70
cost delta = +8.1%
energy = 42 * 0.4 * 1.15 = 19.320 kWh
emissions = 19.320 * 180 / 1000 = 3.478 kgCO2e
emissions delta = -57.2%
```

### Mixed reference schedule

- Training: US East (32 GPUh)
- Fine-tuning: US Central (8 GPUh)
- Embedding refresh: US West (2 GPUh)

```text
cost = (32 * 3.35) + (8 * 2.55) + (2 * 3.10) = $133.80
emissions =
  (32 * 0.4 * 1.15 * 180 / 1000)
  + (8 * 0.4 * 1.20 * 620 / 1000)
  + (2 * 0.4 * 1.18 * 410 / 1000)
  = 5.417 kgCO2e

cost delta = +2.8%
emissions delta = -33.3%
```

This is a plausible balanced tradeoff, but it is **not** a required solver output until the configured objective weights and normalization are implemented. The implementation test should assert feasibility and component math first, then lock the expected optimal schedule after review.

## 4. Objective simulations

| Objective | Expected direction | What the UI should explain |
| --- | --- | --- |
| Cost First | Prefer Central when deadlines/capacity permit | Lower cost can increase emissions |
| Balanced | Mix pools or accept a small cost premium for meaningful emissions reduction | No single metric dominates |
| Carbon First | Prefer East and potentially cleaner time slots | Cleaner placement may cost more or start later |
| SLA First | Prefer earliest, lower-latency feasible pool | SLA pressure can reduce savings and carbon flexibility |

The scenario suite must include at least one case where each objective produces a different schedule. The reference scenario alone does not have to cover every edge case.

## 5. Golden scenario suite

### GS-1: Cost-carbon tradeoff

Reference scenario above. Proves objective switching and baseline comparison.

### GS-2: Capacity collision

Two 12-GPU workloads overlap on a 16-GPU pool. Proves capacity is enforced and one job moves or waits.

### GS-3: Deadline pressure

A job has only one valid start. Proves duration ceiling and deadline enforcement.

### GS-4: Residency restriction

A workload allows only US East. Proves cheaper/cleaner alternatives outside the allowlist are never selected.

### GS-5: Unsupported GPU

H100 workload with only A100 pools. Proves explicit infeasibility.

### GS-6: Budget infeasibility

Every feasible placement exceeds max budget. Proves budget reason code.

### GS-7: Stale carbon signal

Cost objective can continue with warning; carbon objective blocks or follows configured fallback policy. Proves data-health behavior.

### GS-8: No-change result

Baseline is already optimal. Proves GridSynapse says "no change recommended" instead of inventing savings.

## 6. Invariant tests

Every feasible result must satisfy:

- workload placed once;
- compatible GPU;
- valid region;
- start >= earliest start;
- end <= deadline;
- per-slot capacity not exceeded;
- budget and latency respected;
- aggregate totals equal placement sums;
- result input hash equals request hash;
- optimized and baseline use the same calculators;
- approval is not inherited after input changes.

Property-based tests should generate small randomized scenarios and validate these invariants independently of the optimizer.

## 7. Benchmark plan

Do not publish a performance claim until these are measured:

| Benchmark | Jobs | Pools | Slots | Runs |
| --- | ---: | ---: | ---: | ---: |
| Small demo | 12 | 3 | 16 | 50 |
| Operator | 100 | 6 | 96 | 30 |
| Stress | 500 | 12 | 192 | 10 |

Record:

- machine CPU/RAM/OS;
- Python, OR-Tools, and commit versions;
- p50, p95, max solve time;
- feasible/infeasible status;
- variable and constraint counts;
- objective profile;
- deterministic-result hash.

Initial engineering gate: p95 under 2 seconds for the Operator benchmark on the documented machine. This is a gate, not a public claim, until measured.

## 8. AI explanation evaluation

For each golden scenario, compare output against required facts:

- selected pool and start;
- baseline and optimized totals;
- objective profile;
- binding constraints;
- tradeoffs;
- stale/missing sources;
- approval boundary.

Fail if the explanation:

- invents a pool, metric, percentage, source, or execution;
- describes a soft preference as a hard constraint;
- claims guaranteed savings;
- omits a material warning;
- contradicts the validated result.

## 9. UI simulation script

A portfolio walkthrough should take 60-90 seconds:

1. Operator Brief shows three pending workloads and the named baseline.
2. Operator opens the queue and selects all three.
3. Resource Meter exposes the cost/carbon tradeoff across West, Central, and East.
4. Operator runs Balanced optimization.
5. Result shows placement timeline and validated baseline deltas.
6. Operator switches to Cost First and sees the schedule and tradeoff change.
7. GridSynapse AI explains why cost fell and emissions rose.
8. Operator approves and downloads the recommendation JSON.

## 10. Portfolio evidence ledger

| Public statement | Required evidence |
| --- | --- |
| "Uses a real optimization engine" | API call path + CP-SAT tests |
| "Enforces capacity and deadlines" | invariant tests |
| "Compares cost and carbon" | shared formulas + reference scenario |
| "AI explains decisions" | structured schema + eval results |
| "Adapter-ready" | provider interfaces + one imported snapshot |
| "Measured solve time" | benchmark artifact with machine/commit |
| "Live product" | production smoke and recording |

## 11. Publishable assets

- Live `gridsynapse.io` console.
- Architecture diagram.
- One reference-scenario methodology page.
- Benchmark summary.
- 60-90 second product recording.
- Before/after screenshots of legacy dashboard and v2 workflow.
- Code excerpts for CP-SAT constraints, result validator, adapter interface, and explanation guardrail.

## 12. Evidence rule

The dashboard can be visually impressive, but every number that looks live must be one of:

- observed and timestamped;
- contract-priced and identified;
- imported from a versioned public snapshot;
- calculated from those inputs;
- clearly labeled synthetic for a scenario.

No random animation may be presented as operational telemetry.
