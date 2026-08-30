-- Seven overlapping per-call tables collapse into a coherent shape.
--
--   call_recaps + call_briefs      -> call_reports      (same PK, same producer, same
--                                                        trust level: model-generated)
--   call_recap_deliveries          -> outbound_messages (recap email AND official
--                                                        commitment email)
--   call_handoff_events            -> audit_events
--
-- The line that keeps audit_events from becoming a junk drawer:
--   call_transcript_events is evidence of WHAT WAS SAID.
--   audit_events is evidence of WHAT THE SYSTEM DID.
-- If a row is a quote of a human, it is a transcript event. If it is a decision, a
-- directive, a transition or a dispatch, it is an audit event.
--
-- Dropping the superseded tables is deliberately NOT in this migration. It needs a human
-- decision and a backfill; until then the existing Python that reads and writes
-- call_recaps, call_briefs, call_recap_deliveries and call_handoff_events keeps working.

alter table public.calls
    add column if not exists operation_id uuid references public.operations(id),
    add column if not exists rfq_id uuid references public.rfqs(id),
    add column if not exists carrier_id uuid references public.carriers(id),
    -- Added beyond the W1 column contract: without it a CallBinding cannot round-trip
    -- through the database, because carrier_contact would be lost on every resolve.
    add column if not exists carrier_contact_id uuid references public.carrier_contacts(id),
    add column if not exists mandate_id uuid references public.mandates(id),
    add column if not exists phase text check (phase in ('rfq','award','renegotiation','inbound'));

create index calls_rfq_idx on public.calls (rfq_id);
create index offers_rfq_idx on public.offers (rfq_id);

create table public.call_reports (
    call_sid text primary key references public.calls(twilio_call_sid) on delete cascade,
    summary text not null,
    key_points jsonb not null default '[]'::jsonb,
    quoted_prices jsonb not null default '[]'::jsonb,
    names jsonb not null default '[]'::jsonb,
    conditions jsonb not null default '[]'::jsonb,
    objections jsonb not null default '[]'::jsonb,
    changes jsonb not null default '[]'::jsonb,
    mentions jsonb not null default '[]'::jsonb,
    model text not null default '',
    generated_at timestamptz not null default now()
);
-- Note what is NOT here: call_briefs.actions. Actions come from audit_events (W7).

create table public.outbound_messages (
    id uuid primary key default gen_random_uuid(),
    kind text not null check (kind in ('recap','commitment')),
    subject_type text not null check (subject_type in ('call','commitment')),
    subject_id text not null,
    to_email text,
    status text not null default 'pending'
        check (status in ('pending','sent','failed','unknown')),
    provider_message_id text,
    error text,
    sent_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (kind, subject_type, subject_id)
);

create table public.audit_events (
    id uuid primary key default gen_random_uuid(),
    event_key text not null unique,
    subject_type text not null check (subject_type in ('call','handoff','offer','commitment','rfq')),
    subject_id text not null,
    call_id uuid references public.calls(id),
    kind text not null check (kind in (
        'guard_directive','policy_decision','proposal_recorded',
        'escalation_requested','clarification_asked','message_sent','state_transition')),
    from_state text,
    to_state text,
    reason_code text,
    audio_offset_ms integer check (audio_offset_ms >= 0),
    detail jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index audit_events_subject_idx on public.audit_events (subject_type, subject_id, created_at);
create index audit_events_call_idx on public.audit_events (call_id, audio_offset_ms);

alter table public.call_reports enable row level security;
alter table public.outbound_messages enable row level security;
alter table public.audit_events enable row level security;

comment on table public.call_reports is
    'Model-generated report for one call: summary and things mentioned. Evidence, not authority.';
comment on table public.outbound_messages is
    'One row per outbound email attempt. unique(kind,subject_type,subject_id) is the one-attempt gate.';
comment on table public.audit_events is
    'Append-only evidence of what the system did, keyed on event_key. Never what was said.';
