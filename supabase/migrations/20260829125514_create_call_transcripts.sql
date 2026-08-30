-- Call evidence belongs to the audit trail, never to the commitment state machine.
-- This migration stores the case created for one Twilio call and the immutable
-- transcript events that can later be linked to an audio offset.

create table public.call_cases (
    id uuid primary key default gen_random_uuid(),
    twilio_call_sid text not null unique,
    direction text not null check (direction in ('inbound', 'outbound')),
    status text not null default 'active' check (status in ('active', 'ended', 'failed')),
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    check ((status = 'ended' and ended_at is not null) or status <> 'ended')
);

create table public.call_transcript_events (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.call_cases(id) on delete restrict,
    event_key text not null unique,
    track text not null check (track in ('inbound', 'outbound')),
    speaker text not null default 'unknown' check (speaker in ('caller', 'agent', 'unknown')),
    sequence_number bigint not null check (sequence_number >= 0),
    audio_offset_ms integer not null check (audio_offset_ms >= 0),
    text text not null check (length(trim(text)) > 0),
    is_final boolean not null default false,
    created_at timestamptz not null default now(),
    unique (case_id, track, sequence_number)
);

create index call_transcript_events_case_offset_idx
    on public.call_transcript_events (case_id, audio_offset_ms);

-- The backend uses the service-role key. No browser client gets direct access
-- to call evidence; dashboard reads must be exposed through authenticated API routes.
alter table public.call_cases enable row level security;
alter table public.call_transcript_events enable row level security;

comment on table public.call_cases is
    'One auditable case for a Twilio call. It is not a booking or commitment.';
comment on table public.call_transcript_events is
    'Append-only STT evidence with an idempotency key and Twilio audio offset.';
