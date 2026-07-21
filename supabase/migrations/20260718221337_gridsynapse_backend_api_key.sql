create extension if not exists pgcrypto with schema extensions;

create schema if not exists private;
revoke all on schema private from public;

create table if not exists private.gridsynapse_backend_credentials (
  credential_id text primary key,
  secret_hash text not null check (length(secret_hash) = 64),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  rotated_at timestamptz
);

revoke all on table private.gridsynapse_backend_credentials from public, anon, authenticated;

create or replace function private.gridsynapse_backend_authorized()
returns boolean
language sql
stable
security definer
set search_path = pg_catalog, private, extensions
as $$
  select exists (
    select 1
    from private.gridsynapse_backend_credentials
    where active
      and secret_hash = encode(
        extensions.digest(
          coalesce(
            nullif(current_setting('request.headers', true), '')::jsonb
              ->> 'x-gridsynapse-database-key',
            ''
          ),
          'sha256'
        ),
        'hex'
      )
  );
$$;

revoke all on function private.gridsynapse_backend_authorized() from public;
grant usage on schema private to anon;
grant execute on function private.gridsynapse_backend_authorized() to anon;

grant select, insert, update, delete on table public.gridsynapse_optimization_runs to anon;
grant select, insert on table public.gridsynapse_decision_events to anon;

drop policy if exists "GridSynapse backend reads runs" on public.gridsynapse_optimization_runs;
drop policy if exists "GridSynapse backend inserts runs" on public.gridsynapse_optimization_runs;
drop policy if exists "GridSynapse backend updates runs" on public.gridsynapse_optimization_runs;
drop policy if exists "GridSynapse backend deletes runs" on public.gridsynapse_optimization_runs;
drop policy if exists "GridSynapse backend reads events" on public.gridsynapse_decision_events;
drop policy if exists "GridSynapse backend inserts events" on public.gridsynapse_decision_events;

create policy "GridSynapse backend reads runs"
  on public.gridsynapse_optimization_runs
  for select to anon
  using ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend inserts runs"
  on public.gridsynapse_optimization_runs
  for insert to anon
  with check ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend updates runs"
  on public.gridsynapse_optimization_runs
  for update to anon
  using ((select private.gridsynapse_backend_authorized()))
  with check ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend deletes runs"
  on public.gridsynapse_optimization_runs
  for delete to anon
  using ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend reads events"
  on public.gridsynapse_decision_events
  for select to anon
  using ((select private.gridsynapse_backend_authorized()));

create policy "GridSynapse backend inserts events"
  on public.gridsynapse_decision_events
  for insert to anon
  with check ((select private.gridsynapse_backend_authorized()));

comment on function private.gridsynapse_backend_authorized() is
  'Validates the server-only GridSynapse database credential supplied through PostgREST.';
