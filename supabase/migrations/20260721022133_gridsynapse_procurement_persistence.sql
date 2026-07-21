create table if not exists public.gridsynapse_procurement_plans (
  procurement_plan_id text primary key,
  recommendation_id text not null
    references public.gridsynapse_optimization_runs (recommendation_id) on delete cascade,
  status text not null,
  plan_payload jsonb not null,
  request_payload jsonb not null,
  result_payload jsonb not null,
  create_payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists gridsynapse_procurement_recommendation_idx
  on public.gridsynapse_procurement_plans (recommendation_id);
create index if not exists gridsynapse_procurement_updated_idx
  on public.gridsynapse_procurement_plans (updated_at desc);
create index if not exists gridsynapse_procurement_status_idx
  on public.gridsynapse_procurement_plans (status);

alter table public.gridsynapse_procurement_plans enable row level security;

revoke all on table public.gridsynapse_procurement_plans from public, anon, authenticated;
grant select, insert, update, delete on table public.gridsynapse_procurement_plans to anon;
grant select, insert, update, delete on table public.gridsynapse_procurement_plans to service_role;

drop policy if exists "GridSynapse backend reads procurement plans"
  on public.gridsynapse_procurement_plans;
drop policy if exists "GridSynapse backend inserts procurement plans"
  on public.gridsynapse_procurement_plans;
drop policy if exists "GridSynapse backend updates procurement plans"
  on public.gridsynapse_procurement_plans;
drop policy if exists "GridSynapse backend deletes procurement plans"
  on public.gridsynapse_procurement_plans;

create policy "GridSynapse backend reads procurement plans"
  on public.gridsynapse_procurement_plans
  for select to anon
  using ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend inserts procurement plans"
  on public.gridsynapse_procurement_plans
  for insert to anon
  with check ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend updates procurement plans"
  on public.gridsynapse_procurement_plans
  for update to anon
  using ((select private.gridsynapse_backend_authorized()))
  with check ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend deletes procurement plans"
  on public.gridsynapse_procurement_plans
  for delete to anon
  using ((select private.gridsynapse_backend_authorized()));

comment on table public.gridsynapse_procurement_plans is
  'Durable GridSynapse zero-spend procurement plans and simulated lifecycle state.';
