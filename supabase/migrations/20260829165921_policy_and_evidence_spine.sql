-- The policy and evidence core. Everything here is vertical-free: no container, no
-- pedimento, no port. A different vertical reuses these tables unchanged.
--
-- The organising idea is that the invariants in AGENTS.md are integrity constraints, not
-- coding conventions. Where one can be expressed as an index or a check it is expressed
-- that way, because application code is the layer this architecture declares untrusted.

-- One tenant in practice for the hackathon (BUILD.md cut list). The column is trivial now
-- and impossible to retrofit later, so it goes in even though nothing multiplexes on it.
create table public.tenants (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz not null default now()
);

insert into public.tenants (id, name)
values ('00000000-0000-0000-0000-000000000001', 'Volta demo');

-- ---------------------------------------------------------------- counterparties

create table public.counterparties (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    name text not null check (length(trim(name)) > 0),
    kind text not null check (kind in ('carrier', 'driver', 'client', 'terminal')),
    status text not null default 'active' check (status in ('active', 'suspended', 'unknown')),
    -- DOMAIN.md 2.7: Volta cannot onboard anyone by phone. If a caller invents a carrier
    -- mid-call, refusing to quote them is correct behaviour, not a missing feature.
    is_on_file boolean not null default false,
    created_at timestamptz not null default now()
);

create table public.counterparty_contacts (
    id uuid primary key default gen_random_uuid(),
    counterparty_id uuid not null references public.counterparties(id) on delete cascade,
    name text,
    role text,
    phone text not null check (phone ~ '^\+[1-9][0-9]{6,14}$'),
    is_on_record boolean not null default true,
    created_at timestamptz not null default now()
);

-- Correlating an inbound call starts here. DOMAIN.md 4.1: "I'll call you back" arrives
-- from a number that may or may not be the one on file, and identity level 0 is exactly
-- "this number matches a record".
create unique index counterparty_contacts_phone_on_record_idx
    on public.counterparty_contacts (phone) where is_on_record;
create index counterparty_contacts_phone_idx on public.counterparty_contacts (phone);

-- ---------------------------------------------------------------- operations

create table public.operations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    client_id uuid references public.counterparties(id),
    -- Human-facing folio. Doubles as identity level 1 evidence: only a party to the
    -- operation would know it (BUILD.md 6).
    reference text not null,
    type text not null default 'drayage',
    status text not null default 'draft' check (status in
        ('draft', 'sourcing', 'awarding', 'booked', 'executing', 'closed', 'cancelled')),
    -- Core columns know no logistics. The vertical migration constrains this payload.
    vertical_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (tenant_id, reference)
);

-- ---------------------------------------------------------------- mandates

create table public.mandates (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    operation_id uuid not null references public.operations(id) on delete cascade,
    -- DOMAIN.md 3: an intermediary holds a ceiling from the importer and sets a lower one
    -- for the carrier. A flat cap cannot represent two levels, and the judge's "my boss
    -- approved more" attack is sharper when someone upstream genuinely could have.
    parent_mandate_id uuid references public.mandates(id),
    version integer not null check (version > 0),
    cap_amount_minor bigint not null check (cap_amount_minor > 0),
    cap_currency char(3) not null default 'USD' check (cap_currency ~ '^[A-Z]{3}$'),
    -- D8. NULL is not a zero margin: a non-USD proposal with no explicit human-issued
    -- margin cannot be authorized at all, and policy/ must fail closed on it.
    fx_safety_margin_bps integer
        check (fx_safety_margin_bps is null or fx_safety_margin_bps >= 0),
    window_start timestamptz,
    window_end timestamptz,
    conditions jsonb not null default '{}'::jsonb,
    -- D23/D24: mandate writes happen only from the dashboard, behind OTP + fresh TOTP.
    -- Null until dashboard auth lands; the FK is here so it cannot become a free-text name.
    authorized_by uuid references auth.users(id),
    authorized_at timestamptz not null default now(),
    expires_at timestamptz,
    superseded_by uuid references public.mandates(id),
    created_at timestamptz not null default now(),
    unique (operation_id, version),
    check (window_end is null or window_start is null or window_end > window_start)
);

-- Mandates are versioned rows, never updated in place. A policy decision made ten minutes
-- ago cannot be explained if the cap it was judged against was overwritten -- and D8
-- requires stale mandate versions to fail closed, which needs the old version to exist.
create unique index mandates_one_active_per_operation_idx
    on public.mandates (operation_id) where superseded_by is null;

-- ---------------------------------------------------------------- market

create table public.rfqs (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    operation_id uuid not null references public.operations(id) on delete cascade,
    -- Invariant #5, first half. RFQ gathers offers and creates no obligation; AWARDING
    -- locks the market so exactly one award can happen inside it.
    phase text not null default 'open' check (phase in ('open', 'awarding', 'closed')),
    opened_at timestamptz not null default now(),
    closed_at timestamptz,
    created_at timestamptz not null default now(),
    check (phase <> 'closed' or closed_at is not null)
);

create unique index rfqs_one_live_per_operation_idx
    on public.rfqs (operation_id) where phase in ('open', 'awarding');

create table public.participant_segments (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.call_cases(id) on delete cascade,
    offset_from_ms integer not null check (offset_from_ms >= 0),
    offset_to_ms integer check (offset_to_ms is null or offset_to_ms >= offset_from_ms),
    claimed_identity text,
    -- BUILD.md 6: identity is a level established by evidence, never asserted. policy/
    -- receives it as a plain argument and may only ever use it to require MORE
    -- (invariant #10) -- which is why it lives here and not on the mandate.
    identity_level smallint not null default 0 check (identity_level between 0 and 4),
    resolved_contact_id uuid references public.counterparty_contacts(id),
    created_at timestamptz not null default now()
);

create index participant_segments_case_idx
    on public.participant_segments (case_id, offset_from_ms);

create table public.offers (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    rfq_id uuid not null references public.rfqs(id) on delete cascade,
    counterparty_id uuid not null references public.counterparties(id),
    case_id uuid references public.call_cases(id),
    -- DOMAIN.md 4.1: the phone changes hands. An offer belongs to the segment in which it
    -- was actually said, not to whoever answered.
    participant_segment_id uuid references public.participant_segments(id),
    evidence_offset_ms integer check (evidence_offset_ms is null or evidence_offset_ms >= 0),
    quoted_currency char(3) not null check (quoted_currency ~ '^[A-Z]{3}$'),
    -- D9: "plus tolls", "at cost", uncapped waiting -> the total is not final, and a
    -- non-final total can never be authorized. Defaults to false so silence blocks.
    is_total_final boolean not null default false,
    -- Written by policy/, in Python, with Decimal. NULL until evaluated.
    policy_amount_usd_minor bigint
        check (policy_amount_usd_minor is null or policy_amount_usd_minor >= 0),
    fx_snapshot_id uuid references public.fx_rate_snapshots(id),
    mandate_id uuid references public.mandates(id),
    pickup_window_start timestamptz,
    pickup_window_end timestamptz,
    status text not null default 'proposed' check (status in
        ('proposed', 'superseded', 'withdrawn', 'expired', 'accepted', 'rejected')),
    -- An offer that changes is a new row (invariant #4). A conversation contradicts
    -- itself; both numbers were said, and last-write-wins would destroy the fact the
    -- trial by fire is testing.
    superseded_by uuid references public.offers(id),
    created_at timestamptz not null default now(),
    -- A priced non-USD offer must cite the snapshot that priced it (D7). Without this the
    -- USD amount is an unfalsifiable claim.
    check (policy_amount_usd_minor is null
        or quoted_currency = 'USD'
        or fx_snapshot_id is not null)
);

-- Invariant #5, the half that matters: "two open bookings is the worst possible failure".
-- Three carriers may hold confirmed offers simultaneously; only one may be accepted. When
-- two dispatchers confirm at the same moment -- a real race in a system that dials three
-- at once -- the second insert fails here, rather than in a code path someone remembered.
create unique index offers_one_accepted_per_rfq_idx
    on public.offers (rfq_id) where status = 'accepted';

create index offers_rfq_idx on public.offers (rfq_id, created_at desc);

create table public.offer_cost_components (
    id uuid primary key default gen_random_uuid(),
    offer_id uuid not null references public.offers(id) on delete cascade,
    -- D9 enumerates the scope of an all-in cap. The enum is deliberately closed: a charge
    -- that fits no category is exactly the case that must block authorization rather than
    -- be quietly dropped into a total.
    category text not null check (category in (
        'transport', 'fuel', 'tolls', 'port', 'terminal', 'gate', 'handling', 'inspection',
        'equipment', 'chassis', 'container', 'storage', 'waiting', 'detention', 'demurrage',
        'pickup', 'destination', 'unloading', 'return', 'additional_stop', 'special_cargo',
        'permits', 'security', 'insurance', 'customs', 'tax', 'fee', 'reimbursement',
        'payment_charge', 'contingency', 'discount', 'other')),
    -- Signed: a discount is a negative component, preserved as evidence rather than
    -- folded into the base rate where it stops being auditable.
    amount_minor bigint not null,
    currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
    -- "at cost" or uncapped waiting is unbounded, which makes the offer total non-final.
    is_bounded boolean not null default true,
    is_included boolean not null default true,
    responsibility text not null default 'customer'
        check (responsibility in ('customer', 'carrier', 'shared', 'unknown')),
    source text,
    conditions text,
    created_at timestamptz not null default now()
);

create index offer_cost_components_offer_idx on public.offer_cost_components (offer_id);

-- ---------------------------------------------------------------- commitments

create table public.commitments (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    operation_id uuid not null references public.operations(id) on delete cascade,
    offer_id uuid not null references public.offers(id),
    participant_segment_id uuid not null references public.participant_segments(id),
    -- BUILD.md 4. The last three states arrive hours later and outside the call that
    -- created the commitment, so the model has to accept asynchronous completion: a
    -- boolean "committed" would call a booking valid when no truck exists.
    chain_state text not null default 'VERBAL' check (chain_state in (
        'VERBAL', 'RECAP_SENT', 'COMMITTED', 'RESOURCED', 'DOCUMENTED', 'EXECUTED',
        'RECAP_FAILED', 'NOT_COMMITTED', 'SUPERSEDED')),
    superseded_by uuid references public.commitments(id),
    created_at timestamptz not null default now()
);

create unique index commitments_one_live_per_operation_idx
    on public.commitments (operation_id)
    where superseded_by is null
      and chain_state not in ('RECAP_FAILED', 'NOT_COMMITTED', 'SUPERSEDED');

-- A status column says where a commitment is. The demo has to show how it got there and
-- what authorized each step, including the steps that failed.
create table public.commitment_transitions (
    id uuid primary key default gen_random_uuid(),
    commitment_id uuid not null references public.commitments(id) on delete cascade,
    from_state text,
    to_state text not null,
    reason text,
    actor text not null default 'policy',
    policy_decision_id uuid,
    occurred_at timestamptz not null default now()
);

create index commitment_transitions_commitment_idx
    on public.commitment_transitions (commitment_id, occurred_at);

create table public.evidence (
    id uuid primary key default gen_random_uuid(),
    commitment_id uuid not null references public.commitments(id) on delete cascade,
    -- Nullable only because no recording is produced yet. Invariant #3 is written in
    -- terms of the OFFSET ("no audio offset -> EVIDENCE_MISSING"), which is why the
    -- offset is not null and this is.
    recording_id uuid references public.recordings(id),
    audio_offset_ms integer not null check (audio_offset_ms >= 0),
    transcript_event_id uuid references public.call_transcript_events(id),
    created_at timestamptz not null default now()
);

create index evidence_commitment_idx on public.evidence (commitment_id);

-- ---------------------------------------------------------------- decisions and log

create table public.policy_decisions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    operation_id uuid references public.operations(id) on delete cascade,
    case_id uuid references public.call_cases(id),
    tool_invocation_id uuid,
    -- What it was judged against, captured by value and by reference. D8 requires stale
    -- mandate versions to fail closed; replaying a decision needs both.
    mandate_id uuid references public.mandates(id),
    mandate_version integer,
    fx_snapshot_id uuid references public.fx_rate_snapshots(id),
    identity_level smallint check (identity_level between 0 and 4),
    proposal jsonb not null,
    verdict text not null check (verdict in ('allow', 'deny', 'clarify', 'escalate')),
    reason_code text not null,
    rule_fired text,
    decided_at timestamptz not null default now()
);

create index policy_decisions_operation_idx
    on public.policy_decisions (operation_id, decided_at desc);

comment on table public.policy_decisions is
    'Every evaluation, including denials. The denials are the interesting rows during the '
    'trial by fire: they are the only way to SHOW a refusal rather than assert one.';

create table public.tool_invocations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    case_id uuid references public.call_cases(id),
    tool_name text not null,
    arguments jsonb not null default '{}'::jsonb,
    result jsonb,
    -- BUILD.md 7.5 wants a measured p95, not a claimed one. If this crosses 200ms the
    -- tool moves out of the conversational turn.
    latency_ms integer check (latency_ms is null or latency_ms >= 0),
    outcome text not null check (outcome in ('ok', 'timeout', 'error', 'denied')),
    created_at timestamptz not null default now()
);

create index tool_invocations_case_idx on public.tool_invocations (case_id, created_at);

create table public.escalations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    case_id uuid references public.call_cases(id),
    operation_id uuid references public.operations(id) on delete cascade,
    reason text not null,
    -- Enough for a human to take a live call without reading a transcript (BUILD.md 2.1).
    context_payload jsonb not null default '{}'::jsonb,
    target text,
    raised_at timestamptz not null default now(),
    accepted_at timestamptz
);

create table public.ledger_events (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    operation_id uuid references public.operations(id) on delete cascade,
    case_id uuid references public.call_cases(id),
    type text not null,
    payload jsonb not null default '{}'::jsonb,
    -- Invariant #7. Twilio and the STT provider both redeliver. This is the whole
    -- idempotency mechanism: unique + ON CONFLICT DO NOTHING is atomic, so there is no
    -- read-then-write window for a redelivery to slip through.
    idempotency_key text not null unique,
    created_at timestamptz not null default now()
);

create index ledger_events_operation_idx on public.ledger_events (operation_id, created_at);

alter table public.commitment_transitions
    add constraint commitment_transitions_decision_fk
    foreign key (policy_decision_id) references public.policy_decisions(id);

alter table public.policy_decisions
    add constraint policy_decisions_tool_fk
    foreign key (tool_invocation_id) references public.tool_invocations(id);

-- ---------------------------------------------------------------- the database says no

-- A cross-table invariant a CHECK cannot express: no commitment becomes binding without
-- an evidence row. BUILD.md's risk table asks for this in policy/; having it here too
-- means it cannot be forgotten in a hurry at hour 20.
--
-- This is not business logic in the database. The trigger cannot authorize anything -- it
-- can only refuse, in the same direction as a foreign key. policy/ remains the sole
-- grantor of permission; the database is a second party that can say no.
create or replace function public.enforce_commitment_evidence()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.to_state in ('COMMITTED', 'RESOURCED', 'DOCUMENTED', 'EXECUTED') then
        if not exists (
            select 1
              from public.evidence e
             where e.commitment_id = new.commitment_id
        ) then
            raise exception
                'commitment % cannot reach % with no evidence row (AGENTS.md invariant #3)',
                new.commitment_id, new.to_state
                using errcode = 'check_violation';
        end if;
    end if;
    return new;
end;
$$;

create trigger commitment_transitions_require_evidence
    before insert on public.commitment_transitions
    for each row execute function public.enforce_commitment_evidence();

-- Append-only by privilege, not by convention (invariant #4). service_role is included
-- deliberately: the backend runs as service_role, and "the backend can rewrite its own
-- audit trail" is precisely the property an audit trail must not have.
--
-- Note which tables are NOT here. offers, mandates and commitments carry superseded_by,
-- which is set on the older row -- so they are mutable by design, and their immutable
-- history lives in commitment_transitions and in the version chain instead.
revoke update, delete on
    public.policy_decisions,
    public.commitment_transitions,
    public.evidence,
    public.ledger_events,
    public.tool_invocations
from anon, authenticated, service_role;

-- ---------------------------------------------------------------- RLS

alter table public.tenants                enable row level security;
alter table public.counterparties         enable row level security;
alter table public.counterparty_contacts  enable row level security;
alter table public.operations             enable row level security;
alter table public.mandates               enable row level security;
alter table public.rfqs                   enable row level security;
alter table public.participant_segments   enable row level security;
alter table public.offers                 enable row level security;
alter table public.offer_cost_components  enable row level security;
alter table public.commitments            enable row level security;
alter table public.commitment_transitions enable row level security;
alter table public.evidence               enable row level security;
alter table public.policy_decisions       enable row level security;
alter table public.tool_invocations       enable row level security;
alter table public.escalations            enable row level security;
alter table public.ledger_events          enable row level security;

-- The read model for dashboard/ (BUILD.md 2.1, Persona 3 -> Persona 4).
--
-- This reverses the comment in 20260829125514, which said dashboard reads go through
-- authenticated API routes. Both cannot hold: BUILD.md promises a read model over
-- Supabase Realtime, and postgres_changes fires against tables under RLS -- a backend
-- proxy cannot deliver it. SELECT is opened to authenticated; every write stays denied to
-- every role but service_role.
--
-- using (true) is correct for one tenant. It becomes a tenant predicate the day a second
-- one exists, which is why tenant_id is already on every row.
create policy "read model: authenticated may select"
    on public.operations for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.mandates for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.rfqs for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.offers for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.offer_cost_components for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.commitments for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.commitment_transitions for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.evidence for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.policy_decisions for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.escalations for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.counterparties for select to authenticated using (true);

-- ---------------------------------------------------------------- display

-- Renders a stored USD policy amount back into the quote currency, using the exact
-- snapshot the decision cited.
--
-- This view FORMATS; it never decides. Conversion for authorization happens once, in
-- Python, with Decimal (D7's server-side contract). A plpgsql conversion function would
-- be a second implementation of the cap rule that can silently disagree with policy/ --
-- the one failure this architecture cannot absorb. So the database stores the inputs and
-- the outputs as evidence, and offers this for the dashboard to render.
create view public.offer_display
with (security_invoker = true) as
select
    o.id                       as offer_id,
    o.rfq_id,
    o.counterparty_id,
    o.status,
    o.is_total_final,
    o.quoted_currency,
    o.policy_amount_usd_minor,
    f.usd_per_unit,
    f.observed_at              as rate_observed_at,
    case
        when o.policy_amount_usd_minor is null then null
        when o.quoted_currency = 'USD'         then o.policy_amount_usd_minor
        when f.usd_per_unit is null            then null
        else round(o.policy_amount_usd_minor / f.usd_per_unit)::bigint
    end                        as display_amount_minor,
    o.created_at
from public.offers o
left join public.fx_rate_snapshots f on f.id = o.fx_snapshot_id;
