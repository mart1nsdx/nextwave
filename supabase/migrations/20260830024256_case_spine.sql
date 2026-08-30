-- The business spine. Until now every persisted row was keyed by a Twilio CallSid, so
-- nothing in the database represented the thing the business actually cares about: an
-- operation, the mandate authorizing it, the carriers solicited, the offers heard, and
-- the single commitment that may come out of it.
--
-- "Case" is reclaimed here for the *business* case. The per-call row becomes `calls`.
--
-- Nothing in this file lets a call create authority. Mandates are immutable rows; offers
-- carry a status a deterministic policy step sets; commitments are guarded by a partial
-- unique index so a race cannot produce two open bookings (AGENTS.md invariant #5).

alter table public.call_cases rename to calls;

create table public.operations (
    id uuid primary key default gen_random_uuid(),
    tenant_id text not null,
    reference text not null,
    container_number text,
    origin text not null,
    destination text not null,
    eta timestamptz,
    phase text not null default 'draft'
        check (phase in ('draft','soliciting','awarding','awarded','failed','closed')),
    created_at timestamptz not null default now(),
    unique (tenant_id, reference)
);

-- Immutable. A mandate change is a new row with version+1, never an UPDATE.
create table public.mandates (
    id uuid primary key default gen_random_uuid(),
    operation_id uuid not null references public.operations(id) on delete restrict,
    version integer not null check (version >= 1),
    owner_id text not null,
    max_all_in_usd numeric(12,2) not null check (max_all_in_usd > 0),
    pickup_not_before timestamptz not null,
    pickup_not_after timestamptz not null,
    allowed_equipment text[] not null check (array_length(allowed_equipment,1) >= 1),
    commitment_mode text not null check (commitment_mode in ('autonomous','human_escalation')),
    fx_margin_bps integer check (fx_margin_bps >= 0),
    created_at timestamptz not null default now(),
    unique (operation_id, version),
    check (pickup_not_before <= pickup_not_after)
);

create table public.carriers (
    id uuid primary key default gen_random_uuid(),
    tenant_id text not null,
    name text not null,
    is_verified boolean not null default false,
    created_at timestamptz not null default now()
);

create table public.carrier_contacts (
    id uuid primary key default gen_random_uuid(),
    carrier_id uuid not null references public.carriers(id) on delete restrict,
    display_name text,
    phone_e164 text not null,
    email text,
    created_at timestamptz not null default now(),
    unique (phone_e164)
);

create table public.rfqs (
    id uuid primary key default gen_random_uuid(),
    operation_id uuid not null references public.operations(id) on delete restrict,
    mandate_id uuid not null references public.mandates(id) on delete restrict,
    phase text not null default 'soliciting'
        check (phase in ('soliciting','awarding','awarded','failed')),
    created_at timestamptz not null default now()
);

-- RFQ and AWARD are separate phases and only one may be live per operation
-- (AGENTS.md invariant #5).
create unique index rfqs_one_live_per_operation
    on public.rfqs (operation_id)
    where phase in ('soliciting','awarding');

-- rfq_id is NOT NULL on purpose: an inbound call that cannot be resolved to a live RFQ
-- produces an escalation and no offer at all. Fail closed (invariant #6).
create table public.offers (
    id uuid primary key default gen_random_uuid(),
    rfq_id uuid not null references public.rfqs(id) on delete restrict,
    carrier_id uuid not null references public.carriers(id) on delete restrict,
    carrier_contact_id uuid not null references public.carrier_contacts(id) on delete restrict,
    call_id uuid not null references public.calls(id) on delete restrict,
    proposal_id text not null unique,
    source_event_id text not null unique,
    components jsonb not null,
    cost_is_final boolean not null default false,
    pickup_at timestamptz,
    equipment text,
    valid_until timestamptz,
    transcript_anchor_ms integer check (transcript_anchor_ms >= 0),
    carrier_confirmed_exact_recap boolean not null default false,
    confirmed_at timestamptz,
    status text not null default 'proposed'
        check (status in ('proposed','eligible','rejected','accepted','expired')),
    reason_code text,
    created_at timestamptz not null default now()
);

create table public.fx_rate_snapshots (
    id uuid primary key default gen_random_uuid(),
    snapshot_id text not null unique,
    quote_currency text not null check (char_length(quote_currency) = 3),
    usd_per_unit numeric(18,8) not null check (usd_per_unit > 0),
    observed_at timestamptz not null,
    source text not null
);

create table public.commitments (
    id uuid primary key default gen_random_uuid(),
    operation_id uuid not null references public.operations(id) on delete restrict,
    rfq_id uuid not null references public.rfqs(id) on delete restrict,
    offer_id uuid not null references public.offers(id) on delete restrict,
    mandate_id uuid not null references public.mandates(id) on delete restrict,
    mandate_version integer not null,
    canonical_payload_sha256 text not null,
    state text not null default 'prepared'
        check (state in ('prepared','recap_sent','committed','failed','unknown')),
    transcript_anchor_ms integer not null check (transcript_anchor_ms >= 0),
    prepared_at timestamptz not null,
    expires_at timestamptz not null,
    human_approval_id text,
    created_at timestamptz not null default now()
);

-- Two open bookings is the worst failure this system can produce. The database, not a
-- code path, is what makes it impossible.
create unique index commitments_one_committed_per_rfq
    on public.commitments (rfq_id)
    where state = 'committed';

-- Backend uses the service-role key. Dashboard reads go through authenticated API
-- routes, never a browser client touching these tables directly.
alter table public.operations enable row level security;
alter table public.mandates enable row level security;
alter table public.carriers enable row level security;
alter table public.carrier_contacts enable row level security;
alter table public.rfqs enable row level security;
alter table public.offers enable row level security;
alter table public.fx_rate_snapshots enable row level security;
alter table public.commitments enable row level security;

comment on table public.calls is
    'One auditable record per Twilio call. Renamed from call_cases; "case" now means the business case.';
comment on table public.operations is
    'The shipment leg being run. The business case a call belongs to.';
comment on table public.mandates is
    'Immutable human authorization. A change is a new version row, never an UPDATE.';
comment on table public.offers is
    'A heard quote. status is set by deterministic policy; it is never a commitment.';
comment on table public.commitments is
    'The only authorized obligation. At most one committed row per RFQ.';
