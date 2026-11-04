-- Summary-only schema v3. Existing document tables/buckets are deliberately untouched.
begin;
create table if not exists public.prd_projects (
 id uuid primary key, name text not null check(length(name) between 1 and 100),
 created timestamptz not null default now()
);
create table if not exists public.prd_summaries (
 id uuid primary key, project_id uuid not null references public.prd_projects(id) on delete cascade,
 created timestamptz not null default now(), payload jsonb not null
);
create index if not exists prd_summaries_project_created on public.prd_summaries(project_id,created desc);
create table if not exists public.prd_daily_calls(day date primary key,calls integer not null);
alter table public.prd_projects enable row level security;
alter table public.prd_summaries enable row level security;
alter table public.prd_daily_calls enable row level security;
revoke all on public.prd_projects,public.prd_summaries,public.prd_daily_calls from anon,authenticated;
grant all on public.prd_projects,public.prd_summaries,public.prd_daily_calls to service_role;
create or replace function public.prd_reserve_call(p_limit integer)
returns boolean language plpgsql security invoker set search_path=public as $$
begin
 if p_limit<=0 then return false;end if;
 insert into public.prd_daily_calls(day,calls) values((now() at time zone 'Asia/Shanghai')::date,1)
 on conflict(day) do update set calls=prd_daily_calls.calls+1 where prd_daily_calls.calls<p_limit;
 return found;
end $$;
revoke all on function public.prd_reserve_call(integer) from public,anon,authenticated;
grant execute on function public.prd_reserve_call(integer) to service_role;
commit;
