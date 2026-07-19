# GridSynapse v2 Research and Repository Audit

**Audit date:** July 17, 2026
**Repository:** `GhostOpsandCo/gridsynapse-mvp`
**Audit branch:** `v2/compute-optimizer`

## 1. Executive read

The previous GridSynapse version is a strong visual concept with enough backend structure to explain the original ambition. It is not yet a credible compute-optimization product.

The rebuild should preserve:

- real-time operator feel;
- dense but readable meters;
- clear cost/carbon framing;
- Prometheus-compatible observability direction;
- Python/FastAPI/OR-Tools foundation.

It should replace:

- random dashboard metrics;
- mock optimization responses;
- unsupported performance and compliance claims;
- continuous LP scheduling presented as integer scheduling;
- infrastructure files that reference nonexistent services or tests;
- a national-grid/marketplace story that is much broader than the working product.

## 2. Current repository findings

### Product and UI

`infra/dashboard-v2.html` and `infra/mobile-dashboard.html` show good early product instincts: compact status, meters, activity, earnings/cost concepts, and a credible operator aesthetic.

However, the primary metrics are generated or animated in the browser. Examples include GPU counts, carbon saved, hourly savings, latency, uptime, large job migrations, and activity feed events. These values do not come from the API, solver, Prometheus, or source snapshots.

**Decision:** reuse the visual rhythm, not the values or information architecture.

### API

`api/main.py` exposes useful conceptual routes, but:

- `/api/v1/optimize` returns a mock result instead of calling `solver/optimizer.py`;
- submitted jobs return hardcoded scheduling, cost, and carbon values;
- prices, partner onboarding, billing, certificates, and solver health are mocked;
- Redis is required at application startup even though the core demo could run without it;
- CORS is open and there is no meaningful auth boundary;
- PostgreSQL is launched but not used by the API.

**Decision:** create a small v2 API around scenarios, real optimization, provenance, approval, and export. Do not carry forward unrelated mock marketplace endpoints.

### Optimizer

`solver/optimizer.py` uses `pywraplp.Solver.CreateSolver('GLOP')` while declaring integer variables. GLOP is a continuous linear solver, so it does not provide the scheduling semantics the product claims.

Additional correctness risks:

- duration is truncated with `int()` instead of rounded up;
- variables are created for invalid trailing start times;
- exact-once constraints do not cover every created variable consistently;
- cost, revenue, carbon, and preference terms are combined without common units or normalization;
- emissions omit power, PUE, energy, and time conversion;
- the model lacks GPU compatibility, deadlines, residency, latency, budgets, and meaningful interruptibility;
- Redis location is hardcoded.

**Decision:** replace the v2 core with CP-SAT, integer units, hard constraints, named baselines, normalized objectives, and an independent validator.

### AI agents

`agents/agent_prompts.py` contains prompt templates and mock coordinator outputs. It describes forecasting, bidding, dispatch, and autonomous behavior that is not implemented.

**Decision:** v2 AI explains a validated result using structured outputs. Forecasting and autonomous dispatch are later phases, not launch claims.

### Demo script

`demo.py` scripts outcomes such as large GPU migrations, zero downtime, 47ms response, hourly savings, and uptime. It is presentation logic, not system evidence.

**Decision:** replace scripted outcomes with versioned scenarios and reproducible results.

### CI and infrastructure

The workflow and compose files reference missing assets:

- API/solver/agent test directories;
- integration and performance tests;
- Kubernetes overlays;
- Grafana provisioning directories;
- OpenTelemetry collector config;
- release metadata such as `api/pyproject.toml`.

`docker compose config` parses, but warns about an obsolete version field and missing environment variables. Parsing does not prove referenced mounted files or services work.

**Decision:** reduce CI to implemented checks, then add gates as real code lands. Do not preserve aspirational jobs that always fail or never run.

### README and claims

The current README claims or implies large savings, emissions reductions, high request throughput, sub-100ms optimization, 99.99% uptime, security certifications/readiness, Kubernetes operations, private networking, billing, and marketplace onboarding without repository evidence.

**Decision:** rewrite the README after the vertical slice works. Public claims require a scenario, baseline, units, method, machine, commit, and timestamp.

### Domain

The repository `CNAME` contains `gridsynapse.io`, but a direct DNS lookup on July 17, 2026 returned no apex A record. Renewing the domain restores ownership, not hosting or HTTPS.

**Decision:** deploy the Next.js console and container API first, then configure DNS and verify HTTPS. Do not point the v2 product at GitHub Pages.

## 3. Official ecosystem research

### Kubernetes Kueue

Kueue is a Kubernetes-native job queueing and admission layer. Its current model emphasizes priorities, queues, resource flavors, quotas, cohorts/fair sharing, preemption, admission checks, topology-aware scheduling, and integrations with Kubernetes Jobs, Kubeflow, Ray, JobSet, and Pods.

**Product lesson:** GridSynapse should complement the scheduler by creating a policy-backed placement recommendation, not pretend to replace all queue and cluster orchestration.

Source: <https://kueue.sigs.k8s.io/>

### NVIDIA DCGM Exporter

DCGM Exporter exposes GPU telemetry through Prometheus and integrates with the NVIDIA GPU Operator.

**Product lesson:** real utilization, health, memory, temperature, and job-level GPU signals should come through a telemetry adapter rather than browser-generated meters.

Source: <https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/dcgm-exporter.html>

### OpenCost and FinOps FOCUS

OpenCost provides current and historical Kubernetes cost allocation, including GPU allocation and AI inference cost tracking. FOCUS provides a vendor-neutral schema for cloud, SaaS, and data-center cost and usage data.

**Product lesson:** GridSynapse should ingest normalized cost evidence and optimize placement. It should not rebuild a complete billing or cost-allocation product in v2.

Sources: <https://www.opencost.io/> and <https://focus.finops.org/>

### Carbon Aware SDK

The Green Software Foundation Carbon Aware SDK standardizes carbon-intensity access and supports choosing when or where software runs based on emissions.

**Product lesson:** time/location shifting is a credible GridSynapse capability for flexible workloads, but carbon signals need source, unit, timestamp, freshness, and fallback policy.

Source: <https://github.com/Green-Software-Foundation/carbon-aware-sdk>

### EIA Open Data

The US Energy Information Administration exposes official energy datasets and APIs, including balancing-authority data that can support timestamped snapshots.

**Product lesson:** use a pinned EIA-derived snapshot for the first public methodology. Do not call a changing live feed during a portfolio demo unless failure and stale states are designed.

Source: <https://www.eia.gov/opendata/>

### OR-Tools CP-SAT

CP-SAT is the appropriate OR-Tools backend for integer constraint programming and scheduling.

**Product lesson:** jobs, GPU counts, time slots, and capacity decisions must use integer-safe modeling. Solver output still requires independent validation.

Source: <https://developers.google.com/optimization/cp/cp_solver>

### NVIDIA Run:ai

Run:ai is positioned as an enterprise AI workload and GPU orchestration platform across public, private, hybrid, and on-premises environments.

**Product lesson:** "GPU orchestration" is already an established category with strong incumbents. GridSynapse should differentiate on auditable multi-objective placement, source-backed cost/carbon comparison, and explanation rather than claiming a broader orchestration platform before it exists.

Source: <https://www.nvidia.com/en-us/software/run-ai/>

## 4. Competitive product conclusion

The market does not need another dashboard that says GPUs are expensive. The differentiated v2 wedge is:

> A decision layer that compares feasible placements across cost, carbon, delay, and capacity risk, shows the baseline, explains the tradeoffs, and preserves operator approval.

GridSynapse should integrate with tools that already own adjacent layers:

- Kueue/Ray/Kubeflow own workload and queue state;
- DCGM owns GPU telemetry;
- OpenCost/FOCUS own cost normalization;
- carbon providers own emissions signals;
- GridSynapse owns cross-signal recommendation, comparison, explanation, and approval evidence.

## 5. UX research conclusion

The primary user is an operator, so the console must prioritize decisions over marketing:

1. What needs attention?
2. What constraints matter?
3. What options are feasible?
4. What does the selected objective change?
5. What improved versus the baseline?
6. Why should I trust it?
7. What can I approve or export?

The legacy dashboard gives equal visual weight to many metrics and marketplace concepts. V2 should use progressive disclosure: queue and decision first, technical evidence and source details after the result.

## 6. What GridSynapse should not claim yet

- universal cost or carbon savings;
- autonomous live workload migration;
- guaranteed latency or uptime;
- support for a production scheduler before an adapter exists;
- production-grade multi-tenancy/security/compliance;
- live national-grid optimization;
- forecasting accuracy;
- marketplace liquidity or partner revenue.

## 7. What GridSynapse can credibly show first

- a real CP-SAT schedule for flexible AI workloads;
- hard constraints and explicit infeasibility;
- cost and emissions calculated from visible inputs;
- baseline-versus-optimized results;
- objective profiles that produce different tradeoffs;
- AI explanation grounded in the validated result;
- human approval and export;
- adapter interfaces mapped to current ecosystem tools;
- reproducible tests and benchmark artifacts.

## 8. Final recommendation

Build the smallest complete operator loop before adding live providers:

`versioned scenario -> real optimizer -> validated result -> clear console -> explanation -> approval/export`

That loop is enough to show meaningful skill across product strategy, optimization, backend contracts, AI guardrails, FinOps/carbon modeling, institutional UX, testing, and deployment. Live integrations then become evidence-backed extensions rather than a substitute for core product correctness.
