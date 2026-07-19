"use client";

import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Cloud,
  Database,
  Download,
  ExternalLink,
  FileInput,
  FileJson,
  FileSpreadsheet,
  Gauge,
  GitCompareArrows,
  Info,
  Leaf,
  ListChecks,
  PencilLine,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  XCircle,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { duration, labelize, money, number, shortTime, signedPercent } from "@/lib/format";
import type {
  DataHealth,
  DecisionHistoryItem,
  Explanation,
  LiveMarketSnapshot,
  ObjectiveProfile,
  OptimizationRequest,
  OptimizationResult,
  Placement,
  PersistenceStatus,
  ResourcePool,
  Workload,
} from "@/lib/types";

const SCENARIO_ID = "reference-cost-carbon-tradeoff-v1";

type View = "decide" | "workloads" | "market" | "plans" | "quality";

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
  { id: "decide", label: "Recommendation", icon: <Sparkles size={18} /> },
  { id: "workloads", label: "Workloads", icon: <FileJson size={18} /> },
  { id: "market", label: "Market inputs", icon: <Cloud size={18} /> },
  { id: "plans", label: "Review & approve", icon: <ListChecks size={18} /> },
  { id: "quality", label: "Data quality", icon: <Database size={18} /> },
];

function utcInputValue(iso: string) {
  return iso.slice(0, 16);
}

function utcInputToIso(value: string) {
  return `${value}:00.000Z`;
}

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

function percentage(part: number, total: number) {
  return total === 0 ? 0 : (part / total) * 100;
}

function providerOnlyCost(scenario: OptimizationRequest, pool: ResourcePool) {
  return scenario.workloads.reduce(
    (sum, workload) => sum + workload.gpuCount * (workload.durationMinutes / 60) * pool.priceUsdPerGpuHour,
    0,
  );
}

function allDeadlinesMet(scenario: OptimizationRequest, placements: Placement[]) {
  return placements.every((placement) => {
    const workload = workloadForPlacement(scenario, placement);
    return workload ? new Date(placement.end).getTime() <= new Date(workload.deadline).getTime() : false;
  });
}

function DecisionSummary({
  scenario,
  result,
  health,
  onReview,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  health: DataHealth | null;
  onReview: () => void;
}) {
  const providers = Array.from(
    new Set(result.optimized.placements.map((placement) => providerForPlacement(scenario, placement)?.provider).filter(Boolean)),
  ) as string[];
  const truth = sourceTruth(health);
  const deadlinesMet = allDeadlinesMet(scenario, result.optimized.placements);
  const costDelta = result.deltas.costUsd;
  const isSaving = costDelta <= 0;

  return (
    <>
      <section className="decision-hero">
        <div>
          <span className="eyebrow eyebrow--green">Recommended plan</span>
          <h2>Route {scenario.workloads.length} workloads through {providers.join(" and ")}.</h2>
          <p>Lower projected cost using public catalog prices. Capacity remains modeled and must be confirmed before placement.</p>
        </div>
        <button className="primary-button primary-button--green" onClick={onReview} type="button">
          Review {result.optimized.placements.length} placements <ArrowRight size={18} />
        </button>
      </section>

      <section className="decision-metrics" aria-label="Recommendation outcome">
        <div>
          <span>{isSaving ? "Estimated savings" : "Estimated cost increase"}</span>
          <strong className={isSaving ? "positive" : "tradeoff"}>{money(Math.abs(costDelta))}</strong>
          <small>{number(Math.abs(result.deltas.costPercent), 1)}% vs. catalog baseline</small>
        </div>
        <div>
          <span>Estimated emissions change</span>
          <strong className={result.deltas.emissionsPercent <= 0 ? "positive" : "tradeoff"}>
            {signedPercent(result.deltas.emissionsPercent)}
          </strong>
          <small>{result.deltas.emissionsKgCo2e <= 0 ? "Lower modeled emissions" : "Higher modeled emissions"}</small>
        </div>
        <div>
          <span>Deadline compliance</span>
          <strong className={deadlinesMet ? "positive" : "tradeoff"}>{deadlinesMet ? "All deadlines met" : "Review required"}</strong>
          <small>{result.optimized.placements.length} of {scenario.workloads.length} workloads placed</small>
        </div>
        <div>
          <span className="metric-label-with-info">Decision confidence <InfoTip text="Confidence is limited because provider capacity, latency, and availability are planning estimates." /></span>
          <strong className="tradeoff">Limited</strong>
          <small>{truth.modeled.length} modeled inputs affect placement</small>
        </div>
      </section>
    </>
  );
}

function PlacementTable({
  scenario,
  result,
  targetRef,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  targetRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <section className="panel placements-panel" ref={targetRef}>
      <SectionHeader
        title={`Recommended placements (${result.optimized.placements.length})`}
        aside={
          <div className="compact-actions">
            <a className="text-button" href={api.exportUrl(result.recommendationId, "csv")}>
              <Download size={16} /> Export CSV
            </a>
          </div>
        }
      />
      <div className="table-wrap table-wrap--placements">
        <table className="data-table">
          <thead>
            <tr>
              <th>Workload</th>
              <th>Recommended provider</th>
              <th>Start (UTC)</th>
              <th>Est. cost</th>
              <th>Est. savings</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {result.optimized.placements.map((placement) => {
              const workload = workloadForPlacement(scenario, placement);
              const pool = providerForPlacement(scenario, placement);
              const baseline = result.baseline.placements.find((item) => item.workloadId === placement.workloadId);
              const savings = (baseline?.costUsd ?? placement.costUsd) - placement.costUsd;
              const isSaving = savings >= 0;
              return (
                <tr key={placement.workloadId}>
                  <td><strong>{workload?.name ?? placement.workloadId}</strong><small>{workload?.gpuType}</small></td>
                  <td><span className="provider-cell"><Server size={17} /><span><strong>{pool?.provider}</strong><small>{pool?.region}</small></span></span></td>
                  <td><strong>{shortTime(placement.start)}</strong><small>{new Date(placement.start).toLocaleDateString()}</small></td>
                  <td><strong>{money(placement.costUsd)}</strong><small>{placement.gpuCount} GPUs</small></td>
                  <td><strong className={isSaving ? "positive" : "tradeoff"}>{isSaving ? money(savings) : `${money(Math.abs(savings))} added`}</strong><small>{number(Math.abs(percentage(savings, baseline?.costUsd ?? 0)), 1)}% {isSaving ? "saved" : "higher"}</small></td>
                  <td><strong className="tradeoff">Limited</strong><small>Capacity modeled</small></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="table-note">Savings use public A100-80GB catalog prices. Costs exclude egress, taxes, and provider-specific discounts.</p>
    </section>
  );
}

function AlternativesPanel({ scenario, result }: { scenario: OptimizationRequest; result: OptimizationResult }) {
  const preferredPools = scenario.resourcePools.filter((pool) => ["RunPod", "Google Cloud"].includes(pool.provider));
  const alternatives = [
    {
      label: "Recommended plan",
      detail: Array.from(new Set(result.optimized.placements.map((item) => providerForPlacement(scenario, item)?.provider))).filter(Boolean).join(" + "),
      total: result.optimized.totalCostUsd,
      selected: true,
      confidence: "Limited",
    },
    ...preferredPools.map((pool) => ({
      label: `All on ${pool.provider}`,
      detail: pool.region,
      total: providerOnlyCost(scenario, pool),
      selected: false,
      confidence: "Limited",
    })),
    {
      label: "Catalog baseline",
      detail: "Current AWS placement",
      total: result.baseline.totalCostUsd,
      selected: false,
      confidence: "Observed price",
    },
  ];

  return (
    <section className="panel alternatives-panel">
      <SectionHeader title="Alternatives and tradeoffs" />
      <div className="alternative-list">
        {alternatives.map((option) => {
          const savings = result.baseline.totalCostUsd - option.total;
          return (
            <div className={option.selected ? "alternative-row is-selected" : "alternative-row"} key={option.label}>
              <span className="alternative-check">{option.selected ? <Check size={14} /> : null}</span>
              <div><strong>{option.label}</strong><small>{option.detail}</small></div>
              <div><strong>{money(option.total)}</strong><small>Total cost</small></div>
              <div><strong className={savings > 0 ? "positive" : ""}>{savings > 0 ? money(savings) : "-"}</strong><small>{savings > 0 ? `${number(percentage(savings, result.baseline.totalCostUsd), 1)}%` : "Baseline"}</small></div>
              <div><strong className={option.confidence === "Limited" ? "tradeoff" : ""}>{option.confidence}</strong><small>{option.confidence === "Limited" ? "Modeled capacity" : "Catalog price"}</small></div>
            </div>
          );
        })}
      </div>
      <p className="table-note">All displayed options meet workload deadlines under the modeled capacity scenario.</p>
    </section>
  );
}

function EvidencePanel({
  scenario,
  health,
  onOpenQuality,
}: {
  scenario: OptimizationRequest;
  health: DataHealth | null;
  onOpenQuality: () => void;
}) {
  const truth = sourceTruth(health);
  const observedMetrics = [
    ["Catalog pricing", `${truth.observed.filter((source) => source.metric === "price").length} providers`],
    ["Carbon forecast", `${truth.observed.filter((source) => source.metric === "carbon").length} live region`],
    ["Your workloads", `${scenario.workloads.length} inputs`],
    ["Deadlines", `${scenario.workloads.length} constraints`],
  ];
  const modeledMetrics = [
    ["Provider capacity", `${scenario.resourcePools.length} providers`],
    ["Regional carbon", `${truth.modeled.filter((source) => source.metric === "carbon").length} regions`],
    ["Latency", `${scenario.resourcePools.length} providers`],
    ["Availability", `${scenario.resourcePools.length} providers`],
  ];

  return (
    <section className="panel evidence-panel">
      <SectionHeader eyebrow="Evidence behind this recommendation" title="Observed inputs are separated from planning estimates" />
      <div className="evidence-split">
        <div>
          <h3 className="positive"><CheckCircle2 size={18} /> {truth.observed.length} observed inputs</h3>
          <div className="evidence-items">
            {observedMetrics.map(([label, value]) => <span key={label}><strong>{label}</strong><small>{value}</small></span>)}
          </div>
        </div>
        <div>
          <h3 className="tradeoff"><AlertTriangle size={18} /> {truth.modeled.length} planning estimates</h3>
          <div className="evidence-items">
            {modeledMetrics.map(([label, value]) => <span key={label}><strong>{label}</strong><small>{value}</small></span>)}
          </div>
        </div>
      </div>
      <div className="evidence-footer">
        <p>Modeled capacity and public prices can change. Confirm provider inventory before placing a workload.</p>
        <button className="secondary-button" onClick={onOpenQuality} type="button">View data quality details <ArrowRight size={16} /></button>
      </div>
    </section>
  );
}

function DecideView({
  scenario,
  result,
  health,
  onOpenQuality,
  onOpenPlans,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  health: DataHealth | null;
  onOpenQuality: () => void;
  onOpenPlans: () => void;
}) {
  const placementRef = useRef<HTMLDivElement>(null);
  return (
    <div className="view-stack">
      <DecisionSummary health={health} onReview={() => placementRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} result={result} scenario={scenario} />
      <div className="decision-grid">
        <PlacementTable result={result} scenario={scenario} targetRef={placementRef} />
        <AlternativesPanel result={result} scenario={scenario} />
      </div>
      <div className="decision-actions panel">
        <div><span className="eyebrow">Next decision</span><h2>Review the placements, then approve or revise the plan.</h2></div>
        <button className="primary-button" onClick={onOpenPlans} type="button">Review plan decision <ArrowRight size={17} /></button>
      </div>
      <EvidencePanel health={health} onOpenQuality={onOpenQuality} scenario={scenario} />
    </div>
  );
}

function WorkloadsView({
  scenario,
  onScenarioChange,
  onOptimize,
  running,
  notice,
  setNotice,
}: {
  scenario: OptimizationRequest;
  onScenarioChange: (scenario: OptimizationRequest) => void;
  onOptimize: () => void;
  running: boolean;
  notice: string | null;
  setNotice: (notice: string | null) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const updateWorkload = (id: string, patch: Partial<Workload>) => {
    onScenarioChange({ ...scenario, workloads: scenario.workloads.map((item) => item.id === id ? { ...item, ...patch } : item) });
    setNotice("Workload changes are ready to optimize.");
  };
  const addWorkload = () => {
    const template = scenario.workloads[0];
    const next: Workload = {
      ...template,
      id: `workload-${Date.now()}`,
      name: "New batch workload",
      gpuCount: 2,
      durationMinutes: 60,
      priority: 50,
      maxBudgetUsd: null,
      baselinePoolId: scenario.resourcePools[0]?.id ?? null,
    };
    onScenarioChange({ ...scenario, workloads: [...scenario.workloads, next] });
    setNotice("New workload added. Review its constraints before optimizing.");
  };
  const removeWorkload = (id: string) => {
    if (scenario.workloads.length <= 1) {
      setNotice("At least one workload is required.");
      return;
    }
    onScenarioChange({ ...scenario, workloads: scenario.workloads.filter((item) => item.id !== id) });
    setNotice("Workload removed. Run optimization to update the recommendation.");
  };
  const importFile = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as OptimizationRequest | { workloads: Workload[] } | Workload[];
      const nextScenario = Array.isArray(parsed)
        ? { ...scenario, workloads: parsed }
        : "workloads" in parsed && !(`schemaVersion` in parsed)
          ? { ...scenario, workloads: parsed.workloads }
          : parsed as OptimizationRequest;
      await api.validate(nextScenario);
      onScenarioChange(nextScenario);
      setNotice(`${nextScenario.workloads.length} workloads imported and validated.`);
    } catch (importError) {
      setNotice(importError instanceof Error ? `Import failed: ${importError.message}` : "Import failed. Use a valid GridSynapse scenario JSON file.");
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const downloadTemplate = () => {
    const blob = new Blob([JSON.stringify({ workloads: scenario.workloads }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "gridsynapse-workload-template.json";
    anchor.click();
    URL.revokeObjectURL(url);
    setNotice("Workload template downloaded.");
  };

  return (
    <div className="view-stack">
      <section className="view-intro">
        <div><span className="eyebrow eyebrow--green">Workload inputs</span><h2>Define the jobs GridSynapse should place.</h2><p>Edit constraints directly or import a JSON workload list. Changes do not affect the recommendation until you optimize.</p></div>
        <div className="intro-actions">
          <input accept="application/json,.json" className="sr-only" onChange={(event) => event.target.files?.[0] && void importFile(event.target.files[0])} ref={fileRef} type="file" />
          <button className="secondary-button" onClick={() => fileRef.current?.click()} type="button"><Upload size={16} /> Import JSON</button>
          <button className="secondary-button" onClick={downloadTemplate} type="button"><Download size={16} /> Template</button>
          <button className="secondary-button" onClick={addWorkload} type="button"><FileInput size={16} /> Add workload</button>
        </div>
      </section>
      {notice ? <div className="notice-banner" role="status"><Info size={16} /><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice(null)} type="button"><XCircle size={16} /></button></div> : null}
      <section className="panel workload-editor">
        <SectionHeader title={`${scenario.workloads.length} workloads in this decision`} detail="Set the hard requirements the optimizer must respect. A new plan is created only after validation." />
        <div className="workload-card-list">
          {scenario.workloads.map((workload) => (
            <article className="workload-edit-card" key={workload.id}>
              <div className="workload-edit-card__title"><span><PencilLine size={17} /></span><div><strong>{workload.name}</strong><small>{labelize(workload.workloadType)} / {workload.gpuType}</small></div><button aria-label={`Remove ${workload.name}`} onClick={() => removeWorkload(workload.id)} type="button"><Trash2 size={16} /></button></div>
              <label><span>Name</span><input onChange={(event) => updateWorkload(workload.id, { name: event.target.value })} value={workload.name} /></label>
              <label><span>GPU count</span><input min="1" onChange={(event) => updateWorkload(workload.id, { gpuCount: Math.max(1, Number(event.target.value)) })} type="number" value={workload.gpuCount} /></label>
              <label><span>Duration</span><select onChange={(event) => updateWorkload(workload.id, { durationMinutes: Number(event.target.value) })} value={workload.durationMinutes}><option value="60">1 hour</option><option value="120">2 hours</option><option value="240">4 hours</option><option value="360">6 hours</option></select></label>
              <label><span>Priority</span><input max="100" min="1" onChange={(event) => updateWorkload(workload.id, { priority: Math.min(100, Math.max(1, Number(event.target.value))) })} type="number" value={workload.priority} /></label>
              <label><span>Deadline (UTC)</span><input onChange={(event) => updateWorkload(workload.id, { deadline: utcInputToIso(event.target.value) })} type="datetime-local" value={utcInputValue(workload.deadline)} /></label>
              <label><span>Allowed regions</span><input defaultValue={workload.allowedRegions.join(", ")} onBlur={(event) => updateWorkload(workload.id, { allowedRegions: event.target.value.split(",").map((region) => region.trim()).filter(Boolean) })} placeholder="us-east-1, us-central1" /></label>
              <label><span>Maximum budget</span><input min="0" onChange={(event) => updateWorkload(workload.id, { maxBudgetUsd: event.target.value === "" ? null : Math.max(0, Number(event.target.value)) })} placeholder="No limit" type="number" value={workload.maxBudgetUsd ?? ""} /></label>
              <label className="checkbox-field"><input checked={workload.interruptible} onChange={(event) => updateWorkload(workload.id, { interruptible: event.target.checked })} type="checkbox" /><span>May be interrupted</span></label>
              <div className="constraint-summary"><span><ClockIcon /> Deadline {shortTime(workload.deadline)}</span><span>{workload.interruptible ? "Interruptible" : "Continuous"}</span><span>{workload.allowedRegions.length} allowed regions</span><span>{workload.maxBudgetUsd === null ? "No budget cap" : `${money(workload.maxBudgetUsd)} max`}</span></div>
            </article>
          ))}
        </div>
      </section>
      <section className="sticky-action-bar">
        <div><strong>Ready to recalculate</strong><small>GridSynapse validates the scenario before returning a new plan.</small></div>
        <button className="primary-button primary-button--green" disabled={running} onClick={onOptimize} type="button">{running ? <RefreshCw className="spin" size={16} /> : <Zap size={16} />}{running ? "Optimizing" : "Validate and optimize"}</button>
      </section>
    </div>
  );
}

function ClockIcon() {
  return <span aria-hidden="true">UTC</span>;
}

function MarketView({
  scenario,
  health,
  onReview,
}: {
  scenario: OptimizationRequest;
  health: DataHealth | null;
  onReview: () => void;
}) {
  const truth = sourceTruth(health);
  return (
    <div className="view-stack">
      <section className="view-intro">
        <div><span className="eyebrow eyebrow--green">Verify market inputs</span><h2>Compare the prices and assumptions behind the recommendation.</h2><p>GridSynapse uses public A100-80GB catalog prices and labels planning estimates. It does not claim that provider inventory is currently reservable.</p></div>
        <div className="intro-actions"><button className="primary-button" onClick={onReview} type="button">Review recommendation <ArrowRight size={16} /></button></div>
      </section>
      <section className="market-truth-strip">
        <div><CheckCircle2 size={18} /><span><strong>{truth.observed.length} observed inputs</strong><small>Catalog prices and one GB carbon forecast</small></span></div>
        <div><AlertTriangle size={18} /><span><strong>{truth.modeled.length} planning estimates</strong><small>Capacity, latency, availability, and regional carbon</small></span></div>
      </section>
      <section className="panel provider-market">
        <SectionHeader title="A100-80GB provider catalog" aside={<StatusBadge tone="blue">Price sorted</StatusBadge>} />
        <div className="provider-card-grid">
          {[...scenario.resourcePools].sort((a, b) => a.priceUsdPerGpuHour - b.priceUsdPerGpuHour).map((pool, index) => {
            const priceSource = pool.metricSources?.price ?? pool.source;
            const carbonSource = pool.metricSources?.carbon ?? pool.source;
            const capacitySource = pool.metricSources?.capacity;
            return (
              <article className={index === 0 ? "provider-card is-best-price" : "provider-card"} key={pool.id}>
                <div className="provider-card__header"><span><Server size={18} /></span><div><strong>{pool.provider}</strong><small>{pool.region}</small></div>{index === 0 ? <StatusBadge tone="green">Lowest catalog price</StatusBadge> : null}</div>
                <div className="provider-price"><strong>{money(pool.priceUsdPerGpuHour)}</strong><span>per GPU-hour</span></div>
                <dl>
                  <div><dt>Capacity</dt><dd>{Math.max(...pool.capacityBySlot)} GPUs <StatusBadge tone="amber">Modeled</StatusBadge></dd></div>
                  <div><dt>Carbon</dt><dd>{pool.carbonGramsPerKwhBySlot[0]} gCO2e/kWh <StatusBadge tone={carbonSource.sourceType === "forecast" ? "green" : "amber"}>{carbonSource.sourceType === "forecast" ? "Forecast" : "Modeled"}</StatusBadge></dd></div>
                  <div><dt>Latency</dt><dd>{pool.latencyMs} ms <StatusBadge tone="amber">Modeled</StatusBadge></dd></div>
                  <div><dt>Availability</dt><dd>{number(pool.availabilityBps / 100, 1)}% <StatusBadge tone="amber">Modeled</StatusBadge></dd></div>
                </dl>
                <div className="provider-card__footer"><span>Price confidence: {priceSource.confidence}</span>{priceSource.sourceUrl ? <a href={priceSource.sourceUrl} rel="noreferrer" target="_blank">Open catalog <ExternalLink size={14} /></a> : null}</div>
                {capacitySource?.sourceType === "estimated" ? <p className="provider-warning"><Info size={14} /> Confirm live inventory with {pool.provider} before placement.</p> : null}
              </article>
            );
          })}
        </div>
      </section>
      <section className="next-step-panel"><div><strong>Next step: review the recommended plan</strong><p>Use these inputs to verify the tradeoffs, then record an operator decision.</p></div><button className="primary-button" onClick={onReview} type="button">Review & approve <ArrowRight size={16} /></button></section>
    </div>
  );
}

function MiniTimeline({ scenario, result }: { scenario: OptimizationRequest; result: OptimizationResult }) {
  return (
    <div className="mini-timeline">
      {result.optimized.placements.map((placement) => {
        const workload = workloadForPlacement(scenario, placement);
        const pool = providerForPlacement(scenario, placement);
        return (
          <div key={placement.workloadId}>
            <span><strong>{workload?.name}</strong><small>{pool?.provider} / {pool?.region}</small></span>
            <span><strong>{shortTime(placement.start)} - {shortTime(placement.end)}</strong><small>{placement.gpuCount} GPUs / {duration(workload?.durationMinutes ?? 0)}</small></span>
            <StatusBadge tone="green">Deadline met</StatusBadge>
          </div>
        );
      })}
    </div>
  );
}

function DecisionHistory({ history }: { history: DecisionHistoryItem[] }) {
  return (
    <section className="panel decision-history">
      <SectionHeader
        title="Recent decision history"
        detail="Saved recommendations and operator review states, newest first."
        aside={<StatusBadge tone="blue">{history.length} records</StatusBadge>}
      />
      {history.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Updated</th><th>Objective</th><th>Workloads</th><th>Recommended cost</th><th>Cost change</th><th>Decision</th></tr></thead>
            <tbody>{history.map((item) => {
              const isSaving = item.costDeltaUsd <= 0;
              return <tr key={item.recommendationId}><td><strong>{new Date(item.updatedAt).toLocaleDateString()}</strong><small>{new Date(item.updatedAt).toLocaleTimeString()}</small></td><td><strong>{profiles[item.objectiveProfile].label}</strong><small>{item.scenarioId}</small></td><td><strong>{item.workloadCount}</strong><small>validated inputs</small></td><td><strong>{money(item.totalCostUsd)}</strong><small>catalog estimate</small></td><td><strong className={isSaving ? "positive" : undefined}>{isSaving ? `${money(Math.abs(item.costDeltaUsd))} saved` : `${money(item.costDeltaUsd)} added`}</strong><small>vs. baseline</small></td><td><StatusBadge tone={item.approvalStatus === "approved" ? "green" : item.approvalStatus === "revision_required" ? "amber" : "neutral"}>{labelize(item.approvalStatus)}</StatusBadge>{item.approvedBy ? <small>{item.approvedBy}</small> : null}</td></tr>;
            })}</tbody>
          </table>
        </div>
      ) : <div className="empty-history"><ListChecks size={20} /><div><strong>No saved decisions yet</strong><p>Apply an objective profile or record a review to create the first entry.</p></div></div>}
    </section>
  );
}

function PlansView({
  scenario,
  result,
  explanation,
  profile,
  setProfile,
  appliedProfile,
  running,
  onOptimize,
  onApprove,
  onRevision,
  updatingApproval,
  history,
}: {
  scenario: OptimizationRequest;
  result: OptimizationResult;
  explanation: Explanation | null;
  profile: ObjectiveProfile;
  setProfile: (profile: ObjectiveProfile) => void;
  appliedProfile: ObjectiveProfile;
  running: boolean;
  onOptimize: () => void;
  onApprove: () => void;
  onRevision: () => void;
  updatingApproval: boolean;
  history: DecisionHistoryItem[];
}) {
  const active = profiles[profile];
  return (
    <div className="view-stack">
      <section className="view-intro">
        <div><span className="eyebrow eyebrow--green">Decision policy</span><h2>Choose what the optimizer should protect first.</h2><p>Hard workload constraints always apply. The profile changes how feasible placements are ranked.</p></div>
        {profile !== appliedProfile ? <StatusBadge tone="amber">Changes not applied</StatusBadge> : <StatusBadge tone="green">{profiles[appliedProfile].label} active</StatusBadge>}
      </section>
      <section className="objective-card-grid">
        {(Object.keys(profiles) as ObjectiveProfile[]).map((key) => (
          <button className={profile === key ? "objective-card is-selected" : "objective-card"} key={key} onClick={() => setProfile(key)} type="button"><span>{profile === key ? <CheckCircle2 size={18} /> : <CircleDollarSign size={18} />}</span><strong>{profiles[key].label}</strong><small>{profiles[key].detail}</small></button>
        ))}
      </section>
      <section className="panel objective-weights">
        <div><span className="eyebrow">Selected policy</span><h2>{active.label}</h2><p>{active.detail}</p></div>
        <dl>{Object.entries(active.weights).map(([key, value]) => <div key={key}><dt>{labelize(key.replace("Bps", ""))}</dt><dd>{value / 100}%</dd></div>)}</dl>
        <button className="primary-button primary-button--green" disabled={running} onClick={onOptimize} type="button">{running ? <RefreshCw className="spin" size={16} /> : <Zap size={16} />}{running ? "Optimizing" : "Apply and optimize"}</button>
      </section>
      <section className="plans-comparison-grid">
        <article className="plan-summary-card"><span className="eyebrow">Catalog baseline</span><h3>{money(result.baseline.totalCostUsd)}</h3><p>Current AWS placement using public list price.</p><dl><div><dt>Emissions</dt><dd>{number(result.baseline.totalEmissionsKgCo2e, 2)} kg</dd></div><div><dt>Modeled risk index</dt><dd>{number(result.baseline.capacityRiskScore, 1)}</dd></div></dl></article>
        <article className="plan-summary-card is-recommended"><span className="eyebrow eyebrow--green">Recommended plan</span><h3>{money(result.optimized.totalCostUsd)}</h3><p>{profiles[result.solver.objectiveProfile].label} placement across approved regions.</p><dl><div><dt>Emissions</dt><dd>{number(result.optimized.totalEmissionsKgCo2e, 2)} kg</dd></div><div><dt>Modeled risk index</dt><dd>{number(result.optimized.capacityRiskScore, 1)}</dd></div></dl></article>
      </section>
      <section className="panel plan-review">
        <SectionHeader eyebrow="Validated plan" title={explanation?.headline ?? "Recommendation ready for review"} aside={<StatusBadge tone={result.approval.status === "approved" ? "green" : result.approval.status === "revision_required" ? "amber" : "neutral"}>{labelize(result.approval.status)}</StatusBadge>} />
        <div className="plan-review-grid">
          <div>
            <p className="lead-copy">{explanation?.summary ?? "GridSynapse is preparing a grounded explanation."}</p>
            <div className="reason-grid"><div><strong>Why this plan</strong>{(explanation?.decisionFactors ?? []).map((item) => <span key={item}><CheckCircle2 size={14} />{item}</span>)}</div><div><strong>Tradeoffs</strong>{(explanation?.tradeoffs ?? []).map((item) => <span key={item}><GitCompareArrows size={14} />{item}</span>)}</div></div>
            {explanation?.warnings.length ? <div className="warning-line"><AlertTriangle size={16} />{explanation.warnings.join(" ")}</div> : null}
          </div>
          <aside className="approval-card">
            <span className="eyebrow">Operator decision</span><h3>{result.approval.status === "approved" ? "Plan approved" : result.approval.status === "revision_required" ? "Revision requested" : "Review recommendation"}</h3><p>Approval records the decision only. GridSynapse does not reserve or deploy compute.</p>
            <button className="primary-button" disabled={updatingApproval || result.approval.status === "approved"} onClick={onApprove} type="button"><CheckCircle2 size={16} />{result.approval.status === "approved" ? "Approved" : "Approve plan"}</button>
            <button className="secondary-button secondary-button--danger" disabled={updatingApproval} onClick={onRevision} type="button"><RotateCcw size={16} />Request revision</button>
            <div className="export-actions"><a href={api.exportUrl(result.recommendationId, "json")}><FileJson size={15} />JSON</a><a href={api.exportUrl(result.recommendationId, "csv")}><FileSpreadsheet size={15} />CSV</a></div>
          </aside>
        </div>
        <MiniTimeline result={result} scenario={scenario} />
      </section>
      <DecisionHistory history={history} />
    </div>
  );
}

function DataQualityView({ scenario, health, onReview }: { scenario: OptimizationRequest; health: DataHealth | null; onReview: () => void }) {
  const truth = sourceTruth(health);
  const byPool = scenario.resourcePools.map((pool) => ({ pool, sources: (health?.sources ?? []).filter((source) => source.poolId === pool.id) }));
  return (
    <div className="view-stack">
      <section className="view-intro">
        <div><span className="eyebrow eyebrow--green">Decision evidence</span><h2>Know what is observed before you trust a route.</h2><p>Freshness is not the same as accuracy. GridSynapse separates public data from estimates that require confirmation.</p></div>
        <StatusBadge tone={truth.stale.length ? "amber" : "green"}>{truth.stale.length ? `${truth.stale.length} stale inputs` : "Observed sources current"}</StatusBadge>
      </section>
      <section className="quality-score-grid">
        <div><CheckCircle2 size={19} /><span><strong>{truth.observed.length}</strong><small>Observed inputs</small></span></div>
        <div><AlertTriangle size={19} /><span><strong>{truth.modeled.length}</strong><small>Planning estimates</small></span></div>
        <div><Gauge size={19} /><span><strong>Limited</strong><small>Decision confidence</small></span></div>
        <div><ShieldCheck size={19} /><span><strong>{truth.stale.length}</strong><small>Stale inputs</small></span></div>
      </section>
      <section className="panel quality-matrix">
        <SectionHeader title="Source coverage by provider" detail="Observed means a public catalog snapshot or official forecast. Modeled means a planning assumption." />
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Provider</th><th>Price</th><th>Carbon</th><th>Capacity</th><th>Latency</th><th>Availability</th></tr></thead>
            <tbody>{byPool.map(({ pool, sources }) => <tr key={pool.id}><td><strong>{pool.provider}</strong><small>{pool.region}</small></td>{["price", "carbon", "capacity", "latency", "availability"].map((metric) => { const source = sources.find((item) => item.metric === metric); const observed = source && source.sourceType !== "estimated"; return <td key={metric}><StatusBadge tone={source?.stale ? "red" : observed ? "green" : "amber"}>{source?.stale ? "Stale" : observed ? "Observed" : "Modeled"}</StatusBadge><small>{source?.confidence ?? "unknown"} confidence</small></td>; })}</tr>)}</tbody>
          </table>
        </div>
      </section>
      <details className="panel source-records">
        <summary><span><strong>Source records</strong><span>{health?.sources.length ?? 0} inputs with declared source, freshness, and confidence.</span></span><ChevronDown size={18} /></summary>
        <div className="source-record-list">{(health?.sources ?? []).map((source) => <div key={`${source.poolId}-${source.metric}`}><div><strong>{scenario.resourcePools.find((pool) => pool.id === source.poolId)?.provider}</strong><small>{labelize(source.metric)} / {source.sourceId}</small></div><span>{source.unit}</span><span>{new Date(source.observedAt).toLocaleString()}</span><StatusBadge tone={source.stale ? "red" : source.sourceType === "estimated" ? "amber" : "green"}>{source.stale ? "Stale" : source.sourceType === "estimated" ? "Modeled" : "Current"}</StatusBadge>{source.sourceUrl ? <a aria-label="Open source" href={source.sourceUrl} rel="noreferrer" target="_blank"><ExternalLink size={15} /></a> : <span className="source-unavailable">-</span>}</div>)}</div>
      </details>
      <section className="execution-boundary"><ShieldCheck size={22} /><div><strong>Recommendation boundary</strong><p>GridSynapse compares and validates placements. It does not query reservable inventory, purchase compute, or migrate workloads.</p></div></section>
      <section className="next-step-panel"><div><strong>Evidence reviewed</strong><p>Return to the recommendation to evaluate the plan and record the operator decision.</p></div><button className="primary-button" onClick={onReview} type="button">Review & approve <ArrowRight size={16} /></button></section>
    </div>
  );
}

export function OperatorConsole() {
  const [activeView, setActiveView] = useState<View>("decide");
  const [scenario, setScenario] = useState<OptimizationRequest | null>(null);
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [profile, setProfile] = useState<ObjectiveProfile>("balanced");
  const [appliedProfile, setAppliedProfile] = useState<ObjectiveProfile>("balanced");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [refreshingMarket, setRefreshingMarket] = useState(false);
  const [updatingApproval, setUpdatingApproval] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [marketMode, setMarketMode] = useState<"hybrid-live" | "reference">("hybrid-live");
  const [marketGeneratedAt, setMarketGeneratedAt] = useState<string | null>(null);
  const [marketWarnings, setMarketWarnings] = useState<string[]>([]);
  const [persistence, setPersistence] = useState<PersistenceStatus | null>(null);
  const [history, setHistory] = useState<DecisionHistoryItem[]>([]);

  const refreshOperationalState = useCallback(async () => {
    try {
      const [healthResponse, historyResponse] = await Promise.all([
        api.health(),
        api.decisionHistory(),
      ]);
      setPersistence(healthResponse.persistence);
      setHistory(historyResponse);
    } catch {
      setPersistence({
        backend: "unavailable",
        durable: false,
        detail: "Decision history status is temporarily unavailable.",
      });
    }
  }, []);

  const optimizeScenario = useCallback(async (baseScenario: OptimizationRequest, targetProfile: ObjectiveProfile) => {
    setRunning(true);
    setError(null);
    setExplanation(null);
    const request: OptimizationRequest = { ...baseScenario, policy: { ...baseScenario.policy, profile: targetProfile, weights: profiles[targetProfile].weights } };
    try {
      await api.validate(request);
      const nextResult = await api.optimize(request);
      setScenario(request);
      setResult(nextResult);
      setAppliedProfile(targetProfile);
      if (nextResult.status === "feasible") setExplanation(await api.explanation(nextResult.recommendationId));
      setNotice(`Recommendation updated using the ${profiles[targetProfile].label} profile.`);
      void refreshOperationalState();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Optimization failed");
    } finally {
      setRunning(false);
    }
  }, [refreshOperationalState]);

  const load = useCallback(async (refresh = false) => {
    if (scenario) setRefreshingMarket(true); else setLoading(true);
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
      setLoading(false);
      setRefreshingMarket(false);
    }
  }, [optimizeScenario, scenario]);

  useEffect(() => {
    void load(false);
    // Initial market load only. Manual refreshes use the header action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateApproval = async (status: "approved" | "revision_required") => {
    if (!result) return;
    setUpdatingApproval(true);
    setError(null);
    try {
      const nextResult = await api.approve(result.recommendationId, status);
      setResult({ ...nextResult });
      setNotice(status === "approved" ? "Plan approved. Export the handoff or continue monitoring market inputs." : "Revision requested. Change the policy or workloads, then optimize again.");
      void refreshOperationalState();
    } catch (approvalError) {
      setError(approvalError instanceof Error ? approvalError.message : "Approval update failed");
    } finally {
      setUpdatingApproval(false);
    }
  };

  const truth = sourceTruth(health);
  const dataStatus = marketMode === "hybrid-live" ? "Live prices + modeled availability" : "Reference scenario";

  if (loading && !scenario) {
    return <main className="boot-state"><div className="brand-mark"><Boxes size={25} /></div><h1>Loading GridSynapse</h1><p>Reading workload, catalog, carbon, and policy inputs.</p><RefreshCw className="spin" size={22} /></main>;
  }
  if (!scenario || !result) {
    return <main className="boot-state boot-state--error"><AlertTriangle size={28} /><h1>GridSynapse unavailable</h1><p>{error ?? "A validated recommendation could not be loaded."}</p><button className="primary-button" onClick={() => void load()} type="button"><RefreshCw size={16} />Retry</button></main>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setActiveView("decide")} type="button"><span className="brand-mark"><Boxes size={21} /></span><span><strong>GridSynapse</strong><small>Compute Optimizer</small></span></button>
        <nav aria-label="Product areas">{navItems.map((item) => <button className={activeView === item.id ? "is-active" : ""} key={item.id} onClick={() => setActiveView(item.id)} type="button">{item.icon}<span>{item.label}</span></button>)}</nav>
        <div className="sidebar__footer"><span className={persistence?.durable ? "environment-dot" : "environment-dot environment-dot--amber"} /><div><strong>{persistence?.durable ? "Decision history saved" : "Session decision history"}</strong><small>{persistence?.durable ? "Durable review and audit records" : "Connect Supabase for durable records"}</small></div></div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><h1>GridSynapse Compute Optimizer</h1></div>
          <div className="topbar__context">
            <div><small>Data status</small><strong><span className="environment-dot" />{dataStatus} <InfoTip text={`${truth.observed.length} observed inputs and ${truth.modeled.length} planning estimates`} /></strong></div>
            <div><small>Market snapshot</small><strong>{marketGeneratedAt ? new Date(marketGeneratedAt).toLocaleString() : scenario.scenarioId}</strong></div>
            <button className="secondary-button" disabled={refreshingMarket} onClick={() => void load(true)} type="button"><RefreshCw className={refreshingMarket ? "spin" : ""} size={16} />{refreshingMarket ? "Refreshing" : "Refresh"}</button>
          </div>
        </header>

        {error ? <div className="error-banner" role="alert"><AlertTriangle size={17} /><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)} type="button"><XCircle size={17} /></button></div> : null}
        {marketWarnings.length ? <div className="market-warning" role="status"><AlertTriangle size={16} /><span>{marketWarnings.join(" ")}</span></div> : null}
        {notice && activeView !== "workloads" ? <div className="notice-banner" role="status"><Info size={16} /><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice(null)} type="button"><XCircle size={16} /></button></div> : null}

        {activeView === "decide" ? <DecideView health={health} onOpenPlans={() => setActiveView("plans")} onOpenQuality={() => setActiveView("quality")} result={result} scenario={scenario} /> : null}
        {activeView === "workloads" ? <WorkloadsView notice={notice} onOptimize={() => void optimizeScenario(scenario, profile)} onScenarioChange={setScenario} running={running} scenario={scenario} setNotice={setNotice} /> : null}
        {activeView === "market" ? <MarketView health={health} onReview={() => setActiveView("plans")} scenario={scenario} /> : null}
        {activeView === "plans" ? <PlansView appliedProfile={appliedProfile} explanation={explanation} history={history} onApprove={() => void updateApproval("approved")} onOptimize={() => void optimizeScenario(scenario, profile)} onRevision={() => void updateApproval("revision_required")} profile={profile} result={result} running={running} scenario={scenario} setProfile={setProfile} updatingApproval={updatingApproval} /> : null}
        {activeView === "quality" ? <DataQualityView health={health} onReview={() => setActiveView("plans")} scenario={scenario} /> : null}

        <footer className="page-footer"><span>GridSynapse v2 / source-aware placement intelligence</span><span>No reservation or autonomous execution</span></footer>
      </main>
    </div>
  );
}
