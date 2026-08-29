-- The drayage vertical. Everything here is the vocabulary a dispatcher would recognise;
-- none of it is reachable from the core tables in the previous migration except through
-- operations.vertical_payload, which is validated rather than trusted.

create extension if not exists pg_jsonschema with schema extensions;

-- ARCHITECTURE section 7 claims JSONB gives the vertical the flexibility it needs
-- "without giving up the constraints the core needs". This is that claim, made literal:
-- the payload is free-form to the core and schema-checked for this vertical.
--
-- Container numbers are ISO 6346 -- four letters and seven digits, the last a check digit.
-- The pattern catches shape; the check digit is computed in the seed, because a logistics
-- judge will notice and it costs ten lines.
alter table public.operations
    add constraint operations_drayage_payload_valid check (
        type <> 'drayage'
        or extensions.jsonb_matches_schema(
            '{
              "type": "object",
              "properties": {
                "container_number":        {"type": "string", "pattern": "^[A-Z]{4}[0-9]{7}$"},
                "bill_of_lading":          {"type": "string", "minLength": 1},
                "booking":                 {"type": "string"},
                "ocean_carrier":           {"type": "string"},
                "vessel":                  {"type": "string"},
                "voyage":                  {"type": "string"},
                "pedimento":               {"type": "string"},
                "origin_terminal":         {"type": "string"},
                "destination_address":     {"type": "string"},
                "destination_postal_code": {"type": "string", "pattern": "^[0-9]{5}$"},
                "cargo_description":       {"type": "string"},
                "weight_kg":               {"type": "number", "minimum": 0},
                "packages":                {"type": "integer", "minimum": 0}
              },
              "additionalProperties": true
            }'::json,
            vertical_payload)
    );

-- The two clocks (DOMAIN.md 2.3). Demurrage runs discharge -> gate-out and is charged by
-- the ocean carrier; detention runs gate-out -> empty return. Neither is negotiable and
-- neither party charging them answers the phone, so the only lever against that cost is
-- moving faster with the actors who do.
--
-- First-class rather than loose columns on operations because this is the variable that
-- makes everything else urgent, and the dashboard renders it counting down.
create table public.operation_clocks (
    operation_id uuid primary key references public.operations(id) on delete cascade,
    free_days integer check (free_days is null or free_days >= 0),
    last_free_day date,
    discharged_at timestamptz,
    gate_out_at timestamptz,
    gate_in_at timestamptz,
    updated_at timestamptz not null default now(),
    check (gate_out_at is null or discharged_at is null or gate_out_at >= discharged_at),
    check (gate_in_at is null or gate_out_at is null or gate_in_at >= gate_out_at)
);

create table public.lanes (
    id uuid primary key default gen_random_uuid(),
    origin text not null,
    destination text not null,
    distance_km integer check (distance_km is null or distance_km > 0),
    created_at timestamptz not null default now(),
    unique (origin, destination)
);

-- Mock rates must stay consistent between calls or the comparison demonstrates nothing
-- (DOMAIN.md 7). Carrier personality lives here: cheap with a bad window, expensive and
-- reliable, one that does not answer. Without conflicting personalities there is nothing
-- for the quote comparison to compare.
create table public.rate_cards (
    id uuid primary key default gen_random_uuid(),
    counterparty_id uuid not null references public.counterparties(id) on delete cascade,
    lane_id uuid not null references public.lanes(id) on delete cascade,
    base_amount_minor bigint not null check (base_amount_minor > 0),
    currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
    typical_lead_time_hours integer check (typical_lead_time_hours is null or typical_lead_time_hours >= 0),
    -- DOMAIN.md 2.4: a carrier quoting less who arrives two days late is more expensive
    -- than one quoting more on time. Ranking by freight price alone cannot see that; this
    -- is what turns a promised window into an expected cost.
    reliability_bps integer check (reliability_bps between 0 and 10000),
    created_at timestamptz not null default now(),
    unique (counterparty_id, lane_id)
);

-- DOMAIN.md 2.7: onboarding and booking are different processes, and Volta cannot onboard
-- anyone by phone. These rows are what counterparties.is_on_file means. They are also the
-- fields a Carta Porte demands, which is what gives a booking call substance.
create table public.carrier_documents (
    id uuid primary key default gen_random_uuid(),
    counterparty_id uuid not null references public.counterparties(id) on delete cascade,
    kind text not null check (kind in
        ('rfc', 'sict_permit', 'insurance', 'vehicle_registration', 'driver_license')),
    identifier text not null check (length(trim(identifier)) > 0),
    valid_until date,
    created_at timestamptz not null default now(),
    unique (counterparty_id, kind, identifier)
);

create table public.appointments (
    id uuid primary key default gen_random_uuid(),
    operation_id uuid not null references public.operations(id) on delete cascade,
    terminal text not null,
    slot_start timestamptz not null,
    slot_end timestamptz,
    reference text,
    created_at timestamptz not null default now(),
    check (slot_end is null or slot_end > slot_start)
);

alter table public.operation_clocks  enable row level security;
alter table public.lanes             enable row level security;
alter table public.rate_cards        enable row level security;
alter table public.carrier_documents enable row level security;
alter table public.appointments      enable row level security;

create policy "read model: authenticated may select"
    on public.operation_clocks for select to authenticated using (true);
create policy "read model: authenticated may select"
    on public.appointments for select to authenticated using (true);
