import type {
  DataHealth,
  DecisionHistoryItem,
  Explanation,
  HealthResponse,
  LiveMarketSnapshot,
  OptimizationRequest,
  OptimizationResult,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "https://gridsynapse-api.vercel.app";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(body.detail ?? `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  decisionHistory: (limit = 12) =>
    request<DecisionHistoryItem[]>(`/api/v2/decision-history?limit=${limit}`),
  liveMarket: (refresh = false) =>
    request<LiveMarketSnapshot>(`/api/v2/live-market/scenario?refresh=${refresh}`),
  scenario: (id: string) => request<OptimizationRequest>(`/api/v2/scenarios/${id}`),
  dataHealth: (id: string) => request<DataHealth>(`/api/v2/scenarios/${id}/data-health`),
  validate: (body: OptimizationRequest) =>
    request<{ valid: boolean; scenarioId: string; workloadCount: number; resourcePoolCount: number; slotCount: number }>(
      "/api/v2/scenarios/validate",
      { method: "POST", body: JSON.stringify(body) },
    ),
  optimize: (body: OptimizationRequest) =>
    request<OptimizationResult>("/api/v2/optimizations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  explanation: (id: string) =>
    request<Explanation>(`/api/v2/optimizations/${id}/explanation`),
  optimization: (id: string) =>
    request<OptimizationResult>(`/api/v2/optimizations/${id}`),
  approve: (id: string, status: "approved" | "revision_required") =>
    request<OptimizationResult>(`/api/v2/optimizations/${id}/approval`, {
      method: "POST",
      body: JSON.stringify({ status, actor: "operator@gridsynapse.io" }),
    }),
  exportUrl: (id: string, format: "json" | "csv") =>
    `${API_URL}/api/v2/optimizations/${id}/export?format=${format}`,
};
