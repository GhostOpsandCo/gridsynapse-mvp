# GridSynapse v2 Delivery Plan

## 1. Delivery objective

Build a public, portfolio-ready AI Compute Optimization Console whose central result is produced by a real, tested optimizer and can be reproduced from a versioned scenario.

The plan deliberately avoids building every integration at once. The critical path is:

```text
Contracts
  -> deterministic baseline and optimizer
  -> independent validation
  -> FastAPI endpoint
  -> operator console
  -> explanation layer
  -> measured evidence
  -> deployment
```

## 2. Expert workstreams and assignments

These are the agent/engineer briefs. Each workstream owns a narrow output and cannot redefine shared contracts independently.

| Workstream | Expert role | Primary assignment | Required evidence |
| --- | --- | --- | --- |
| Product and architecture | Senior PM / solutions architect | Protect ICP, scope, acceptance criteria, contracts, and claims | PRD traceability checklist |
| Optimization core | Optimization SWE | CP-SAT model, baseline, validator, scenario tests, benchmarks | invariant tests + benchmark artifact |
| API and data | Backend SWE | FastAPI v2 routes, repositories, adapter interfaces, provenance | contract tests + OpenAPI snapshot |
| Operator console | Senior frontend/UX engineer | Next.js workflow, tables, timeline, objective controls, result comparison | browser QA + screenshots |
| FinOps and telemetry | FinOps/data engineer | cost units, carbon units, source freshness, adapter mappings | source mapping + calculation tests |
| AI explanation | AI solutions engineer | structured explanation schema, deterministic fallback, evals | schema/evidence eval report |
| Quality and operations | QA/SRE | CI, integration tests, load tests, observability, deploy checks | release checklist + smoke results |
| Brand and evidence | Product marketer/brand designer | portfolio case study, claim wording, recording, visual consistency | claim ledger + final case study |

### Coordination rule

The product/architecture owner approves changes to:

- canonical schemas;
- units and formulas;
- hard constraints;
- baseline policy;
- public claims;
- execution boundary.

## 3. Phase 0: Stabilize and remove false confidence

**Target:** 1-2 working days
**Owners:** Product/architecture, QA/SRE

### Tasks

- Freeze legacy dashboard as a visual reference.
- Add an explicit legacy/unsupported-claims inventory.
- Remove broken CI jobs or mark them non-blocking until their paths exist.
- Create the v2 package structure and development commands.
- Add schema validation for the reference scenario.
- Make Redis optional for local API startup.
- Establish Python and Node versions.

### Exit gate

- Clean local bootstrap from a fresh checkout.
- CI runs only real checks against real paths.
- Reference JSON validates.
- No public deployment points at mock optimization output.

## 4. Phase 1: Optimization core

**Target:** 5-7 working days
**Owner:** Optimization SWE
**Dependencies:** Contracts complete

### Tasks

1. Implement Pydantic request/result models.
2. Implement shared unit conversion functions.
3. Implement deterministic baseline scheduler.
4. Implement CP-SAT placement variables for valid pool/start combinations only.
5. Implement hard constraints.
6. Implement normalized objective components and four profiles.
7. Implement aggregate and per-placement calculations.
8. Implement independent result validator.
9. Add infeasibility reasons.
10. Add golden and property-based tests.

### Required tests

- exactly one placement per scheduled workload;
- no capacity overlap;
- GPU compatibility;
- earliest start/deadline;
- residency and latency;
- budget;
- duration ceiling, never truncation;
- identical input determinism;
- baseline/optimized calculation parity;
- objective profile changes result on a designed scenario;
- infeasible request produces stable reason codes.

### Exit gate

- Reference scenario produces a validated result.
- All invariants pass outside the solver.
- No GLOP backend remains in v2.
- Benchmark runner records scenario, machine, commit, p50, and p95.

## 5. Phase 2: API and adapter-ready data layer

**Target:** 4-5 working days
**Owners:** Backend SWE, FinOps/data engineer
**Dependencies:** Phase 1 result contract

### Tasks

- Implement `/api/v2/scenarios`, validation, workloads, pools, data health, and optimizations.
- Persist recommendation metadata and approval state.
- Add source/freshness validation.
- Implement JSON, static-pricing, and carbon-snapshot adapters.
- Add Prometheus metrics and structured logs.
- Add rate and scenario-size limits.
- Generate OpenAPI and TypeScript contract bindings.

### Exit gate

- API calls the real optimizer.
- API result validates against the result schema.
- Stale/missing required data produces actionable errors.
- OpenAPI, Python models, and TypeScript contracts agree.
- A changed input invalidates an approval.

## 6. Phase 3: Operator console

**Target:** 7-10 working days
**Owner:** Senior frontend/UX engineer
**Dependencies:** Stable API contract

### Build order

1. App shell and Operator Brief.
2. Workload Queue.
3. Resource Meter.
4. Objective and hard-constraint review.
5. Optimization run state.
6. Baseline-versus-optimized result.
7. Placement timeline.
8. Data provenance and warnings.
9. Approval and export.

### UX rules

- One primary action per screen.
- Inputs precede decisions; decisions precede evidence; evidence precedes approval.
- Hard constraints never look like objective preferences.
- Values never animate randomly.
- Units are visible in headers and tooltips.
- Empty, loading, stale, infeasible, error, and approved states are designed.
- Fixed-format timelines and meters use stable dimensions.

### Exit gate

- A new operator completes the reference workflow without instructions.
- Desktop and mobile have no horizontal overflow.
- Every visible control changes observable state.
- Browser console is clean.
- UI values match the API response exactly.

## 7. Phase 4: AI explanation and advisor-style guidance

**Target:** 3-5 working days
**Owner:** AI solutions engineer
**Dependencies:** Stable, validated optimization result

### Tasks

- Implement deterministic explanation templates first.
- Add optional LLM provider behind `EXPLANATION_PROVIDER=template|llm`.
- Require structured output validation.
- Add numerical-grounding checks.
- Add evidence/source references.
- Add operator feedback: useful / missing context / incorrect.
- Log prompt, model, schema, and validation versions without customer secrets.

### Eval set

- cost-first result;
- carbon-first result;
- SLA-constrained result;
- stale source warning;
- infeasible workload;
- no-change result;
- result with baseline infeasible.

### Exit gate

- AI cannot introduce unsupported pools, values, or actions.
- Invalid output falls back cleanly.
- Explanation is traceable to result fields.
- Schedule remains byte-for-byte unchanged when explanation mode changes.

## 8. Phase 5: Evidence, deployment, and portfolio case study

**Target:** 4-6 working days
**Owners:** QA/SRE, brand/evidence
**Dependencies:** Phases 1-4

### Tasks

- Run scenario suite and benchmark matrix.
- Perform desktop/mobile visual QA.
- Add accessibility pass.
- Deploy API staging and web preview.
- Configure `gridsynapse.io` only after production smoke passes.
- Create a before/after case study.
- Record 60-90 second workflow video.
- Publish architecture diagram and claim methodology.

### Portfolio package

- Live product.
- Short product walkthrough.
- "Legacy to v2" architecture comparison.
- Solver invariants and benchmark summary.
- Screenshots of workload queue, resource matrix, optimized timeline, and explanation.
- Concise case study: problem, constraints, decisions, implementation, evidence.

### Exit gate

- Production domain and API pass smoke tests.
- Every public numerical claim appears in the claim ledger with evidence.
- No synthetic value is presented as live telemetry.
- README matches implemented behavior.

## 9. Product backlog by priority

### P0: required for credible demo

- CP-SAT solver.
- Correct units and formulas.
- Baseline scheduler.
- Independent validator.
- Real optimize API.
- Versioned scenario and provenance.
- Operator workflow and result comparison.
- Human approval/export.
- Automated tests.

### P1: differentiating portfolio value

- Structured AI explanation.
- Multiple objective profiles.
- Infeasibility diagnosis.
- Timestamped carbon snapshot adapter.
- Benchmark/evidence page.
- 60-90 second recording.

### P2: pilot readiness

- Kueue read adapter.
- OpenCost/FOCUS import.
- DCGM telemetry import.
- Postgres recommendation history.
- OIDC/RBAC.
- Read-only scheduler export.

### P3: later commercial depth

- Forecasting.
- What-if scenarios.
- Multi-cluster capacity reservation.
- Live carbon-aware shifting.
- Customer-specific policy profiles.
- Approval integration and controlled execution.

## 10. PR and review sequence

Keep changes reviewable and avoid one giant rebuild:

1. `v2/contracts-and-scenarios`
2. `v2/cp-sat-core`
3. `v2/baseline-validator`
4. `v2/api-vertical-slice`
5. `v2/operator-shell`
6. `v2/result-timeline`
7. `v2/explanations`
8. `v2/evidence-and-deploy`

Each PR includes tests and a short "claims changed" note.

## 11. Quality gates

### Contract gate

- JSON schemas valid.
- Example request/result valid.
- Python and TypeScript generation reproducible.

### Solver gate

- All invariants pass.
- Golden scenarios pass.
- Independent validator passes.
- No floating-point decision variables.

### UI gate

- Critical workflow browser-tested.
- No fake controls.
- No random data.
- Desktop/mobile screenshots approved.

### Release gate

- Type/lint/test/build green.
- Benchmark recorded.
- Staging smoke green.
- Production smoke green.
- Claim ledger reviewed.

## 12. Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Optimizer looks smart but violates real constraints | Critical | independent validator and golden scenarios |
| Mixed units create misleading tradeoffs | Critical | integer units and shared calculators |
| Savings claims use an unfair baseline | High | named baseline policy and infeasible disclosure |
| Live data integrations delay demo | High | deterministic scenario adapters first |
| AI hallucinates rationale | High | structured result-only context, validation, fallback |
| Dashboard becomes dense and decorative | Medium | guided workflow, one primary action, progressive disclosure |
| Domain is renewed but not routed | Medium | deploy first, then set DNS and verify HTTPS |
| Legacy CI creates false confidence | High | replace jobs with real path-based checks |
| OR-Tools container exceeds serverless limits | Medium | deploy API on a long-running container platform |

## 13. Go/no-go decisions

### Go to public demo when

- the real optimizer drives every result;
- reference scenario and invariants pass;
- claims are scenario-backed;
- synthetic data is labeled;
- execution remains read-only;
- production smoke passes.

### Do not go when

- the optimize endpoint still returns mock values;
- values are randomly animated;
- the baseline is undefined;
- infeasible workloads disappear silently;
- AI output can modify allocations;
- the README overstates implementation or certifications.

## 14. Estimated delivery range

For one strong engineer using focused AI assistance, a polished vertical-slice public demo is realistically **4-6 weeks**. A pilot with live Kueue, cost, GPU telemetry, identity, and approval integrations is a separate **6-12+ week** effort depending on customer access and infrastructure complexity.

The portfolio should ship the vertical slice first. It proves product judgment, optimization architecture, AI guardrails, financial/carbon modeling, and polished operator UX without pretending the production integrations already exist.
