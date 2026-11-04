-- Execute once in a new Supabase project's SQL Editor. No secrets in this file.
begin;
create table if not exists public.prd_documents (
  id uuid primary key, name text not null, project text not null,
  created timestamptz not null default now(), updated timestamptz not null default now(),
  sha text not null, status text not null default 'ready'
    check (status in ('ready','processing','done','failed','deleting')),
  notes jsonb not null default '[]', report jsonb, error text, provider text, model text,
  lease uuid, parser_version integer not null default 2,
  raw_manifest jsonb not null, parsed_manifest jsonb not null
);
create table if not exists public.prd_messages (
  id bigint generated always as identity primary key,
  document_id uuid not null references public.prd_documents(id) on delete cascade,
  question text not null, answer text not null, created timestamptz not null default now()
);
create table if not exists public.prd_daily_calls (
  day date primary key, calls integer not null
);
alter table public.prd_documents enable row level security;
alter table public.prd_messages enable row level security;
alter table public.prd_daily_calls enable row level security;
revoke all on public.prd_documents,public.prd_messages,public.prd_daily_calls from anon,authenticated;
grant all on public.prd_documents,public.prd_messages,public.prd_daily_calls to service_role;
grant usage,select on sequence public.prd_messages_id_seq to service_role;

create or replace function public.prd_claim(p_id uuid,p_token uuid,p_provider text,p_model text)
returns boolean language plpgsql security invoker set search_path=public as $$
begin
  update public.prd_documents set status='processing',lease=p_token,provider=p_provider,
    model=p_model,error=null,updated=now()
  where id=p_id and status not in ('processing','deleting');
  return found;
end $$;

create or replace function public.prd_recover(p_id uuid)
returns boolean language plpgsql security invoker set search_path=public as $$
begin
  update public.prd_documents set status='failed',lease=null,error='处理被中断，可以重新提炼',updated=now()
  where id=p_id and status='processing' and updated < now()-interval '15 minutes';
  return found;
end $$;

create or replace function public.prd_begin_delete(p_id uuid)
returns jsonb language plpgsql security invoker set search_path=public as $$
declare item public.prd_documents;
begin
  update public.prd_documents set status='deleting',lease=null,updated=now()
    where id=p_id and status != 'processing' returning * into item;
  if not found then return null; end if;
  return to_jsonb(item);
end $$;

create or replace function public.prd_reserve_call(p_limit integer)
returns boolean language plpgsql security invoker set search_path=public as $$
begin
  if p_limit <= 0 then return false; end if;
  insert into public.prd_daily_calls(day,calls)
    values ((now() at time zone 'Asia/Shanghai')::date,1)
  on conflict(day) do update set calls=prd_daily_calls.calls+1
    where prd_daily_calls.calls < p_limit;
  return found;
end $$;

revoke all on function public.prd_claim(uuid,uuid,text,text), public.prd_recover(uuid),
 public.prd_begin_delete(uuid), public.prd_reserve_call(integer) from public,anon,authenticated;
grant execute on function public.prd_claim(uuid,uuid,text,text), public.prd_recover(uuid),
 public.prd_begin_delete(uuid), public.prd_reserve_call(integer) to service_role;

-- Private bucket. Objects are at most 8 MiB, including for 200 MB original documents.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('prd-files','prd-files',false,10485760,array['application/octet-stream'])
on conflict(id) do update set public=false,file_size_limit=10485760,
 allowed_mime_types=array['application/octet-stream'];
commit;
