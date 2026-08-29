-- Money, and the evidence a currency conversion leaves behind (DECISION_LOG D7, D8, D9).
--
-- Every monetary value in this schema is a PAIR: bigint minor units plus an explicit
-- ISO 4217 code. Never a bare number, never a float. Integer minor units make D9's
-- "round upward to USD cents, never down against a cap" an explicit decision in
-- application code rather than an accident of storage precision.
--
-- D7 fixes USD as the sole policy currency and requires every policy decision to be
-- bound to the immutable snapshot that priced it. Immutable is enforced below by
-- privilege, not by convention: if the row can change, the evidence is worthless.

create table public.fx_rate_snapshots (
    id uuid primary key default gen_random_uuid(),
    provider text not null,
    base_currency char(3) not null default 'USD' check (base_currency ~ '^[A-Z]{3}$'),
    quote_currency char(3) not null check (quote_currency ~ '^[A-Z]{3}$'),
    -- Normalised as USD per ONE unit of quote_currency, which is D7's stated direction.
    -- Fixing the direction in the column name is deliberate: an inverted rate is a
    -- silent 1000x authorization error, and a name is cheaper than a test.
    usd_per_unit numeric(20, 10) not null check (usd_per_unit > 0),
    provider_rate_id text,
    observed_at timestamptz not null,
    fetched_at timestamptz not null default now(),
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    check (expires_at > observed_at),
    check (quote_currency <> base_currency),
    unique (provider, quote_currency, observed_at)
);

create index fx_rate_snapshots_lookup_idx
    on public.fx_rate_snapshots (quote_currency, observed_at desc);

alter table public.fx_rate_snapshots enable row level security;

-- Append-only by privilege. service_role is included deliberately: the backend runs as
-- service_role, and "the backend could rewrite its own evidence" is exactly the property
-- an audit trail must not have.
revoke update, delete on public.fx_rate_snapshots from anon, authenticated, service_role;

comment on table public.fx_rate_snapshots is
    'Immutable FX observation. A policy decision cites the exact snapshot that priced it '
    '(D7). Never populated from model output or from anything a caller said.';
