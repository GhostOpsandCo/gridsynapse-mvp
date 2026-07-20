"use client";

import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  Cloud,
  Download,
  FileCode2,
  Gauge,
  Info,
  ListChecks,
  Play,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  XCircle,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { duration, labelize, money, number, shortTime } from "@/lib/format";
import type {
  DataHealth,
  DecisionHistoryItem,
  ExecutableWorkloadSpec,
  Explanation,
  LiveMarketSnapshot,
  ObjectiveProfile,
  OptimizationRequest,
  OptimizationResult,
  PersistenceStatus,
  Placement,
  ProcurementAction,
  ProcurementPlan,
  ProcurementStatus,
  ResourcePool,
} from "@/lib/types";

const SCENARIO_ID = "reference-cost-carbon-tradeoff-v1";

type View = "queue" | "decision" | "procurement" | "runs" | "outcomes";

const profiles: Record<
  ObjectiveProfile,
  { label: string; detail: string; weights: OptimizationRequest["policy"]["weights"] }
> = {
  cost: {
    label: "Cost first",
    detail: "Minimize catalog spend while keeping every hard workload constraint.",
    weights: { costBps: 6500, carbonBps: 1000, delayBps: 1500, riskBps: 1000 },
  },
  balanced: {
    label: "Balanced",
    detail: "Balance cost, carbon, start delay, and modeled capacity risk.",
    weights: { costBps: 4000, carbonBps: 2500, delayBps: 2000, riskBps: 1500 },
  },
  carbon: {
    label: "Carbon first",
    detail: "Prefer lower-emissions windows and regions within policy.",
    weights: { costBps: 1500, carbonBps: 6000, delayBps: 1500, riskBps: 1000 },
  },
  sla: {
    label: "Deadline first",
    detail: "Prioritize early starts and higher modeled availability.",
    weights: { costBps: 2000, carbonBps: 500, delayBps: 5500, riskBps: 2000 },
  },
};

const navItems: Array<{ id: View; label: string; icon: React.ReactNode }> = [
  { id: "queue", label: "Queue", icon: <ListChecks size={18} /> },
  { id: "decision", label: "Decision", icon: <Sparkles size={18} /> },
  { id: "procurement", label: "Procurement", icon: <ClipboardCheck size={18} /> },
  { id: "runs", label: "Runs", icon: <Play size={18} /> },
  { id: "outcomes", label: "Outcomes", icon: <ReceiptText size={18} /> },
];

const lifecycle: ProcurementStatus[] = [
  "created",
  "dry_run_ready",
  "approved_for_launch",
  "provisioning",
  "running",
  "completed",
  "reconciled",
];

function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "green" | "blue" | "amber" | "red";
}) {
  return <span className={`status-badge status-badge--${tone}`}>{children}</span>;
}

function InfoTip({ text }: { text: string }) {
  return (
    <span className="info-tip" title={text} aria-label={text}>
      <Info size={14} />
    </span>
  );
}

function SectionHeader({
  eyebrow,
  title,
  detail,
  aside,
}: {
  eyebrow?: string;
  title: string;
  detail?: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        <h2>{title}</h2>
        {detail ? <p>{detail}</p> : null}
      </div>
      {aside ? <div className="section-header__aside">{aside}</div> : null}
    </div>
  );
}

function providerForPlacement(scenario: OptimizationRequest, placement: Placement) {
  return scenario.resourcePools.find((pool) => pool.id === placement.poolId);
}

function workloadForPlacement(scenario: OptimizationRequest, placement: Placement) {
  return scenario.workloads.find((workload) => workload.id === placement.workloadId);
}

function sourceTruth(health: DataHealth | null) {
  const sources = health?.sources ?? [];
  const observed = sources.filter((source) => source.sourceType !== "estimated");
  const modeled = sources.filter((source) => source.sourceType === "estimated");
  return { observed, modeled, stale: sources.filter((source) => source.stale) };
}

function requestedGpuHours(scenario: OptimizationRequest) {
  return scenario.workloads.reduce(
    (sum, workload) => sum + workload.gpuCount * (workload.durationMinutes / 60),
    0,
  );
}

function allDeadlinesMet(scenario: OptimizationRequest, placements: Placement[]) {
  return placements.every((placement) => {
    const workload = workloadForPlacement(scenario, placement);
    return workload
      ? new Date(placement.end).getTime() <= new Date(workload.deadline).getTime()
      : false;
  });
}

function toneForStatus(status: ProcurementStatus) {
  if (["reconciled", "completed", "dry_run_ready"].includes(status)) return "green" as const;
  if (["approved_for_launch", "provisioning", "running"].includes(status)) return "blue" as const;
  if (status === "verification_failed") return "red" as const;
  return "neutral" as const;
}

function QueueView({
  scenario,
  result,
  profile,
  setProfile,
  running,
  onOptimize,
  onOpenDecision,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  profile: ObjectiveProfile;
  setProfile: (profile: ObjectiveProfile) => void;
  running: boolean;
  onOptimize: () => void;
  onOpenDecision: () => void;
}) {
  const gpuHours = requestedGpuHours(scenario);
  const urgent = scenario.workloads.filter(
    (workload) => new Date(workload.deadline).getTime() - Date.now() < 24 * 60 * 60 * 1000,
  ).length;

  return (
    <div className="view-stack">
      <section className="operations-brief">
        <div>
          <span className="eyebrow eyebrow--green">Compute buying queue</span>
          <h2>{scenario.workloads.length} workloads are ready for a validated placement decision.</h2>
          <p>
            GridSynapse converted {number(gpuHours, 0)} requested GPU-hours into a comparable
            provider decision with deadlines, spend, and evidence attached.
          </p>
        </div>
        <button className="primary-button primary-button--green" onClick={onOpenDecision} type="button">
          Review recommendation <ArrowRight size={17} />
        </button>
      </section>

      <section className="decision-metrics" aria-label="Queue summary">
        <div><span>Queued workloads</span><strong>{scenario.workloads.length}</strong><small>{urgent} due within 24 hours</small></div>
        <div><span>Requested compute</span><strong>{number(gpuHours, 0)} GPU-hours</strong><small>{scenario.workloads[0]?.gpuType ?? "GPU"} requirement</small></div>
        <div><span>Catalog baseline</span><strong>{money(result.baseline.totalCostUsd)}</strong><small>Current placement estimate</small></div>
        <div><span>Potential savings</span><strong className="positive">{money(Math.max(0, -result.deltas.costUsd))}</strong><small>Before account pricing</small></div>
      </section>

      <section className="panel queue-panel">
        <SectionHeader
          title="Workload queue"
          detail="The queue shows what must run, when it is due, and the hard constraint GridSynapse must protect."
          aside={<StatusBadge tone="green">Validated inputs</StatusBadge>}
        />
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Workload</th><th>Compute</th><th>Duration</th><th>Deadline (UTC)</th><th>Priority</th><th>Status</th></tr></thead>
            <tbody>{scenario.workloads.map((workload) => (
              <tr key={workload.id}>
                <td data-label="Workload"><strong>{workload.name}</strong><small>{labelize(workload.workloadType)}</small></td>
                <td data-label="Compute"><strong>{workload.gpuCount} x {workload.gpuType}</strong><small>{number(workload.gpuCount * workload.durationMinutes / 60, 0)} GPU-hours</small></td>
                <td data-label="Duration"><strong>{duration(workload.durationMinutes)}</strong><small>{workload.interruptible ? "Interruptible" : "Continuous"}</small></td>
                <td data-label="Deadline"><strong>{shortTime(workload.deadline)}</strong><small>{new Date(workload.deadline).toLocaleDateString()}</small></td>
                <td data-label="Priority"><strong>{workload.priority}</strong><small>out of 100</small></td>
                <td data-label="Status"><StatusBadge tone="green">Ready</StatusBadge><small>{workload.allowedRegions.length} allowed regions</small></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <section className="panel policy-strip">
        <div>
          <span className="eyebrow">Buying objective</span>
          <h2>{profiles[profile].label}</h2>
          <p>{profiles[profile].detail}</p>
        </div>
        <div className="segmented-control" role="group" aria-label="Optimization objective">
          {(Object.keys(profiles) as ObjectiveProfile[]).map((key) => (
            <button className={profile === key ? "is-active" : ""} key={key} onClick={() => setProfile(key)} type="button">{profiles[key].label}</button>
          ))}
        </div>
        <button className="primary-button" disabled={running} onClick={onOptimize} type="button">
          {running ? <RefreshCw className="spin" size={16} /> : <Zap size={16} />}
          {running ? "Recalculating" : "Recalculate"}
        </button>
      </section>
    </div>
  );
}

function DecisionView({
  scenario,
  result,
  explanation,
  health,
  updatingApproval,
  onApprove,
  onRevision,
  onOpenProcurement,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  explanation: Explanation | null;
  health: DataHealth | null;
  updatingApproval: boolean;
  onApprove: () => void;
  onRevision: () => void;
  onOpenProcurement: () => void;
}) {
  const truth = sourceTruth(health);
  const deadlinesMet = allDeadlinesMet(scenario, result.optimized.placements);
  const isApproved = result.approval.status === "approved";

  return (
    <div className="view-stack">
      <section className="decision-hero">
        <div>
          <span className="eyebrow eyebrow--green">Validated compute decision</span>
          <h2>Buy the required compute for {money(result.optimized.totalCostUsd)} and save {money(Math.max(0, -result.deltas.costUsd))}.</h2>
          <p>{explanation?.summary ?? "GridSynapse is preparing the decision rationale."}</p>
        </div>
        {isApproved ? (
          <button className="primary-button primary-button--green" onClick={onOpenProcurement} type="button">Build procurement plan <ArrowRight size={17} /></button>
        ) : (
          <button className="primary-button primary-button--green" disabled={updatingApproval} onClick={onApprove} type="button"><CheckCircle2 size={17} />Approve decision</button>
        )}
      </section>

      <section className="decision-metrics">
        <div><span>Recommended cost</span><strong>{money(result.optimized.totalCostUsd)}</strong><small>Public catalog estimate</small></div>
        <div><span>Savings</span><strong className="positive">{money(Math.max(0, -result.deltas.costUsd))}</strong><small>{number(Math.abs(result.deltas.costPercent), 1)}% vs. baseline</small></div>
        <div><span>Deadline coverage</span><strong className={deadlinesMet ? "positive" : "tradeoff"}>{result.optimized.placements.length}/{scenario.workloads.length}</strong><small>{deadlinesMet ? "All modeled deadlines met" : "Review required"}</small></div>
        <div><span>Decision status</span><strong>{labelize(result.approval.status)}</strong><small>Human-controlled approval</small></div>
      </section>

      <section className="panel">
        <SectionHeader title="Recommended placement" detail="Each row ties a workload to the proposed provider, timing, and estimated value." />
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Workload</th><th>Provider</th><th>Region</th><th>Start</th><th>GPU-hours</th><th>Est. cost</th><th>Evidence</th></tr></thead>
            <tbody>{result.optimized.placements.map((placement) => {
              const workload = workloadForPlacement(scenario, placement);
              const pool = providerForPlacement(scenario, placement);
              return (
                <tr key={placement.workloadId}>
                  <td data-label="Workload"><strong>{workload?.name}</strong><small>{workload?.workloadType ? labelize(workload.workloadType) : placement.workloadId}</small></td>
                  <td data-label="Provider"><span className="provider-cell"><Server size={17} /><span><strong>{pool?.provider}</strong><small>{pool?.gpuType}</small></span></span></td>
                  <td data-label="Region"><strong>{pool?.region}</strong><small>{pool?.cluster}</small></td>
                  <td data-label="Start"><strong>{shortTime(placement.start)}</strong><small>{new Date(placement.start).toLocaleDateString()}</small></td>
                  <td data-label="GPU-hours"><strong>{number(placement.gpuCount * ((new Date(placement.end).getTime() - new Date(placement.start).getTime()) / 3_600_000), 0)}</strong><small>{placement.gpuCount} GPUs</small></td>
                  <td data-label="Est. cost"><strong>{money(placement.costUsd)}</strong><small>planning estimate</small></td>
                  <td data-label="Evidence"><StatusBadge tone="amber">Modeled capacity</StatusBadge><small>catalog price observed</small></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </section>

      <section className="decision-support-grid">
        <article className="panel">
          <SectionHeader title="Why this decision" detail="The operator rationale stays attached to the recommendation." />
          <div className="check-list">{(explanation?.decisionFactors ?? []).map((item) => <span key={item}><CheckCircle2 size={15} />{item}</span>)}</div>
          {(explanation?.tradeoffs ?? []).length ? <div className="warning-line"><AlertTriangle size={16} />{explanation?.tradeoffs.join(" ")}</div> : null}
        </article>
        <article className="panel">
          <SectionHeader title="Evidence boundary" aside={<StatusBadge tone={truth.stale.length ? "amber" : "green"}>{truth.stale.length ? "Review stale input" : "Sources current"}</StatusBadge>} />
          <div className="evidence-compact">
            <span><CheckCircle2 size={16} /><strong>{truth.observed.length} observed inputs</strong><small>Public price and forecast records</small></span>
            <span><AlertTriangle size={16} /><strong>{truth.modeled.length} planning estimates</strong><small>Capacity is not reservable inventory</small></span>
            <span><ShieldCheck size={16} /><strong>Human approval required</strong><small>No purchase or provider call</small></span>
          </div>
        </article>
      </section>

      <section className="decision-actions panel">
        <div><span className="eyebrow">Operator checkpoint</span><h2>{isApproved ? "Decision approved. Build the inspectable compute commitment." : "Approve this exact recommendation before procurement planning."}</h2></div>
        <div className="compact-actions">
          {!isApproved ? <button className="secondary-button secondary-button--danger" disabled={updatingApproval} onClick={onRevision} type="button"><RotateCcw size={16} />Request revision</button> : null}
          {isApproved ? <button className="primary-button" onClick={onOpenProcurement} type="button">Open procurement <ArrowRight size={16} /></button> : <button className="primary-button" disabled={updatingApproval} onClick={onApprove} type="button"><Check size={16} />Approve decision</button>}
        </div>
      </section>
    </div>
  );
}

function CommitmentHeader({ plan }: { plan: ProcurementPlan }) {
  return (
    <section className="commitment-header">
      <div><span className="eyebrow eyebrow--green">Validated compute commitment</span><h2>{plan.procurementPlanId}</h2><p>{plan.placements.length} placements / {money(plan.estimatedTotalCostUsd)} estimated / {money(plan.maxSpendUsd)} ceiling</p></div>
      <StatusBadge tone={toneForStatus(plan.status)}>{labelize(plan.status)}</StatusBadge>
    </section>
  );
}

function ProcurementView({
  result,
  plan,
  busy,
  onCreate,
  onVerify,
  onApproveSimulation,
  onOpenDecision,
  onOpenRuns,
  onCopy,
  onDownload,
}: {
  result: OptimizationResult;
  plan: ProcurementPlan | null;
  busy: boolean;
  onCreate: () => void;
  onVerify: () => void;
  onApproveSimulation: () => void;
  onOpenDecision: () => void;
  onOpenRuns: () => void;
  onCopy: () => void;
  onDownload: () => void;
}) {
  if (result.approval.status !== "approved") {
    return (
      <div className="view-stack"><section className="locked-state panel"><ShieldCheck size={28} /><span className="eyebrow">Procurement locked</span><h2>Approve the exact compute decision first.</h2><p>GridSynapse will not create an inspectable SkyPilot planning artifact from an unapproved recommendation.</p><button className="primary-button" onClick={onOpenDecision} type="button">Review decision <ArrowRight size={16} /></button></section></div>
    );
  }
  if (!plan) {
    return (
      <div className="view-stack">
        <section className="operations-brief"><div><span className="eyebrow eyebrow--green">Procurement planning</span><h2>Turn the approved decision into an inspectable compute commitment.</h2><p>The commitment binds the approved input hash, workload commands, spend ceiling, market evidence, and SkyPilot manifest. It does not launch compute.</p></div><button className="primary-button primary-button--green" disabled={busy} onClick={onCreate} type="button"><FileCode2 size={17} />{busy ? "Building" : "Build commitment"}</button></section>
        <section className="boundary-grid">
          <div><CheckCircle2 size={18} /><strong>Approved decision</strong><small>Exact input hash attached</small></div>
          <div><SquareTerminal size={18} /><strong>SkyPilot planning artifact</strong><small>Container image and command included</small></div>
          <div><ShieldCheck size={18} /><strong>Spend ceiling</strong><small>Estimate must remain within limit</small></div>
          <div><AlertTriangle size={18} /><strong>Launch disabled</strong><small>No credentials or provider call</small></div>
        </section>
      </div>
    );
  }

  const verification = plan.verification;
  return (
    <div className="view-stack">
      <CommitmentHeader plan={plan} />
      <section className="decision-metrics">
        <div><span>Estimated cost</span><strong>{money(plan.estimatedTotalCostUsd)}</strong><small>Public catalog planning value</small></div>
        <div><span>Spend ceiling</span><strong>{money(plan.maxSpendUsd)}</strong><small>Hard verification check</small></div>
        <div><span>Placements</span><strong>{plan.placements.length}</strong><small>Executable workload specs</small></div>
        <div><span>Live launch</span><strong className="tradeoff">Disabled</strong><small>Portfolio safety lock</small></div>
      </section>

      <section className="panel">
        <SectionHeader title="Commitment placements" detail="Planning evidence and executable workload details are packaged together." />
        <div className="commitment-placement-grid">{plan.placements.map((placement) => (
          <article key={placement.placementId}>
            <div><span className="provider-icon"><Server size={17} /></span><span><strong>{placement.provider}</strong><small>{placement.region} / {placement.gpuType}</small></span></div>
            <dl><div><dt>Workload</dt><dd>{placement.workloadId}</dd></div><div><dt>Image</dt><dd>{placement.workloadSpec.containerImage}</dd></div><div><dt>Command</dt><dd>{placement.workloadSpec.command.join(" ")}</dd></div><div><dt>Estimated cost</dt><dd>{money(placement.estimatedCostUsd)}</dd></div></dl>
          </article>
        ))}</div>
      </section>

      <section className="panel verification-panel">
        <SectionHeader title="Dry-run verification" detail="Verification checks approval, freshness, executable fields, hash integrity, and spend before lifecycle simulation." aside={verification ? <StatusBadge tone={verification.validForDryRun ? "green" : "red"}>{verification.validForDryRun ? "Dry run ready" : "Blocked"}</StatusBadge> : <StatusBadge>Not verified</StatusBadge>} />
        {verification ? <div className="verification-list">{verification.checks.map((check) => <div key={check.checkId}><span className={check.passed ? "check-dot is-pass" : check.severity === "warning" ? "check-dot is-warning" : "check-dot is-fail"}>{check.passed ? <Check size={12} /> : <AlertTriangle size={12} />}</span><span><strong>{labelize(check.checkId)}</strong><small>{check.message}</small></span></div>)}</div> : <div className="empty-inline"><Gauge size={20} /><span><strong>Verification has not run.</strong><small>The manifest exists, but no lifecycle action is available until checks pass.</small></span></div>}
        <div className="panel-actions">
          <button className="secondary-button" onClick={onCopy} type="button"><FileCode2 size={16} />Copy manifest</button>
          <button className="secondary-button" onClick={onDownload} type="button"><Download size={16} />Download YAML</button>
          {!verification ? <button className="primary-button primary-button--green" disabled={busy} onClick={onVerify} type="button"><ShieldCheck size={16} />{busy ? "Verifying" : "Verify dry run"}</button> : null}
          {plan.status === "dry_run_ready" ? <button className="primary-button" disabled={busy} onClick={onApproveSimulation} type="button"><CheckCircle2 size={16} />Approve simulated run</button> : null}
          {lifecycle.indexOf(plan.status) >= lifecycle.indexOf("approved_for_launch") ? <button className="primary-button" onClick={onOpenRuns} type="button">Open run lifecycle <ArrowRight size={16} /></button> : null}
        </div>
      </section>

      <details className="panel manifest-panel">
        <summary><span><strong>SkyPilot manifest</strong><small>Inspectable SkyPilot planning artifact generated from the approved placements.</small></span><ChevronDown size={18} /></summary>
        <pre>{plan.skypilotManifestYaml}</pre>
      </details>

      <section className="activation-readiness panel">
        <div><span className="eyebrow">Activation readiness</span><h2>Everything required for a live adapter is named; every billable path is off.</h2><p>Turning on a provider later requires an approved adapter, account credentials in a secret manager, executable inventory, account pricing, an organization spend limit, and <code>GRIDSYNAPSE_EXECUTION_ENABLED=true</code>.</p></div>
        <StatusBadge tone="amber">Configuration required</StatusBadge>
      </section>
    </div>
  );
}

function RunsView({
  plan,
  busy,
  onOpenProcurement,
  onTransition,
  onOpenOutcomes,
}: {
  plan: ProcurementPlan | null;
  busy: boolean;
  onOpenProcurement: () => void;
  onTransition: (action: ProcurementAction) => void;
  onOpenOutcomes: () => void;
}) {
  if (!plan || lifecycle.indexOf(plan.status) < lifecycle.indexOf("approved_for_launch")) {
    return <div className="view-stack"><section className="locked-state panel"><Play size={28} /><span className="eyebrow">Run lifecycle locked</span><h2>Verify and approve the compute commitment first.</h2><p>Runs appear only after the dry-run checks pass and the simulation is explicitly approved.</p><button className="primary-button" onClick={onOpenProcurement} type="button">Open procurement <ArrowRight size={16} /></button></section></div>;
  }

  const next: Partial<Record<ProcurementStatus, { action: ProcurementAction; label: string }>> = {
    approved_for_launch: { action: "start_provisioning", label: "Simulate provisioning" },
    provisioning: { action: "mark_running", label: "Mark simulated run active" },
    running: { action: "mark_completed", label: "Complete simulated run" },
  };
  const nextAction = next[plan.status];

  return (
    <div className="view-stack">
      <section className="operations-brief"><div><span className="eyebrow eyebrow--green">Controlled run lifecycle</span><h2>{plan.status === "completed" || plan.status === "reconciled" ? "The simulated workloads completed." : "Follow the planned workload from approval to completion."}</h2><p>Every state change is explicitly labeled as a portfolio simulation. No provider API, reservation, or billable resource is involved.</p></div>{nextAction ? <button className="primary-button primary-button--green" disabled={busy} onClick={() => onTransition(nextAction.action)} type="button"><Play size={16} />{busy ? "Updating" : nextAction.label}</button> : <button className="primary-button" onClick={onOpenOutcomes} type="button">Review outcomes <ArrowRight size={16} /></button>}</section>
      <section className="panel lifecycle-panel">
        <SectionHeader title="Commitment lifecycle" aside={<StatusBadge tone={toneForStatus(plan.status)}>{labelize(plan.status)}</StatusBadge>} />
        <div className="lifecycle-track">{lifecycle.slice(1).map((status, index) => {
          const currentIndex = lifecycle.indexOf(plan.status);
          const statusIndex = lifecycle.indexOf(status);
          const complete = currentIndex >= statusIndex;
          return <div className={complete ? "is-complete" : ""} key={status}><span>{complete ? <Check size={15} /> : index + 1}</span><strong>{labelize(status)}</strong><small>{status === "approved_for_launch" ? "Simulation approval" : status === "reconciled" ? "Estimated vs. simulated actual" : "Portfolio lifecycle state"}</small></div>;
        })}</div>
      </section>
      <section className="panel">
        <SectionHeader title="Planned workloads" detail="The run view makes the operational sequence inspectable before any provider adapter is activated." />
        <div className="run-card-grid">{plan.placements.map((placement) => <article key={placement.placementId}><span><Server size={17} /></span><div><strong>{placement.workloadId}</strong><small>{placement.provider} / {placement.gpuCount} x {placement.gpuType}</small></div><StatusBadge tone={plan.status === "running" ? "blue" : plan.status === "completed" || plan.status === "reconciled" ? "green" : "neutral"}>{plan.status === "running" ? "Running simulation" : plan.status === "completed" || plan.status === "reconciled" ? "Completed" : labelize(plan.status)}</StatusBadge></article>)}</div>
      </section>
      <section className="execution-boundary"><ShieldCheck size={22} /><div><strong>Zero-spend portfolio boundary</strong><p>This lifecycle proves the controls and state machine. It does not claim provider capacity, launch compute, or create a charge.</p></div></section>
    </div>
  );
}

function OutcomesView({
  scenario,
  result,
  plan,
  history,
  persistence,
  busy,
  onReconcile,
  onOpenRuns,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  plan: ProcurementPlan | null;
  history: DecisionHistoryItem[];
  persistence: PersistenceStatus | null;
  busy: boolean;
  onReconcile: () => void;
  onOpenRuns: () => void;
}) {
  if (!plan || lifecycle.indexOf(plan.status) < lifecycle.indexOf("completed")) {
    return <div className="view-stack"><section className="locked-state panel"><ReceiptText size={28} /><span className="eyebrow">Outcomes pending</span><h2>Complete the simulated run to reconcile the commitment.</h2><p>GridSynapse compares the approved estimate with a clearly labeled simulated actual only after completion.</p><button className="primary-button" onClick={onOpenRuns} type="button">Open runs <ArrowRight size={16} /></button></section></div>;
  }
  const reconciliation = plan.reconciliation;
  const savings = result.baseline.totalCostUsd - (reconciliation?.simulatedActualCostUsd ?? plan.estimatedTotalCostUsd);
  const deadlinesMet = allDeadlinesMet(scenario, result.optimized.placements);
  return (
    <div className="view-stack">
      <section className="operations-brief"><div><span className="eyebrow eyebrow--green">Procurement outcome</span><h2>{reconciliation ? `The simulated commitment delivered ${money(savings)} of modeled savings.` : "The commitment is ready for outcome reconciliation."}</h2><p>{reconciliation ? "Estimated and simulated actual values are separated so the result remains honest and auditable." : "Reconcile once to generate the final portfolio receipt. No provider invoice is queried."}</p></div>{!reconciliation ? <button className="primary-button primary-button--green" disabled={busy} onClick={onReconcile} type="button"><ReceiptText size={16} />{busy ? "Reconciling" : "Reconcile outcome"}</button> : null}</section>
      {reconciliation ? <>
        <section className="decision-metrics">
          <div><span>Approved estimate</span><strong>{money(reconciliation.estimatedTotalCostUsd)}</strong><small>Procurement commitment</small></div>
          <div><span>Simulated actual</span><strong>{money(reconciliation.simulatedActualCostUsd)}</strong><small>Not provider billing data</small></div>
          <div><span>Variance</span><strong className={reconciliation.varianceUsd <= 0 ? "positive" : "tradeoff"}>{money(reconciliation.varianceUsd)}</strong><small>{number(reconciliation.variancePercent ?? 0, 1)}% vs. estimate</small></div>
          <div><span>Modeled savings</span><strong className="positive">{money(savings)}</strong><small>vs. catalog baseline</small></div>
        </section>
        <section className="outcome-receipt panel">
          <div><span className="receipt-icon"><CheckCircle2 size={24} /></span><span><span className="eyebrow eyebrow--green">Portfolio receipt</span><h2>Compute commitment reconciled</h2><p>{reconciliation.completedWorkloadCount}/{reconciliation.workloadCount} workloads completed in the deterministic simulation. {deadlinesMet ? "All modeled deadlines were met." : "A deadline exception requires review."}</p></span></div>
          <dl><div><dt>Commitment ID</dt><dd>{plan.procurementPlanId}</dd></div><div><dt>Evidence hash</dt><dd>{plan.verification?.evidenceHash.slice(0, 18)}...</dd></div><div><dt>Reconciliation ID</dt><dd>{reconciliation.reconciliationId}</dd></div><div><dt>Provenance</dt><dd>Deterministic portfolio simulation</dd></div></dl>
        </section>
      </> : null}
      <section className="panel">
        <SectionHeader title="Decision history" detail={persistence?.durable ? "Supabase-backed recommendation and approval records persist across sessions." : "Recommendation and approval records are available for this API session."} aside={<StatusBadge tone={persistence?.durable ? "green" : "amber"}>{history.length} records</StatusBadge>} />
        {history.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Recommendation</th><th>Objective</th><th>Workloads</th><th>Estimated cost</th><th>Value vs. baseline</th><th>Approval</th></tr></thead><tbody>{history.map((item) => <tr key={item.recommendationId}><td data-label="Recommendation"><strong>{item.recommendationId.slice(0, 18)}...</strong><small>{new Date(item.updatedAt).toLocaleString()}</small></td><td data-label="Objective"><strong>{profiles[item.objectiveProfile].label}</strong><small>ranking policy</small></td><td data-label="Workloads"><strong>{item.workloadCount}</strong><small>validated inputs</small></td><td data-label="Estimated cost"><strong>{money(item.totalCostUsd)}</strong><small>catalog estimate</small></td><td data-label="Value vs. baseline"><strong className={item.costDeltaUsd <= 0 ? "positive" : "tradeoff"}>{item.costDeltaUsd <= 0 ? `${money(Math.abs(item.costDeltaUsd))} saved` : `${money(item.costDeltaUsd)} added`}</strong><small>modeled</small></td><td data-label="Approval"><StatusBadge tone={item.approvalStatus === "approved" ? "green" : item.approvalStatus === "revision_required" ? "amber" : "neutral"}>{labelize(item.approvalStatus)}</StatusBadge></td></tr>)}</tbody></table></div> : <div className="empty-inline"><ListChecks size={20} /><span><strong>No decision records yet.</strong><small>Approve a recommendation to create the first record.</small></span></div>}
      </section>
    </div>
  );
}

export function OperatorConsole() {
  const [activeView, setActiveView] = useState<View>("queue");
  const [scenario, setScenario] = useState<OptimizationRequest | null>(null);
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [profile, setProfile] = useState<ObjectiveProfile>("balanced");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [refreshingMarket, setRefreshingMarket] = useState(false);
  const [updatingApproval, setUpdatingApproval] = useState(false);
  const [procurementBusy, setProcurementBusy] = useState(false);
  const [procurementPlan, setProcurementPlan] = useState<ProcurementPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [marketMode, setMarketMode] = useState<"hybrid-live" | "reference">("hybrid-live");
  const [marketGeneratedAt, setMarketGeneratedAt] = useState<string | null>(null);
  const [marketWarnings, setMarketWarnings] = useState<string[]>([]);
  const [persistence, setPersistence] = useState<PersistenceStatus | null>(null);
  const [history, setHistory] = useState<DecisionHistoryItem[]>([]);
  const initialLoad = useRef(false);

  const refreshOperationalState = useCallback(async () => {
    try {
      const [healthResponse, historyResponse] = await Promise.all([api.health(), api.decisionHistory()]);
      setPersistence(healthResponse.persistence);
      setHistory(historyResponse);
    } catch {
      setPersistence({ backend: "unavailable", durable: false, detail: "Decision history status is temporarily unavailable." });
    }
  }, []);

  const optimizeScenario = useCallback(async (baseScenario: OptimizationRequest, targetProfile: ObjectiveProfile) => {
    setRunning(true);
    setError(null);
    setExplanation(null);
    setProcurementPlan(null);
    const request: OptimizationRequest = { ...baseScenario, policy: { ...baseScenario.policy, profile: targetProfile, weights: profiles[targetProfile].weights } };
    try {
      await api.validate(request);
      const nextResult = await api.optimize(request);
      setScenario(request);
      setResult(nextResult);
      if (nextResult.status === "feasible") setExplanation(await api.explanation(nextResult.recommendationId));
      setNotice(`Decision recalculated using the ${profiles[targetProfile].label} objective.`);
      void refreshOperationalState();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Optimization failed");
    } finally {
      setRunning(false);
    }
  }, [refreshOperationalState]);

  const load = useCallback(async (refresh = false) => {
    if (initialLoad.current) setRefreshingMarket(true); else setLoading(true);
    setError(null);
    try {
      try {
        const snapshot: LiveMarketSnapshot = await api.liveMarket(refresh);
        setMarketMode(snapshot.marketMode);
        setMarketGeneratedAt(snapshot.generatedAt);
        setMarketWarnings(snapshot.warnings);
        setScenario(snapshot.scenario);
        setHealth(snapshot.health);
        setProfile(snapshot.scenario.policy.profile);
        await optimizeScenario(snapshot.scenario, snapshot.scenario.policy.profile);
      } catch (marketError) {
        const [referenceScenario, referenceHealth] = await Promise.all([api.scenario(SCENARIO_ID), api.dataHealth(SCENARIO_ID)]);
        setMarketMode("reference");
        setMarketGeneratedAt(null);
        setMarketWarnings([marketError instanceof Error ? marketError.message : "Live market unavailable"]);
        setScenario(referenceScenario);
        setHealth(referenceHealth);
        setProfile(referenceScenario.policy.profile);
        await optimizeScenario(referenceScenario, referenceScenario.policy.profile);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load GridSynapse");
    } finally {
      initialLoad.current = true;
      setLoading(false);
      setRefreshingMarket(false);
    }
  }, [optimizeScenario]);

  useEffect(() => { void load(false); }, [load]);

  const updateApproval = async (status: "approved" | "revision_required") => {
    if (!result) return;
    setUpdatingApproval(true);
    setError(null);
    try {
      const nextResult = await api.approve(result.recommendationId, status);
      setResult(nextResult);
      setProcurementPlan(null);
      setNotice(status === "approved" ? "Decision approved. Procurement planning is now available." : "Revision requested. Change the buying objective and recalculate.");
      void refreshOperationalState();
    } catch (approvalError) {
      setError(approvalError instanceof Error ? approvalError.message : "Approval update failed");
    } finally {
      setUpdatingApproval(false);
    }
  };

  const buildSpecs = (current: OptimizationRequest): ExecutableWorkloadSpec[] => current.workloads.map((workload) => ({
    workloadId: workload.id,
    containerImage: "pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime",
    command: [
      "python",
      "-c",
      `import torch; assert torch.cuda.is_available(), "CUDA is required"; checks=[float((lambda x: (x @ x).mean())(torch.randn((2048, 2048), device=f"cuda:{i}", dtype=torch.float16))) for i in range(torch.cuda.device_count())]; print({"workload":"${workload.id}","gpu_count":torch.cuda.device_count(),"checksums":checks})`,
    ],
    workingDirectory: null,
    environment: { GRIDSYNAPSE_WORKLOAD_TYPE: workload.workloadType },
    secretRefs: [],
    storageMounts: {},
    checkpointUri: workload.checkpointable ? `s3://gridsynapse-checkpoints/${workload.id}` : null,
    retryLimit: workload.checkpointable ? 1 : 0,
    cleanupPolicy: "delete_compute",
  }));

  const createProcurementPlan = async () => {
    if (!scenario || !result) return;
    setProcurementBusy(true); setError(null);
    try {
      const plan = await api.createProcurementPlan({
        recommendationId: result.recommendationId,
        expectedInputHash: result.inputHash,
        requestedBy: "portfolio-operator@gridsynapse.io",
        maxSpendUsd: Math.max(1, Math.ceil(result.optimized.totalCostUsd * 1.2 * 100) / 100),
        workloadSpecs: buildSpecs(scenario),
      });
      setProcurementPlan(plan);
      setNotice("Validated compute commitment created. Run dry-run verification next.");
    } catch (planError) { setError(planError instanceof Error ? planError.message : "Unable to build procurement plan"); }
    finally { setProcurementBusy(false); }
  };

  const verifyProcurementPlan = async () => {
    if (!procurementPlan) return;
    setProcurementBusy(true); setError(null);
    try { const plan = await api.verifyProcurementPlan(procurementPlan.procurementPlanId); setProcurementPlan(plan); setNotice(plan.verification?.validForDryRun ? "Dry-run checks passed. No provider call was made." : "Verification found a blocking issue."); }
    catch (verificationError) { setError(verificationError instanceof Error ? verificationError.message : "Verification failed"); }
    finally { setProcurementBusy(false); }
  };

  const transitionProcurement = async (action: ProcurementAction) => {
    if (!procurementPlan) return;
    setProcurementBusy(true); setError(null);
    try { const plan = await api.transitionProcurementPlan(procurementPlan.procurementPlanId, action); setProcurementPlan(plan); setNotice(`${labelize(plan.status)} recorded in the portfolio simulation.`); }
    catch (transitionError) { setError(transitionError instanceof Error ? transitionError.message : "Lifecycle update failed"); }
    finally { setProcurementBusy(false); }
  };

  const copyManifest = async () => {
    if (!procurementPlan) return;
    await navigator.clipboard.writeText(procurementPlan.skypilotManifestYaml);
    setNotice("SkyPilot manifest copied.");
  };

  const downloadManifest = () => {
    if (!procurementPlan) return;
    const url = URL.createObjectURL(new Blob([procurementPlan.skypilotManifestYaml], { type: "text/yaml" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${procurementPlan.procurementPlanId}.yaml`; anchor.click(); URL.revokeObjectURL(url);
    setNotice("SkyPilot manifest downloaded.");
  };

  const truth = sourceTruth(health);
  const dataStatus = marketMode === "hybrid-live" ? "Public prices + modeled capacity" : "Reference scenario";

  if (loading && !scenario) return <main className="boot-state"><div className="brand-mark"><Boxes size={25} /></div><h1>Loading GridSynapse</h1><p>Reading workloads, market evidence, and policy constraints.</p><RefreshCw className="spin" size={22} /></main>;
  if (!scenario || !result) return <main className="boot-state boot-state--error"><AlertTriangle size={28} /><h1>GridSynapse unavailable</h1><p>{error ?? "A validated recommendation could not be loaded."}</p><button className="primary-button" onClick={() => void load()} type="button"><RefreshCw size={16} />Retry</button></main>;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setActiveView("queue")} type="button"><span className="brand-mark"><Boxes size={21} /></span><span><strong>GridSynapse</strong><small>Compute Procurement</small></span></button>
        <nav aria-label="Product areas">{navItems.map((item) => <button className={activeView === item.id ? "is-active" : ""} key={item.id} onClick={() => setActiveView(item.id)} type="button">{item.icon}<span>{item.label}</span></button>)}</nav>
        <div className="sidebar__footer"><span className={persistence?.durable ? "environment-dot" : "environment-dot environment-dot--amber"} /><div><strong>{persistence?.durable ? "Decision records durable" : "Session records only"}</strong><small>{persistence?.durable ? "Supabase-backed approvals and history" : "Connect Supabase for durable records"}</small></div></div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><h1>GridSynapse</h1><small className="product-subtitle">AI compute procurement control plane</small></div>
          <div className="topbar__context">
            <div><small>Decision evidence</small><strong><span className="environment-dot" />{dataStatus} <InfoTip text={`${truth.observed.length} observed inputs and ${truth.modeled.length} planning estimates`} /></strong></div>
            <div><small>Snapshot</small><strong>{marketGeneratedAt ? new Date(marketGeneratedAt).toLocaleString() : scenario.scenarioId}</strong></div>
            <button className="secondary-button" disabled={refreshingMarket} onClick={() => void load(true)} type="button"><RefreshCw className={refreshingMarket ? "spin" : ""} size={16} />{refreshingMarket ? "Refreshing" : "Refresh evidence"}</button>
          </div>
        </header>

        {error ? <div className="error-banner" role="alert"><AlertTriangle size={17} /><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)} type="button"><XCircle size={17} /></button></div> : null}
        {marketWarnings.length ? <div className="market-warning" role="status"><AlertTriangle size={16} /><span>{marketWarnings.join(" ")}</span></div> : null}
        {notice ? <div className="notice-banner" role="status"><Info size={16} /><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice(null)} type="button"><XCircle size={16} /></button></div> : null}

        {activeView === "queue" ? <QueueView onOpenDecision={() => setActiveView("decision")} onOptimize={() => void optimizeScenario(scenario, profile)} profile={profile} result={result} running={running} scenario={scenario} setProfile={setProfile} /> : null}
        {activeView === "decision" ? <DecisionView explanation={explanation} health={health} onApprove={() => void updateApproval("approved")} onOpenProcurement={() => setActiveView("procurement")} onRevision={() => void updateApproval("revision_required")} result={result} scenario={scenario} updatingApproval={updatingApproval} /> : null}
        {activeView === "procurement" ? <ProcurementView busy={procurementBusy} onApproveSimulation={() => void transitionProcurement("approve_for_launch")} onCopy={() => void copyManifest()} onCreate={() => void createProcurementPlan()} onDownload={downloadManifest} onOpenDecision={() => setActiveView("decision")} onOpenRuns={() => setActiveView("runs")} onVerify={() => void verifyProcurementPlan()} plan={procurementPlan} result={result} /> : null}
        {activeView === "runs" ? <RunsView busy={procurementBusy} onOpenOutcomes={() => setActiveView("outcomes")} onOpenProcurement={() => setActiveView("procurement")} onTransition={(action) => void transitionProcurement(action)} plan={procurementPlan} /> : null}
        {activeView === "outcomes" ? <OutcomesView busy={procurementBusy} history={history} onOpenRuns={() => setActiveView("runs")} onReconcile={() => void transitionProcurement("reconcile")} persistence={persistence} plan={procurementPlan} result={result} scenario={scenario} /> : null}

        <footer className="page-footer"><span>GridSynapse v2 / validated compute commitments</span><span>Portfolio mode: no provider calls or billable execution</span></footer>
      </main>
    </div>
  );
}
