-- Model-extracted agreement evidence. These remain candidates until deterministic
-- policy verifies the mandate, confirmation and written-recap delivery gates.
alter table public.call_recaps
    add column if not exists agreement_candidates jsonb not null default '[]'::jsonb,
    add constraint call_recaps_agreement_candidates_are_array
        check (jsonb_typeof(agreement_candidates) = 'array');

comment on column public.call_recaps.agreement_candidates is
    'Audio-anchored, model-extracted agreement candidates; never committed authority.';
