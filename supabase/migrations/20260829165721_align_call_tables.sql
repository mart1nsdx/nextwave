-- Follows 20260829133007. Additive only: no column an existing code path reads changes
-- name or type, so the call -> transcript -> recap -> email path keeps working.
--
-- Three changes:
--   1. call_recaps / call_briefs / call_recap_deliveries reference the natural key
--      twilio_call_sid while call_transcript_events references the surrogate id. Add
--      case_id so every child of a call points at it the same way.
--   2. call_cases learns a vendor-neutral (provider, provider_call_id) pair. A column
--      named twilio_* in a core table contradicts the domain-agnostic core (ARCHITECTURE
--      section 5); the old column stays as the source of truth until nothing reads it.
--   3. The evidence chain needs somewhere to put audio. Deepgram reports offsets as
--      milliseconds since MEDIA STREAM start (backend/app/voice/events.py); a Twilio
--      recording begins at a different instant. Storing only the offset means playback
--      seeks the wrong moment -- which looks like working evidence and is not.

alter table public.call_cases
    add column if not exists provider text not null default 'twilio',
    add column if not exists provider_call_id text,
    add column if not exists clock_reference_at timestamptz;

update public.call_cases
   set provider_call_id = twilio_call_sid
 where provider_call_id is null;

create unique index if not exists call_cases_provider_call_idx
    on public.call_cases (provider, provider_call_id);

comment on column public.call_cases.clock_reference_at is
    'The single clock reference for this call (BUILD.md 2.1). Every offset_ms in the '
    'system is milliseconds from here. Established once at call start.';

-- Deepgram returns a per-result confidence. Invariant #8 ("never infer numbers") has a
-- direct use for it: a low-confidence amount is a reason to ask, not to extract. Cheap
-- to add now, impossible to recover retroactively.
alter table public.call_transcript_events
    add column if not exists confidence real
        check (confidence is null or (confidence >= 0 and confidence <= 1));

alter table public.call_recaps
    add column if not exists case_id uuid references public.call_cases(id) on delete cascade;
alter table public.call_briefs
    add column if not exists case_id uuid references public.call_cases(id) on delete cascade;
alter table public.call_recap_deliveries
    add column if not exists case_id uuid references public.call_cases(id) on delete cascade;

update public.call_recaps r set case_id = c.id
  from public.call_cases c where c.twilio_call_sid = r.call_sid and r.case_id is null;
update public.call_briefs b set case_id = c.id
  from public.call_cases c where c.twilio_call_sid = b.call_sid and b.case_id is null;
update public.call_recap_deliveries d set case_id = c.id
  from public.call_cases c where c.twilio_call_sid = d.call_sid and d.case_id is null;

create index if not exists call_recaps_case_idx on public.call_recaps (case_id);
create index if not exists call_briefs_case_idx on public.call_briefs (case_id);
create index if not exists call_recap_deliveries_case_idx on public.call_recap_deliveries (case_id);

-- Audio artifacts. Nothing writes this yet: no <Record> is configured anywhere in
-- telephony/, so the audio half of the evidence chain currently has no producer. The
-- table exists so that wiring it is a write, not a migration, on demo day.
create table public.recordings (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.call_cases(id) on delete restrict,
    provider text not null default 'twilio',
    provider_recording_id text,
    storage_path text,
    duration_ms integer check (duration_ms is null or duration_ms >= 0),
    -- Recording start minus call_cases.clock_reference_at. Signed on purpose: a recording
    -- may begin after the stream. Playback seeks audio_offset_ms - clock_offset_ms.
    clock_offset_ms integer not null default 0,
    created_at timestamptz not null default now(),
    unique (provider, provider_recording_id)
);

create index recordings_case_idx on public.recordings (case_id);

alter table public.recordings enable row level security;

comment on table public.recordings is
    'One audio artifact per call leg. clock_offset_ms reconciles recording time with the '
    'stream clock that every transcript offset is measured from.';
