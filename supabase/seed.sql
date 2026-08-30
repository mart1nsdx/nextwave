-- Demo seed. Not reference data: every row here is invented, and DOMAIN.md 7 is the
-- authority on what is real and what is mocked.
--
-- On the numbers. The published 2024 tariff for Manzanillo -> Guadalajara is MXN 20,988
-- base / 26,085.20 subtotal (DOMAIN.md 2.5), which is far above the challenge's fictional
-- MXN 9,000 mandate. DOMAIN.md says explicitly not to silently "fix" that, so these rates
-- stay on the challenge's fictional scale and are internally consistent with the cap. If
-- the number comes up in the pitch, knowing the real tariff is a point in our favour.

begin;

insert into public.lanes (id, origin, destination, distance_km) values
  ('11111111-1111-1111-1111-111111111111', 'Manzanillo', 'Guadalajara', 320);

insert into public.counterparties (id, tenant_id, name, kind, is_on_file) values
  ('22222222-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Textiles Pacifico',    'client',  true),
  ('22222222-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Fletes del Pacifico',  'carrier', true),
  ('22222222-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Transportes Colima',   'carrier', true),
  ('22222222-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Autolineas Manzanillo','carrier', true),
  -- Not on file. If a caller invents this carrier mid-call the correct behaviour is to
  -- refuse to quote them (DOMAIN.md 2.7) -- a robustness argument worth making out loud.
  ('22222222-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Transportes Fantasma', 'carrier', false);

insert into public.counterparty_contacts (counterparty_id, name, role, phone, is_on_record) values
  ('22222222-0000-0000-0000-000000000002', 'Luis Ramirez',  'dispatcher', '+523141000001', true),
  ('22222222-0000-0000-0000-000000000003', 'Ana Beltran',   'dispatcher', '+523141000002', true),
  ('22222222-0000-0000-0000-000000000004', 'Jorge Mendoza', 'dispatcher', '+523141000003', true);

-- Personalities. Without conflicting ones the quote comparison demonstrates nothing
-- (DOMAIN.md 7), and DOMAIN.md 2.4's point -- that the cheapest freight can be the most
-- expensive operation once demurrage is counted -- has nothing to bite on.
--   Pacifico  : cheapest, slow, unreliable  -> wins on price, loses on expected cost
--   Colima    : mid price, fast, reliable   -> should win on expected total cost
--   Autolineas: fastest, over the cap       -> must be refused, not negotiated down
insert into public.rate_cards (counterparty_id, lane_id, base_amount_minor, currency, typical_lead_time_hours, reliability_bps) values
  ('22222222-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111',  980000, 'MXN', 48, 6500),
  ('22222222-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 1060000, 'MXN', 24, 9200),
  ('22222222-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 1240000, 'MXN', 12, 8800);

-- What "on file" means (DOMAIN.md 2.7). These are also the fields a Carta Porte demands.
insert into public.carrier_documents (counterparty_id, kind, identifier, valid_until) values
  ('22222222-0000-0000-0000-000000000002', 'rfc',         'FPA950101AB1', null),
  ('22222222-0000-0000-0000-000000000002', 'sict_permit', 'SICT-CF-114522', '2027-03-31'),
  ('22222222-0000-0000-0000-000000000003', 'rfc',         'TCO880214QX7', null),
  ('22222222-0000-0000-0000-000000000003', 'sict_permit', 'SICT-CF-220913', '2027-09-30'),
  ('22222222-0000-0000-0000-000000000004', 'rfc',         'AMZ010704LM4', null),
  ('22222222-0000-0000-0000-000000000004', 'sict_permit', 'SICT-CF-330417', '2026-12-31');

-- Container number carries a real ISO 6346 check digit; the constraint added in
-- 20260829170519 refuses anything else.
insert into public.operations (id, tenant_id, client_id, reference, status, vertical_payload) values
  ('33333333-3333-3333-3333-333333333333',
   '00000000-0000-0000-0000-000000000001',
   '22222222-0000-0000-0000-000000000001',
   'OP-MZO-0001', 'sourcing',
   '{"container_number":"MSCU1234566","bill_of_lading":"MEDUMZ0099231","ocean_carrier":"MSC","vessel":"MSC Rania","voyage":"FT534A","origin_terminal":"Contecon Manzanillo","destination_address":"Av. Lopez Mateos 1200, Guadalajara, Jalisco","destination_postal_code":"44940","cargo_description":"Textiles","weight_kg":18400,"packages":620}'::jsonb);

-- The two clocks (DOMAIN.md 2.3). This is what makes the operation urgent and what the
-- dashboard renders counting down.
insert into public.operation_clocks (operation_id, free_days, last_free_day, discharged_at) values
  ('33333333-3333-3333-3333-333333333333', 5, current_date + 3, now() - interval '2 days');

-- USD cap, per D7. fx_safety_margin_bps is SEED DATA, not an approved margin: D10 requires
-- an authenticated human to accept or override an RT recommendation before a value carries
-- authority, and says the concrete bps must not be invented during implementation. In a
-- real operation a null margin makes a non-USD proposal unauthorizable (D8), by design.
insert into public.mandates (id, tenant_id, operation_id, version, cap_amount_minor, cap_currency,
                             fx_safety_margin_bps, window_start, window_end, status) values
  ('44444444-4444-4444-4444-444444444444',
   '00000000-0000-0000-0000-000000000001',
   '33333333-3333-3333-3333-333333333333',
   1, 60000, 'USD', 200, current_date + 1, current_date + 2, 'active');

-- Why USD 600 and not the USD 550 of D9's worked example: at 600 both Pacifico and Colima
-- are eligible, and the seed then makes a live disagreement visible rather than hiding it.
--   D32 awards the LOWEST ELIGIBLE BUFFERED USD candidate           -> Fletes del Pacifico (499.80)
--   DOMAIN.md 2.4 ranks by EXPECTED TOTAL COST incl. demurrage risk -> Transportes Colima  (556.60)
-- Two written rules, two different carriers, same data. Someone has to decide which one
-- market/ implements; the seed exists so that decision is made deliberately.
-- Autolineas busts the cap on buffered freight alone and must be refused under either.

insert into public.rfqs (id, tenant_id, operation_id, phase) values
  ('55555555-5555-5555-5555-555555555555',
   '00000000-0000-0000-0000-000000000001',
   '33333333-3333-3333-3333-333333333333', 'open');

-- One observation, so an MXN quote can be priced into the USD cap. Fetched server-side in
-- real use; never from model output or from anything a caller said (D7).
insert into public.fx_rate_snapshots (id, provider, quote_currency, usd_per_unit, observed_at, expires_at) values
  ('66666666-6666-6666-6666-666666666666', 'seed', 'MXN', 0.0500000000, now(), now() + interval '1 day');

commit;
