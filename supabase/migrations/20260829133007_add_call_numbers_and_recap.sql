-- Follows 20260829125514_create_call_transcripts.sql. That migration is already
-- committed to the shared branch, so this adds to it rather than editing it.
--
-- Two changes:
--   1. call_cases learns the phone numbers on both legs, so evidence can be looked
--      up by who called, not only by Twilio's opaque CallSid.
--   2. call_recaps / call_briefs hold the post-call analysis. Neither is a commitment:
--      they are model-generated evidence that a later policy check reads.

alter table public.call_cases
    add column if not exists from_number text,
    add column if not exists to_number text;

create index if not exists call_cases_from_number_idx
    on public.call_cases (from_number);

create table public.call_recaps (
    call_sid text primary key references public.call_cases(twilio_call_sid) on delete cascade,
    summary text not null,
    key_points jsonb not null default '[]'::jsonb,
    quoted_prices jsonb not null default '[]'::jsonb,
    names jsonb not null default '[]'::jsonb,
    conditions jsonb not null default '[]'::jsonb,
    objections jsonb not null default '[]'::jsonb,
    changes jsonb not null default '[]'::jsonb,
    model text not null default '',
    generated_at timestamptz not null default now()
);

-- Email delivery state for the recap. 'sent' is what a policy step waits on before it
-- lets a commitment reach COMMITTED; 'failed' means RECAP_FAILED / NOT_COMMITTED.
create table public.call_recap_deliveries (
    call_sid text primary key references public.call_cases(twilio_call_sid) on delete cascade,
    status text not null default 'pending' check (status in ('pending', 'sent', 'failed')),
    to_email text,
    provider_message_id text,
    error text,
    sent_at timestamptz,
    updated_at timestamptz not null default now()
);

create table public.call_briefs (
    call_sid text primary key references public.call_cases(twilio_call_sid) on delete cascade,
    actions jsonb not null default '[]'::jsonb,
    mentions jsonb not null default '[]'::jsonb,
    model text not null default '',
    generated_at timestamptz not null default now()
);

-- Backend uses the service-role key. Dashboard reads go through authenticated API
-- routes, never a browser client touching these tables directly.
alter table public.call_recaps enable row level security;
alter table public.call_briefs enable row level security;
alter table public.call_recap_deliveries enable row level security;

comment on table public.call_recaps is
    'Model-generated summary of one call. Evidence for a policy check, not a commitment.';
comment on table public.call_briefs is
    'Structured log of agent actions and things mentioned on one call.';
comment on table public.call_recap_deliveries is
    'Email delivery state for a call recap. status=sent gates COMMITTED.';
