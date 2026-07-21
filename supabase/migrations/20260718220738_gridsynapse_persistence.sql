create table if not exists public.gridsynapse_optimization_runs (
  recommendation_id text primary key,
  scenario_id text not null,
  request_payload jsonb not null,
  result_payload jsonb not null,
  approval_status text not null default 'not_reviewed'
    check (approval_status in ('not_reviewed', 'approved', 'revision_required', 'invalidated')),
  approved_by text,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists gridsynapse_runs_scenario_idx
  on public.gridsynapse_optimization_runs (scenario_id);
create index if not exists gridsynapse_runs_updated_idx
  on public.gridsynapse_optimization_runs (updated_at desc);
create index if not exists gridsynapse_runs_approval_idx
  on public.gridsynapse_optimization_runs (approval_status);

create table if not exists public.gridsynapse_decision_events (
  id uuid primary key default gen_random_uuid(),
  recommendation_id text not null
    references public.gridsynapse_optimization_runs (recommendation_id) on delete cascade,
  event_type text not null,
  actor text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists gridsynapse_events_recommendation_idx
  on public.gridsynapse_decision_events (recommendation_id, created_at desc);

alter table public.gridsynapse_optimization_runs enable row level security;
alter table public.gridsynapse_decision_events enable row level security;

revoke all on table public.gridsynapse_optimization_runs from anon, authenticated;
revoke all on table public.gridsynapse_decision_events from anon, authenticated;

grant select, insert, update, delete on table public.gridsynapse_optimization_runs
  to service_role;
grant select, insert on table public.gridsynapse_decision_events
  to service_role;

comment on table public.gridsynapse_optimization_runs is
  'Durable GridSynapse recommendation, input, and operator review records.';
comment on table public.gridsynapse_decision_events is
  'Append-only audit events for GridSynapse recommendation lifecycle changes.';
