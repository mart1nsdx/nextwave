-- Authoritative database source for Volta control-tower projections.
--
-- This migration creates structure only. It deliberately inserts no example operations,
-- calls, mandates, or rates: the dashboard renders data supplied by real upstream and
-- voice/ledger workflows.

begin;

create table if not exists public.operations (
    id text primary key,
    reference text not null unique,
    client_name text not null,
    container_number text not null,
    route text not null,
    stage text not null,
    attention text not null check (attention in ('needs_attention', 'working', 'executing')),
    days_remaining integer check (days_remaining is null or days_remaining >= 0),
    next_action text not null,
    source_freshness text not null,
    source_is_demo boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.operation_workspaces (
    operation_id text primary key references public.operations(id) on delete cascade,
    workspace jsonb not null,
    updated_at timestamptz not null default now()
);

create table if not exists public.operation_bot_profiles (
    operation_id text primary key references public.operations(id) on delete cascade,
    agent_name text not null,
    agent_role text not null,
    primary_language text not null,
    fallback_language text not null,
    recap_channel text not null,
    updated_at timestamptz not null default now()
);

create table if not exists public.mandates (
    mandate_id text primary key,
    version integer not null check (version >= 1),
    owner_id text not null,
    operation_id text not null references public.operations(id) on delete restrict,
    max_all_in_usd numeric not null check (max_all_in_usd > 0),
    pickup_not_before timestamptz not null,
    pickup_not_after timestamptz not null,
    allowed_equipment text[] not null check (cardinality(allowed_equipment) > 0),
    commitment_mode text not null check (commitment_mode in ('autonomous', 'human_escalation')),
    fx_margin_bps integer check (fx_margin_bps is null or fx_margin_bps >= 0),
    created_at timestamptz not null default now(),
    unique (operation_id, version),
    check (pickup_not_after >= pickup_not_before)
);

create table if not exists public.operation_mandate_heads (
    operation_id text primary key references public.operations(id) on delete cascade,
    mandate_id text not null unique references public.mandates(mandate_id) on delete restrict,
    set_at timestamptz not null default now()
);

create table if not exists public.fx_snapshots (
    snapshot_id text primary key,
    operation_id text not null references public.operations(id) on delete restrict,
    quote_currency char(3) not null check (quote_currency ~ '^[A-Z]{3}$'),
    usd_per_unit numeric not null check (usd_per_unit > 0),
    observed_at timestamptz not null,
    source text not null,
    recorded_at timestamptz not null default now()
);

create table if not exists public.trusted_sessions (
    operation_id text primary key references public.operations(id) on delete cascade,
    trusted_carrier_name text not null,
    trusted_carrier_id text not null,
    trusted_contact_id text not null,
    verified_at timestamptz not null default now()
);

create table if not exists public.call_cases (
    id text primary key,
    operation_id text not null references public.operations(id) on delete restrict,
    carrier_name text not null,
    direction text not null,
    status text not null,
    started_at timestamptz not null,
    duration_seconds integer not null check (duration_seconds >= 0),
    summary text not null,
    has_evidence boolean not null default false,
    call_brief jsonb not null default '[]'::jsonb check (jsonb_typeof(call_brief) = 'array'),
    transcript jsonb not null default '[]'::jsonb check (jsonb_typeof(transcript) = 'array'),
    policy_decisions jsonb not null default '[]'::jsonb
        check (jsonb_typeof(policy_decisions) = 'array'),
    recap_status text not null,
    recording_id text,
    audio_offset_ms integer check (audio_offset_ms is null or audio_offset_ms >= 0),
    transcript_event_id text,
    audio_url text,
    is_demo boolean not null default false,
    created_at timestamptz not null default now(),
    check (
        (recording_id is null and audio_offset_ms is null and transcript_event_id is null)
        or (recording_id is not null and audio_offset_ms is not null and transcript_event_id is not null)
    )
);

create table if not exists public.commitments (
    id text primary key,
    operation_id text not null references public.operations(id) on delete restrict,
    state text not null,
    carrier_name text,
    recap_status text,
    evidence_call_id text references public.call_cases(id) on delete restrict,
    created_at timestamptz not null default now()
);

create table if not exists public.commitment_assignments (
    id bigint generated always as identity primary key,
    commitment_id text not null references public.commitments(id) on delete restrict,
    version integer not null check (version >= 1),
    driver_contact jsonb not null,
    vehicle_data jsonb not null,
    evidence_reference text not null,
    recorded_at timestamptz not null default now(),
    unique (commitment_id, version)
);

create table if not exists public.operator_command_results (
    idempotency_key text primary key,
    operation_id text not null references public.operations(id) on delete restrict,
    rfq_id text not null,
    command_type text not null check (command_type in ('activate_rfq', 'request_award')),
    result jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists call_cases_operation_id_started_at_idx
    on public.call_cases (operation_id, started_at desc);

create index if not exists commitment_assignments_commitment_version_idx
    on public.commitment_assignments (commitment_id, version desc);

create or replace view public.active_mandates as
select mandate.*
from public.mandates as mandate
join public.operation_mandate_heads as head on head.mandate_id = mandate.mandate_id;

create or replace function public.reject_immutable_record_change()
returns trigger
language plpgsql
as $$
begin
    raise exception 'Immutable evidence must be superseded by a new version, never updated';
end;
$$;

drop trigger if exists mandates_are_immutable on public.mandates;
create trigger mandates_are_immutable
before update or delete on public.mandates
for each row execute function public.reject_immutable_record_change();

drop trigger if exists fx_snapshots_are_immutable on public.fx_snapshots;
create trigger fx_snapshots_are_immutable
before update or delete on public.fx_snapshots
for each row execute function public.reject_immutable_record_change();

drop trigger if exists commitment_assignments_are_append_only on public.commitment_assignments;
create trigger commitment_assignments_are_append_only
before update or delete on public.commitment_assignments
for each row execute function public.reject_immutable_record_change();

create or replace function public.control_tower_activate_rfq(
    p_operation_id text,
    p_carrier_ids jsonb,
    p_idempotency_key text
)
returns jsonb
language plpgsql
as $$
declare
    current_workspace jsonb;
    result jsonb;
    rfq_id text;
begin
    select operator_command_results.result
      into result
      from public.operator_command_results
     where idempotency_key = p_idempotency_key;
    if found then
        return result;
    end if;

    select workspace
      into current_workspace
      from public.operation_workspaces
     where operation_id = p_operation_id
     for update;
    if not found then
        raise exception 'Operation workspace % was not found', p_operation_id;
    end if;
    if current_workspace #>> '{rfq,phase}' <> 'ready' then
        raise exception 'RFQ is not ready for activation';
    end if;
    if jsonb_typeof(p_carrier_ids) <> 'array'
        or jsonb_array_length(p_carrier_ids) < 3
        or (select count(distinct carrier_id)
              from jsonb_array_elements_text(p_carrier_ids) as carrier_id)
              <> jsonb_array_length(p_carrier_ids) then
        raise exception 'RFQ activation requires three distinct carriers';
    end if;

    rfq_id := current_workspace #>> '{rfq,id}';
    current_workspace := jsonb_set(current_workspace, '{rfq,phase}', '"open"'::jsonb);
    current_workspace := jsonb_set(current_workspace, '{rfq,carrier_ids}', p_carrier_ids);
    current_workspace := jsonb_set(
        current_workspace, '{stage}', '"RFQ in progress"'::jsonb
    );
    current_workspace := jsonb_set(
        current_workspace,
        '{next_action}',
        '"Review comparable offers before requesting an award."'::jsonb
    );

    update public.operation_workspaces
       set workspace = current_workspace, updated_at = now()
     where operation_id = p_operation_id;
    update public.operations
       set stage = 'RFQ in progress',
           attention = 'working',
           next_action = 'Review comparable offers before requesting an award.',
           updated_at = now()
     where id = p_operation_id;

    result := jsonb_build_object(
        'operation_id', p_operation_id,
        'rfq_id', rfq_id,
        'outcome', 'activated',
        'message', 'RFQ activation recorded. Carrier outreach is managed by the market workflow.',
        'phase', 'open',
        'is_demo', false
    );
    insert into public.operator_command_results (
        idempotency_key, operation_id, rfq_id, command_type, result
    ) values (p_idempotency_key, p_operation_id, rfq_id, 'activate_rfq', result);
    return result;
end;
$$;

create or replace function public.control_tower_request_award(
    p_operation_id text,
    p_offer_id text,
    p_idempotency_key text
)
returns jsonb
language plpgsql
as $$
declare
    current_workspace jsonb;
    result jsonb;
    rfq_id text;
begin
    select operator_command_results.result
      into result
      from public.operator_command_results
     where idempotency_key = p_idempotency_key;
    if found then
        return result;
    end if;

    select workspace
      into current_workspace
      from public.operation_workspaces
     where operation_id = p_operation_id
     for update;
    if not found then
        raise exception 'Operation workspace % was not found', p_operation_id;
    end if;
    if current_workspace #>> '{rfq,phase}' <> 'open' then
        raise exception 'RFQ is not open for an award request';
    end if;
    if not exists (
        select 1
          from jsonb_array_elements(coalesce(current_workspace #> '{rfq,offers}', '[]'::jsonb))
               as offer
         where offer ->> 'id' = p_offer_id
           and offer ->> 'status' = 'eligible'
    ) then
        raise exception 'Offer is not eligible for an award request';
    end if;

    rfq_id := current_workspace #>> '{rfq,id}';
    current_workspace := jsonb_set(current_workspace, '{rfq,phase}', '"awarding"'::jsonb);
    current_workspace := jsonb_set(
        current_workspace, '{stage}', '"Award under review"'::jsonb
    );
    current_workspace := jsonb_set(
        current_workspace,
        '{next_action}',
        '"One award call may proceed after final verification."'::jsonb
    );

    update public.operation_workspaces
       set workspace = current_workspace, updated_at = now()
     where operation_id = p_operation_id;
    update public.operations
       set stage = 'Award under review',
           attention = 'working',
           next_action = 'One award call may proceed after final verification.',
           updated_at = now()
     where id = p_operation_id;

    result := jsonb_build_object(
        'operation_id', p_operation_id,
        'rfq_id', rfq_id,
        'outcome', 'award_requested',
        'message', 'Award request recorded. No commitment is booked until verification completes.',
        'phase', 'awarding',
        'is_demo', false
    );
    insert into public.operator_command_results (
        idempotency_key, operation_id, rfq_id, command_type, result
    ) values (p_idempotency_key, p_operation_id, rfq_id, 'request_award', result);
    return result;
end;
$$;

commit;
