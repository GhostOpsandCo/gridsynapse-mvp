# GridSynapse Evidence

This directory separates product evidence from product claims.

## Reference Scenario

`reference-profile-results.json` is generated from the checked-in synthetic scenario at `data/scenarios/reference-scenario.json`. Each profile is solved by OR-Tools CP-SAT and then checked by the independent validator.

The evidence records:

- the canonical recommendation ID;
- solver status and duration;
- baseline and optimized totals;
- every workload placement;
- calculated cost, emissions, and delay deltas;
- independent validation checks.

Regenerate it with:

```bash
.venv/bin/python scripts/generate_reference_evidence.py
```

## Solver Latency Gate

`scripts/run_benchmark.py` builds a fixed synthetic scenario with:

- 100 workloads;
- 6 H100 resource pools;
- 96 half-hour slots;
- deterministic 10-14-slot scheduling windows;
- one CP-SAT worker and a fixed random seed.

The benchmark measures the complete `optimize(request)` call, including baseline generation, candidate enumeration, solve, result construction, and independent validation. The latest local run used 1 warm-up and 8 measured iterations:

| Metric | Result |
| --- | ---: |
| Minimum wall latency | 125.42 ms |
| Median wall latency | 135.38 ms |
| p95 wall latency | 140.46 ms |
| Maximum wall latency | 141.71 ms |
| Placements validated | 100 / 100 |
| Engineering gate | p95 < 2,000 ms: passed |

The generated machine and timing details are written to `evidence/benchmarks/100-jobs-6-pools-96-slots.json`. That file is intentionally ignored because latency varies by machine and should be regenerated in each environment:

```bash
.venv/bin/python scripts/run_benchmark.py
```

## Interpretation

- Reference outcomes demonstrate logic and tradeoffs; they are not production savings forecasts.
- Benchmark timings are local engineering evidence; they are not a hosted-service SLA.
- Synthetic sources are explicit in every scenario and must be replaced by observed or contracted data for a live deployment.
- Approval and exports prove the operator workflow, not automated infrastructure execution.
