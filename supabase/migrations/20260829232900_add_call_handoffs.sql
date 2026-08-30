-- A handoff is an escalation record, never a booking or a commitment. The unique case_id
-- enforces at most one active transfer attempt for a call even if Twilio redelivers.

create table public.call_handoffs (
    id uuid primary key,
    case_id uuid not null unique references public.call_cases(id) on delete restrict,
    reason text not null check (reason in (
        'direct_request', 'outside_mandate', 'ambiguous_critical_term',
        'conflicting_information', 'policy_failure', 'technical_failure'
    )),
    evidence_offset_ms integer not null check (evidence_offset_ms >= 0),
    note text not null check (length(trim(note)) > 0),
    status text not null check (status in (
        'proposed', 'authorized', 'caller_on_hold', 'human_dialing', 'connected',
        'declined', 'failed', 'completed'
    )),
    conference_name text unique,
    operator_call_sid text unique,
    created_at timestamptz not null default now()
);

create table public.call_handoff_events (
    id uuid primary key default gen_random_uuid(),
    handoff_id uuid not null references public.call_handoffs(id) on delete restrict,
    event_key text not null unique,
    status text not null check (status in (
        'proposed', 'authorized', 'caller_on_hold', 'human_dialing', 'connected',
        'declined', 'failed', 'completed'
    )),
    detail text,
    created_at timestamptz not null default now()
);

create index call_handoff_events_handoff_created_idx
    on public.call_handoff_events (handoff_id, created_at);

alter table public.call_handoffs enable row level security;
alter table public.call_handoff_events enable row level security;

comment on table public.call_handoffs is
    'One idempotent escalation request per call; no row represents a commitment.';
comment on table public.call_handoff_events is
    'Append-only Twilio handoff lifecycle evidence.';
