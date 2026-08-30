# Decision log

One entry per decision that a teammate could reasonably have made differently. The point
is not ceremony — it is so that in hour 18 nobody re-litigates a tradeoff from hour 2, and
so the "why" survives into the demo. Newest at the bottom.

Format: what was decided, what it beat, and what would make us change our mind.

---

## D1 — Deterministic policy engine, not an LLM safety check

**Decided:** authorization is plain Python in `backend/app/policy/`. The price cap is an
`if` statement.

**Beat:** asking the model to self-check ("do not exceed the cap"), which is the default
approach and reads well in a prompt.

**Why:** a prompt-based check fails exactly when it matters — when a persuasive human
argues with it. The trial-by-fire is an adversarial human on the phone. A deterministic
gate cannot be argued with.

**Would change if:** never, for authorization. This is the project's thesis.

## D2 — `domain/` as a shared leaf package

**Decided:** core types (Operation, Quote, Commitment, Mandate) live in `domain/`, which
imports nothing.

**Beat:** putting them in `policy/`, which would have kept the package count lower.

**Why:** `tools/`, `ledger/`, `repo/`, and `market/` all need `Quote` and `Commitment`.
Without a leaf they either duplicate or all import from `policy/`, which destroys the
"policy is a pure sink" property that the whole design rests on. One directory buys a
clean acyclic graph.

**Would change if:** the type set stays under ~3 classes, which it won't.

## D3 — Layering enforced by a test, not a convention

**Decided:** `backend/tests/test_layering.py` holds the allowed-import map as data and
fails the build on any edge outside it.

**Beat:** documenting the layering in `AGENTS.md` and trusting reviewers.

**Why:** four people and their agents editing in parallel for 24 hours. A convention that
is only in a doc degrades within hours, and the degradation is invisible until a judge
exploits it live. ~40 lines of stdlib `ast` makes it structural. We verified it fails
before trusting it.

**Would change if:** it produces false positives that slow people down. It hasn't.

## D4 — uv over pip + requirements.txt

**Decided:** `uv` with a committed `uv.lock`, Python pinned to 3.12.

**Beat:** the `venv` + `requirements.txt` flow originally written into `AGENTS.md`.

**Why:** four people syncing dependencies repeatedly on a shared clock. Fast resolution
and a real lockfile mean "works on my machine" doesn't cost anyone 20 minutes. 3.12
rather than 3.14 for wheel availability across twilio/supabase/pydantic.

**Cost:** everyone needs `uv` installed. Accepted.

## D5 — Vite + React for the dashboard, not Next.js

**Decided:** Vite + React + TypeScript, one screen, no router, no state library.

**Beat:** Next.js, which the original `.gitignore` implied.

**Why:** the dashboard is one read-mostly screen. Next.js brings SSR, routing, and an API
layer we would not use — capability we couldn't justify if asked why it's there. The
backend already owns the API.

**Would change if:** the dashboard needed server-side auth or multiple routes.

## D6 — Communal CHANGELOG.md, cross-cutting changes only

**Decided:** one root `CHANGELOG.md`, newest-first, written only when a change affects
someone else's module or a shared contract.

**Beat:** (a) a `changelog.d/` fragment directory generated into a file, which is
structurally merge-conflict-free; (b) logging every commit.

**Why:** the log's job is "what did the other three change while I was heads down?" —
which needs one chronological view you read top-down, and needs to stay short enough to
actually read. Fragments solve conflicts but add a build step and aren't readable until
generated. Logging every commit duplicates `git log` with worse tooling.

**Cost:** concurrent appends conflict. Mitigated by a rule in both `AGENTS.md` and the
file header: keep both entries, order by timestamp, never resolve by deleting.

## D7 — Cascade STT → LLM → TTS, not OpenAI's Realtime API

**Decided:** the voice path is three separable stages — Deepgram recognises, an OpenAI
model reasons via the Agents SDK, Deepgram synthesises — orchestrated by us in `voice/`.
`realtime/` was renamed to `voice/` accordingly; keeping the old name would have
described a vendor we no longer use.

**Beat:** OpenAI's speech-to-speech Realtime API, which `docs/CHALLENGE.md` explicitly
suggests ("its Realtime API is a natural fit").

**Why:** three reasons, in order of weight.

1. **We own the turn.** The trial-by-fire is a judge interrupting mid-sentence. With a
   cascade, barge-in is our code: local VAD fires in ~20 ms, we send Twilio `clear`,
   Deepgram `Clear`, and cancel the model run. With speech-to-speech, interruption
   behaviour is the vendor's, and we cannot tune it at hour 20.
2. **Providers are swappable under time pressure.** STT accuracy on a noisy Mexican
   phone line is the single largest risk to the demo, and it is not knowable in advance.
   `STT_PROVIDER` is a one-line change behind a Protocol. Speech-to-speech is all or
   nothing.
3. **The transcript is a first-class artifact, not a byproduct.** The challenge demands
   commitments linked to audio offsets and a call brief. A cascade produces timestamped
   text as its natural intermediate; speech-to-speech makes us ask for it separately.

**Cost:** more moving parts and more latency than one hop — roughly STT endpoint +
model + TTS first-byte rather than a single round-trip. Mitigated by streaming every
stage and by mu-law 8 kHz end to end, so nothing resamples.

**Would change if:** our own barge-in measures worse on a real line than Realtime's, or
cascade latency lands somewhere a dispatcher reads as dead air. Both are measurable on
a real call, and that measurement is the trigger — not a preference.

## D8 — The mandate figures are rendered into the prompt, and never spoken

**Decided:** the price ceiling and target for the operation go into the system prompt,
under a block that forbids ever saying them out loud. `agent/context.py` carries them;
`prompts.py` renders them.

**Beat:** (a) keeping them out entirely, so the agent proposes blind and learns the answer
only from `policy.evaluate()`; (b) giving it a target but not the ceiling.

**Why:** an agent that cannot tell a number worth pushing on from one that is not either
accepts the first quote or argues with every quote. Both look bad on a call, and the
demo is a negotiation. Option (a) is the safer design and it stays the fallback.

**Cost, stated plainly:** a prompt is text a counterparty can argue with, and a persistent
one can talk a figure out of a model. Two things contain that, and neither may be removed:
the prompt forbids saying the figures, and `policy/` still decides every proposal — so a
leaked ceiling is an embarrassment, not an authorization. Invariant #2 is untouched: the
mandate is still immutable from inside the call, because nothing the model says can write
it.

**Would change if:** a figure leaks on a live call, or a judge extracts one. The fix then
is to stop rendering it — not to add another sentence asking the model more nicely.

---

# Person 2 security and policy decisions

## D1 / Person 2 D-01 — Deterministic reference monitor plus defense-in-depth

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T13:37-05:00

**Context:** caller speech, transcripts, model output, and tool arguments are untrusted.
Volta needs a root of trust that prevents an incorrect or prompt-injected model from
authorizing a consequential action outside the current server-side mandate.

**Alternatives considered:**

- **A — Prompt-only enforcement.** Fastest to demo, but the model remains the
  authorization boundary. A persuasive caller or model error can turn a behavioral
  failure into an unauthorized action. This is weakest under Trial-by-Fire.
- **B — Prompt plus probabilistic guardrail/model validator.** Adds useful attack
  detection and behavioral defense, but the final safety decision still depends on
  probabilistic inference. It also adds latency, cost, and another failure mode without
  making the price cap a deterministic invariant.
- **C — Deterministic reference monitor plus defense-in-depth.** The model emits a typed
  proposal; strict server-side validation and plain Python policy evaluate it against the
  authoritative current mandate and state before any consequential mutation. Prompts,
  classifiers, and tool guardrails remain auxiliary defenses, never the root of trust.

**Decided:** Alternative C. Authorization lives in `backend/app/policy/` and every
consequential mutation must be completely mediated by deterministic policy. The LLM is
an untrusted proposer, not an authorization authority.

**Why:** C makes hard mandate limits explainable and deterministically testable even if
conversation behavior is manipulated. It is the strongest Trial-by-Fire design and is
consistent with the project's existing trust-layer architecture.

**Trade-off accepted:** the first build hours go to schemas, policy tests, state
contracts, and mediation instead of conversational polish. This is accepted to prevent
unauthorized commitments and reduce late integration ambiguity.

**Implementation contract:**

- Caller/model content cannot mutate the authoritative mandate.
- The model receives proposal/read/escalation capabilities only; no direct commitment,
  award, mandate-mutation, arbitrary database, HTTP, or shell capability.
- Every consequential state mutation revalidates the exact proposal against the current
  authoritative mandate and state, and fails closed on malformed, stale, unavailable, or
  ambiguous inputs.
- Import layering alone is insufficient: mutation endpoints require negative bypass
  tests proving complete mediation.
- Guardrails and injection classifiers may improve behavior or telemetry but cannot
  return authoritative permission.

**Verification:** NOT RUN. Required evidence will include price-cap boundary tests,
prompt-injection metamorphic tests, stale-state tests, route/tool bypass tests, and an
integrated live-call attempt that produces zero unauthorized side effects.

**Would change if:** never to prompt-only or probabilistic authorization. The internal
deployment shape may be simplified if the same deterministic complete-mediation
property and tests are preserved.

## D7 / Person 2 D-02B — USD policy currency with controlled hybrid FX conversion

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T13:52-05:00

**Context:** users configure mandates and caps in one authoritative currency, while
carriers may quote in other currencies. Conversion must be deterministic, reproducible,
and independent of caller or model claims. "Real-time conversion" means conversion at
policy-evaluation time using a timestamped rate snapshot; it does not imply that a daily
reference rate is a continuously tradable market price.

**Alternatives considered:**

- **A — Official daily reference rates only.** Highly auditable and authoritative for
  covered pairs, but no single official source covers every ISO 4217 currency. Business
  days, publication delays, and narrow coverage can force avoidable escalations.
- **B — One commercial near-real-time provider only.** Broad coverage and a simple API,
  but creates a single vendor, availability, rate-limit, and data-quality dependency.
  A quoted provider rate may also differ from the eventual executable bank rate.
- **C — Controlled hybrid.** Use one explicitly approved broad-coverage primary provider,
  official reference adapters where relevant, and immutable cached rate snapshots under
  an approved freshness policy. Never silently switch providers; fail closed if no
  approved usable rate exists.

**Decided:** Alternative C. `USD` is Volta's sole internal mandate, budget, comparison,
ranking, and policy-decision currency. A carrier may quote any explicitly identified,
supported ISO 4217 currency. Country, locale, or a currency symbol never determines the
currency implicitly.

**Why:** C preserves broad Trial-by-Fire coverage without allowing the model to invent
rates, while retaining official benchmarks and reproducible authorization evidence. It
also keeps all user-defined authority comparable in one currency.

**Trade-off accepted:** the FX boundary adds a provider adapter, caching, freshness and
rounding rules, audit fields, outage behavior, and tests. Foreign quotes may escalate
when approved rate data is unavailable rather than being guessed.

**Implementation contract:**

- Preserve every original amount and ISO 4217 currency; never overwrite it with USD.
- Convert server-side with `Decimal`, using a normalized `USD per source unit` rate.
- Store provider, rate identifier when available, observed/fetched/expiry timestamps,
  conversion timestamp, direction, unrounded result, rounding rule, and policy amount.
- Round the USD authorization amount upward to the smallest USD unit; never round down
  against a cap.
- Bind the policy decision to the immutable FX snapshot used for that evaluation.
- Unknown, ambiguous, unsupported, stale, unavailable, or model/caller-supplied rates
  produce `CLARIFY` or `ESCALATE` with zero consequential side effects.
- Mixed-currency cost components are converted separately and then summed in USD without
  double counting.
- FX provider, freshness/cache limits, divergence checks, and safety-margin policy remain
  separate decisions and may not be silently selected during implementation.

**Verification:** NOT RUN. Required evidence includes direction/rounding unit tests,
ISO-code validation, stale/unavailable/provider-divergence tests, immutable-snapshot
replay, mixed-currency totals, and metamorphic tests proving caller-provided rates cannot
change authorization.

**Would change if:** USD ceases to be the business authority currency or the approved
provider cannot meet required coverage/reliability. Any replacement must preserve
deterministic conversion, immutable evidence, and fail-closed behavior.

## D8 / Person 2 D-02C — Mandatory mandate-configured FX safety margin

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T13:55-05:00

**Context:** a foreign-currency obligation can be below a USD mandate cap at policy
evaluation and exceed it later because of market movement or execution spread. Volta
must define whether and how authorization accounts for that risk.

**Alternatives considered:**

- **A — Evaluation-time FX snapshot only.** Lowest implementation cost, but a later rate
  move can make the eventual USD-equivalent cost exceed the mandate even though the
  original authorization was internally correct.
- **B — Mandatory user-configured FX safety margin.** Each mandate that permits non-USD
  obligations explicitly defines `fx_safety_margin_bps`. Policy evaluates the converted
  all-in amount plus that margin. Missing configuration fails closed.
- **C — Executable rate lock or immediate conversion.** Strongest control over settlement
  value, but requires treasury/payment or hedging integration outside this hackathon's
  approved scope.

**Decided:** Alternative B. For every non-USD authorization:
`policy_usd = converted_all_in_usd × (1 + fx_safety_margin_bps / 10_000)`.
The margin is human-issued authority stored in the mandate; the caller, model, FX
provider, and policy implementation cannot invent or change it.

**Why:** B makes currency risk explicit and deterministic without expanding Volta into a
payment or hedging system. It is safer than pretending an evaluation-time spot/reference
rate guarantees future settlement value and remains feasible within 24 hours.

**Trade-off accepted:** the margin reduces but cannot guarantee against all future market
movement. A conservative margin may reject valid offers; an aggressive margin is a human
risk decision. The concrete basis-point value still requires separate approval.

**Implementation contract:**

- A non-USD proposal with no explicit mandate `fx_safety_margin_bps` cannot return `ALLOW`.
- The margin is applied after comprehensive all-in conversion and before comparison to
  the USD cap, using `Decimal` and conservative upward rounding.
- `fx_safety_margin_bps` is versioned with the mandate; stale proposals fail closed.
- USD-denominated quotes do not receive an FX margin unless a separate mandate rule says so.
- The FX snapshot, unbuffered USD result, margin, buffered policy amount, and mandate
  version are stored as authorization evidence.
- Changing the margin is a human-authenticated mandate mutation, never a conversational update.

**Verification:** NOT RUN. Required evidence includes missing/zero/positive/extreme margin
boundaries, upward rounding, stale mandate versions, caller/model margin injection, and
cap-minus/cap-plus-one-cent tests after applying the margin.

**Would change if:** Volta gains an approved executable rate-lock or immediate-conversion
boundary that guarantees settlement value. Any replacement must remain explicit,
auditable, and independent of the LLM.

## D9 / Person 2 D-02A — Comprehensive all-in USD price-cap semantics

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T13:57-05:00

**Context:** a mandate such as "maximum USD 550" is unsafe if it applies only to an
advertised base rate while tolls, taxes, terminal handling, equipment, waiting, or other
customer-payable obligations remain outside the comparison. The cap needs one complete,
deterministic economic meaning.

**Alternatives considered:**

- **A — Comprehensive all-in cap.** Every customer-payable amount within the mandated
  port-to-warehouse scope is included before authorization. Unknown or unbounded charges
  make the total non-final and block authorization.
- **B — Base transport rate only.** Easiest comparison, but extras can make the actual
  obligation exceed the mandate and create an obvious Trial-by-Fire bypass.
- **C — Base rate plus selected accessorial categories.** More flexible than B, but any
  omitted or newly named category can escape the cap unless the schema and contract are
  exhaustive and continuously maintained.

**Decided:** Alternative A. The mandate cap applies to the aggregate amount the customer
may be obligated to pay for the defined port-to-warehouse movement, expressed as the
final policy amount in USD after required FX conversion and safety margin.

**Why:** A makes the cap match the business's actual economic exposure and prevents fee
names or invoice decomposition from bypassing authorization. It is the simplest rule to
explain, test, and defend under an adversarial live negotiation.

**Trade-off accepted:** Volta will clarify or escalate more often when a carrier cannot
provide a guaranteed total. This conservatism is accepted rather than authorizing an
obligation whose maximum cannot be proven.

**Implementation contract:**

- Include every customer-payable component in scope: transport/fuel/tolls; port,
  terminal, gate, handling and inspection; equipment/chassis/container; storage,
  waiting, detention and demurrage; pickup/destination/unloading/return/additional stops;
  special cargo, permits, security and insurance; applicable customs/regulatory items;
  taxes, fees, reimbursements, payment charges; and bounded contingencies.
- Preserve original itemized amounts, currencies, responsibility, inclusion/exclusion,
  source, conditions, and validity period. Do not double count embedded components.
- Convert mixed-currency components separately under D7/D-02B, apply D8/D-02C where
  required, then sum and round upward to USD cents for the policy comparison.
- Terms such as "plus expenses", "at cost", "taxes extra", unnamed charges, uncapped
  waiting, or any unknown customer obligation produce `CLARIFY / TOTAL_NOT_FINAL` or
  escalation, never `ALLOW`.
- Discounts reduce the total only when explicit, guaranteed, attributable to the same
  quote, and preserved as evidence.
- Liability-dependent incident costs require explicit responsibility; a carrier-caused
  loss does not silently increase authorized customer cost.

**Verification:** NOT RUN. Required evidence includes every cost category, embedded-cost
deduplication, mixed currencies, taxes, discounts, bounded/unbounded contingencies,
unknown-fee metamorphic cases, and one-cent boundaries after FX margin and rounding.

**Would change if:** the human defines a narrower operation scope in a new mandate
version. Within that scope, the cap remains comprehensive all-in; no implementation or
caller may silently reinterpret it as a base-rate cap.

## D10 / Person 2 D-02D — Dynamic RT FX-margin recommendation with human acceptance

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:11-05:00

**Context:** D8/D-02C requires an explicit FX safety margin for non-USD authorization.
A universal fixed percentage does not reflect the currency pair, intended settlement
horizon, recent volatility, market closure, or an individual customer's risk tolerance.
Volta therefore needs a bounded way to recommend—not determine—the margin.

**Alternatives considered:**

- **A — Fixed 1% / 100 bps demo margin.** Simple and permissive, but weakly connected to
  observed currency risk and potentially insufficient.
- **B — Fixed 2% / 200 bps demo margin.** Clear and moderate for a fictional example,
  but still arbitrary across currency pairs and time horizons.
- **C — Fixed 5% / 500 bps demo margin.** Conservative, but may reject viable offers and
  still lacks a risk model.
- **D — Dynamic RT calculator with explicit human acceptance.** A deterministic,
  versioned calculator recommends a margin from approved market data and customer inputs,
  explains its method and limitations, and requires the customer to accept or override
  the recommendation before it becomes mandate authority.

**Decided:** Alternative D. Add an "RT" calculator as the working product name for the
FX Risk Tolerance recommendation component. It produces an informational recommended
`fx_safety_margin_bps`; it cannot write the mandate or authorize an action. Only an
authenticated human's explicit acceptance or override creates the authoritative,
versioned mandate value used by policy.

**Why:** D treats the margin as a real customer risk choice instead of embedding an
arbitrary project constant. It provides a useful, explainable baseline while preserving
the separation between recommendation and authority established by D1/D-01.

**Trade-off accepted:** the calculator adds market-history ingestion, methodology,
versioning, explanation, testing, and more failure modes. Its formula, source hierarchy,
lookback, horizon, confidence/risk inputs, minimum data, and bounds remain a separate
decision and must not be invented during implementation.

**Implementation contract:**

- RT is deterministic code, not an LLM calculation or LLM-as-judge.
- RT returns a recommendation, inputs, source snapshots, methodology/calculator version,
  assumptions, limitations, and sensitivity; it has no mandate-write capability.
- The model may explain a structured RT result but cannot change its inputs, output,
  limitations, or acceptance state.
- The UI must show recommended bps and buffered USD effect before the human accepts or
  overrides it. Silence, model assent, or a preselected control is not acceptance.
- Human acceptance/override is authenticated, timestamped, attributed, versioned, and
  stored in the mandate. Policy consumes only that accepted value, never a recommendation.
- Insufficient, stale, unsupported, or unavailable data yields no recommendation and
  cannot silently fall back to a fixed margin.
- The explanation states that RT is an estimate based on historical/observed data, cannot
  predict or guarantee future rates or actual execution spread, and may under- or
  overestimate exposure. The customer must evaluate or explicitly accept the estimate.
- Product wording must not claim that a disclaimer automatically transfers or eliminates
  legal responsibility; legal effect depends on applicable terms and law.

**Verification:** NOT RUN. Required evidence includes deterministic replay from fixed
rate history, stale/insufficient data, extreme volatility, market gaps, unsupported pairs,
human accept/override flows, no default/preselected acceptance, mandate version changes,
and proof that recommendation output alone cannot authorize a proposal.

**Would change if:** RT cannot be made understandable and reproducible within the
hackathon schedule. In that case reduce scope to manual human entry; never silently adopt
a fixed default or let the model choose authority.

## D11 / Person 2 D-02E — Transparent historical simulation for RT

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:14-05:00

**Context:** the approved RT calculator needs a deterministic method for converting FX
history and a settlement horizon into an explainable margin recommendation. The method
must not present statistical estimation as a guarantee.

**Alternatives considered:**

- **A — Parametric volatility formula.** Fast and familiar, but requires distributional
  assumptions and can underrepresent jumps and heavy tails.
- **B — Historical simulation with a transparent adverse percentile.** Replays observed
  horizon-matched FX changes, requires no normal-distribution assumption, and exposes the
  observations and percentile behind the result.
- **C — Historical Expected Shortfall with stress calibration.** Better describes tail
  severity beyond a percentile but is more data-sensitive and difficult to explain and
  validate within the hackathon.
- **D — GARCH or Monte Carlo.** Potentially more adaptive, but adds model specification,
  calibration, randomness, and validation risk that can make an estimate appear more
  authoritative than the evidence warrants.

**Decided:** Alternative B. RT uses historical simulation of adverse changes in
`USD per source-currency unit` over the customer-relevant settlement horizon and selects
an approved adverse percentile. Known execution spread and conversion fees are disclosed
separately rather than hidden inside historical volatility.

**Why:** B is deterministic, reproducible, distribution-agnostic, explainable to a
non-specialist, and small enough to test rigorously. It provides a credible baseline
without turning Volta into a trading or bank-capital model.

**Trade-off accepted:** historical observations may omit future shocks, structural breaks,
currency controls, illiquidity, devaluation, or regime changes. The recommendation can
underestimate or overestimate future exposure and remains advisory.

**Implementation contract:**

- Normalize source data to one documented direction before returns are calculated.
- Use ordered, timestamped, deduplicated observations from approved sources; reject
  missing, non-positive, malformed, or temporally inconsistent rates.
- Compute overlapping adverse movements matching the accepted settlement horizon.
- Select the approved adverse percentile deterministically and round the resulting margin
  upward to basis points.
- Disclose observation window/count, horizon, percentile, worst observed movement, data
  source/freshness, missing-data handling, execution spread/fees, and sensitivity at
  nearby percentiles.
- Preserve the exact input snapshot or immutable reference and calculator version so the
  result can be replayed.
- No result is a guarantee or maximum possible loss; RT must state that history may not
  represent future market conditions and that losses can exceed the recommendation.
- No recommendation is produced when minimum data/freshness requirements are unmet.
- Confidence percentile, observation window, settlement-horizon policy, data source,
  spread treatment, bounds, and stress behavior remain separate approved parameters.

**Verification:** NOT RUN. Required evidence includes hand-calculated fixtures,
direction inversion, overlapping horizons, percentile boundary behavior, missing/duplicate
dates, weekends/holidays, jumps, non-positive rates, deterministic replay, and sensitivity
disclosure.

**Would change if:** testing shows that the historical estimator is unstable or
misleading for supported currencies. Any replacement requires a new human-approved
decision and must preserve advisory status and reproducibility.

## D12 / Person 2 D-02F — Controlled RT historical-simulation baseline

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:16-05:00

**Context:** historical simulation is not reproducible until its minimum observation
count, horizon, percentile, and sensitivity presentation are fixed. Unlimited statistical
configuration would also let a user tune the model merely to make an offer fit.

**Alternatives considered:**

- **A — Controlled baseline.** Require at least 250 valid daily observations, an
  authenticated customer-provided 1–10-business-day settlement horizon, the 99th adverse
  percentile, and displayed 95th/97.5th/worst-observed sensitivity.
- **B — Fully customer-configurable statistics.** Flexible, but permits weak or
  opportunistically chosen windows/percentiles and greatly expands validation and
  explanation requirements.
- **C — Named risk presets.** Simpler UI, but labels such as "balanced" or "conservative"
  can hide assumptions and imply certainty unless every underlying parameter is exposed.

**Decided:** Alternative A. RT uses a minimum of 250 valid daily observations. The
authenticated customer supplies the expected settlement horizon from 1 through 10
business days. RT recommends the 99th-percentile adverse horizon-matched movement and
shows the 95th percentile, 97.5th percentile, and worst observed movement as sensitivity,
not as alternate automatic decisions.

**Why:** A keeps the estimator deterministic, visible, and small enough to test while
letting the customer specify the economically meaningful timing input. The customer still
accepts or overrides the resulting margin under D10/D-02D.

**Trade-off accepted:** 250 observations and a 99th percentile provide limited tail
samples and do not cover an unseen shock. The 1–10-day range excludes longer exposures;
those produce no recommendation until a separately approved model exists.

**Implementation contract:**

- Require at least 250 valid, ordered daily rate observations after validation and
  deduplication; do not fill missing observations by model inference.
- Settlement horizon is an authenticated human input in integer business days `1..10`.
- Compute overlapping horizon-matched adverse movements with a documented business-day
  calendar and deterministic percentile convention.
- Recommend the 99th adverse percentile, rounded upward to basis points.
- Display 95th, 97.5th, and worst-observed adverse movements using the same data/horizon.
- Sensitivity values are explanatory only and never replace the recommendation or the
  human-accepted mandate value automatically.
- Fewer than 250 valid observations, horizon outside `1..10`, stale data, or an
  unsupported calendar/pair yields no RT recommendation and no non-USD authorization.
- The UI explains sample size, tail sparsity, historical limitation, and that losses can
  exceed both the percentile estimate and worst movement in the selected sample.

**Verification:** NOT RUN. Required evidence includes exactly 249/250 observations,
horizons 0/1/10/11, overlapping-window fixtures, percentile interpolation convention,
round-up boundaries, weekend/holiday handling, sensitivity ordering, and deterministic
replay.

**Would change if:** empirical testing shows the minimum sample or fixed percentile is
misleading for supported pairs, or real customer settlement regularly exceeds 10 business
days. Any change requires a new approved decision and versioned calculator behavior.

## D13 / Person 2 D-02G — Open Exchange Rates primary with official cross-checks

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:19-05:00

**Context:** the controlled-hybrid architecture approved in D7/D-02B requires a named
primary source for current and historical FX data. The hackathon baseline must support
USD-native conversion and the 250-observation RT input without pretending that an
indicative market rate is the customer's guaranteed execution rate.

**Alternatives considered:**

- **A — Open Exchange Rates Free plus official cross-checks.** USD-native hourly data,
  broad currency coverage, historical daily observations, and a 1,000-request monthly
  baseline at no subscription cost; weaker service assurance and indicative midpoint
  limitations must be disclosed.
- **B — Open Exchange Rates Developer.** Higher 10,000-request allowance and alternate
  base currencies for USD 12/month, but those features are unnecessary for the approved
  USD-only policy base at hackathon scale.
- **C — Official sources only.** Strong provenance and no vendor subscription, but
  fragmented coverage and formats across central banks create substantial integration
  work and cannot provide one consistent broad-currency source.
- **D — Provider-neutral mock data for the demo.** Fast and free, but does not demonstrate
  real conversion and risks misleading users unless every result is visibly simulated.

**Decided:** Alternative A. Use Open Exchange Rates Free as the primary hackathon source
for supported current and historical rates, normalized to USD. Cross-check a rate against
an approved official source such as the ECB or Banxico when that source publishes the
relevant pair. Persist the source response or immutable content-addressed snapshot and
the cross-check result used for each policy or RT calculation.

**Why:** A fits the approved USD architecture, supplies the required history and broad
coverage with the lowest integration and monetary cost, and leaves time for deterministic
validation. Official cross-checks add independent evidence without making Volta maintain
a fragile global patchwork of central-bank adapters during the hackathon.

**Trade-off accepted:** the free plan has no paid SLA, is subject to its current quota and
terms, and publishes indicative blended rates rather than a guaranteed customer execution
price. Official sources cover only subsets of pairs and may publish on different schedules.
The zero-dollar subscription assumption must be revalidated before deployment or usage
beyond the documented free-plan allowance.

**Implementation contract:**

- An allowlisted server-side adapter is the only component permitted to obtain provider
  data. The LLM, caller, carrier, browser, or tool proposal cannot supply an authoritative
  policy rate.
- Keep provider credentials outside source control and client bundles; never log or return
  them. Authentication failure, quota exhaustion, or provider error fails closed.
- Accept only explicitly supported ISO 4217 fiat codes and positive finite rates. Do not
  enable unofficial, black-market, experimental, commodity, or crypto symbols by default.
- Normalize and document rate direction as `USD per source-currency unit`; validate base,
  quote, provider timestamp, retrieval timestamp, schema, and calculator/adapter version.
- Persist an immutable response or content-addressed snapshot, cryptographic digest,
  provenance, applicable timestamps, normalized rate, and validation outcome so every
  authorization and RT result can be replayed.
- Official cross-check sources are separately allowlisted by pair. Preserve both values,
  timestamps, source identities, and divergence calculation; never silently substitute
  one source for another.
- Until freshness windows, cross-check divergence thresholds, cache behavior, and outage
  rules receive separate human approval, no implementation may invent them or claim a
  rate is authorization-ready.
- Label the rate as indicative. Actual execution spread, payment-provider charges, bank
  fees, taxes, and other comprehensive-all-in components remain separate under D9/D-02A;
  neither the FX margin nor this source decision may silently erase them.
- Enforce quota-aware server-side caching without weakening freshness or auditability.
  A paid-plan transition, fallback provider, or broader production guarantee requires a
  new recorded decision and cost approval.

**Verification:** NOT RUN. Required evidence includes fixed provider fixtures, schema and
direction validation, unsupported codes, unofficial-symbol rejection, non-positive and
non-finite rates, stale/future timestamps, credential redaction, quota/auth/provider
failures, snapshot replay and tamper detection, cross-check agreement/divergence, source
schedule mismatch, caching, and proof that caller/model-supplied rates cannot authorize.

**Would change if:** free-plan terms, allowance, coverage, data licensing, availability,
or validation tests do not support the approved use. Switching plan or provider requires
a new human-approved decision; it is never an automatic fallback.

## D14 / Person 2 D-02H — Strict FX freshness, divergence, and outage baseline

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:21-05:00

**Context:** naming FX sources is insufficient for authorization unless policy defines
how recent the primary observation must be, how independent disagreement is handled, and
whether cached data remains usable during an outage. These rules must be deterministic
and must fit the selected free-plan request allowance.

**Alternatives considered:**

- **A — Strict controlled baseline.** Require a primary provider timestamp no older than
  two hours, fetch/cache approximately hourly, reuse cached data only inside that same
  window, and block covered pairs when an official cross-check differs by more than 1%.
- **B — Daily baseline.** Permit primary observations for 24 hours and up to 2%
  divergence, improving availability but weakening the requested near-real-time behavior.
- **C — Pair-specific thresholds.** Calibrate freshness and divergence per currency,
  improving market sensitivity but adding substantial evidence, configuration, and test
  requirements not yet available.
- **D — Advisory divergence only.** Show disagreement but permit authorization, improving
  demo continuity while allowing questionable data to affect a consequential USD limit.

**Decided:** Alternative A. A primary Open Exchange Rates observation is usable only when
its provider timestamp is at most two hours old at policy evaluation. Server-side caching
and approximately hourly shared retrieval preserve free-plan quota. During provider
failure, the last validated immutable snapshot may be reused only while its provider
timestamp remains within the same two-hour window. For a pair covered by an allowlisted
official cross-check, normalized divergence greater than 1% blocks authorization. Where
no approved official source publishes the pair, a valid primary observation may be used
but the evidence and user-facing result must explicitly state `not independently
cross-checked`.

**Why:** A turns provider freshness and disagreement into deterministic authorization
inputs. It favors a clear safe failure during Trial-by-Fire over silently converting a
customer commitment with stale or materially inconsistent data, while remaining feasible
within the documented free-plan quota when requests are shared and cached server-side.

**Trade-off accepted:** a two-hour limit and 1% threshold can block a legitimate offer
during provider delays, official publication differences, weekends/holidays, or unusual
markets. Pairs without official coverage receive less independent assurance and must not
be represented as cross-checked. This baseline is not pair-calibrated.

**Implementation contract:**

- Compute primary age from trusted server time and the authenticated provider timestamp,
  not browser, caller, carrier, or model time. Future timestamps and negative ages fail.
- `age <= 2 hours` is valid; `age > 2 hours` is stale. Retrieval time does not reset the
  provider observation age.
- Use a process-independent server-side cache/shared store so callers cannot multiply
  upstream requests. Target approximately one successful primary refresh per hour and
  retain quota headroom for controlled recovery and tests.
- Provider error, authentication failure, quota exhaustion, malformed response, or cache
  failure never extends validity. A previously validated immutable snapshot is usable
  only until its original provider timestamp crosses the two-hour boundary.
- For a covered pair, select the most recent publication expected under the allowlisted
  official source's documented business-day, weekend, and holiday schedule. Missing or
  stale publication beyond that expected schedule blocks; never forward-fill silently.
- Normalize both observations to `USD per source-currency unit` and calculate divergence
  deterministically as `abs(primary - official) / official * 100`. Divergence `<= 1%` is
  valid; divergence `> 1%`, a zero/non-finite denominator, or incomparable as-of evidence
  blocks authorization.
- Preserve raw/immutable source evidence, normalized values, timestamps, age, official
  coverage status, expected-publication determination, divergence, threshold, adapter
  versions, and final reason code.
- No official coverage is not equivalent to cross-check success. Record and display
  `not independently cross-checked`; this exception applies only when the allowlisted
  coverage registry confirms that the pair is not published.
- FX denial must return a structured safe reason and must not reveal credentials, raw
  internal errors, or sensitive configuration. The LLM may explain the result but cannot
  override freshness, divergence, coverage, or outage outcomes.

**Verification:** NOT RUN. Required evidence includes ages immediately below/at/above two
hours, future timestamps, trusted-clock behavior, hourly cache concurrency, quota errors,
outage reuse before/at/after expiry, official weekends/holidays and missed publication,
rate-direction normalization, divergence immediately below/at/above 1%, invalid official
denominators, incomparable as-of dates, uncovered pairs, immutable replay, and proof that
the model/caller cannot alter any threshold or outcome.

**Would change if:** provider behavior, official-source publication timing, quota tests,
or observed false blocks show that the baseline is unsuitable. Any wider window, higher
threshold, pair-specific rule, or automatic fallback requires a new human approval and
must not be introduced merely to make a failing demonstration pass.

## D15 / Person 2 D-02I — Most recent 250 valid observations for RT

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:24-05:00

**Context:** D12/D-02F set 250 valid daily observations as the minimum but did not define
the actual rolling lookback. The selected free provider plan permits 1,000 requests per
month; a first-month backfill must coexist with approximately hourly current-rate refresh.

**Alternatives considered:**

- **A — Most recent 250 valid daily observations, with mandatory disclosure.** Fits the
  initial free-plan request budget and emphasizes the current market regime, but supplies
  only a small number of observations in the 99th-percentile tail.
- **B — Most recent 500 observations.** Improves tail evidence and regime coverage, but
  initial backfill plus hourly refresh exceeds the documented free monthly allowance.
- **C — Five-year rolling history.** Covers more regimes but requires paid/bulk access or
  staged ingestion and may mix obsolete currency conditions.
- **D — Customer-selected lookback.** Flexible, but permits opportunistic tuning and
  materially expands validation, explanation, and mandate-governance requirements.

**Decided:** Alternative A with the disclosure. RT calculations use exactly the most
recent 250 valid daily observations available under the approved validation and freshness
rules. The structured result and UI must prominently disclose the limited sample, sparse
99th-percentile tail evidence, inability to represent unseen crises, and possibility that
future loss exceeds the recommendation and worst observation in the window.

**Why:** A is deterministic, recent, explainable, feasible within the free-plan budget,
and prevents the lookback from being tuned to obtain a desired margin. Making the warning
part of the structured result prevents an LLM or presentation layer from omitting the
central limitation.

**Trade-off accepted:** approximately one year of valid business-day observations can
miss older crises, devaluations, capital controls, structural breaks, and infrequent tail
events. The 99th percentile is based on very few extreme samples, especially after
horizon matching, and must not be characterized as statistically certain.

**Implementation contract:**

- After source validation, ordering, and deduplication, select exactly the newest 250
  valid daily observations by canonical observation date; never let a caller or model
  choose or truncate the lookback.
- Fewer than 250 valid observations yields no recommendation. More than 250 are retained
  as auditable source history if available but are excluded from this calculator version.
- Record the first and last included dates, valid count, rejected/missing dates and reason
  codes, selection rule, provider snapshots/digests, and calculator version.
- Quota planning is operational evidence, not permission to weaken validation. Backfill
  requests and shared hourly refreshes must be metered; quota exhaustion fails closed.
- The deterministic structured result includes a non-empty limitation code and canonical
  disclosure stating that 250 recent observations provide sparse tail evidence, exclude
  older regimes, cannot predict crises, and do not cap possible loss.
- The UI presents that disclosure adjacent to the recommendation before acceptance or
  override. It may not be hidden behind optional expansion, reduced to a generic legal
  disclaimer, or replaced by model-generated wording.
- Logs/audit evidence record which disclosure version was shown and accepted alongside
  the recommendation. Acceptance acknowledges visibility; it does not turn the estimate
  into a guarantee or eliminate Volta's obligations.
- Historical observations are not refetched merely to change a recorded result. Each
  completed recommendation remains replayable against its immutable evidence.

**Verification:** NOT RUN. Required evidence includes 249/250/251 valid observations,
newest-window selection, unsorted and duplicate dates, invalid observations inside and
outside the candidate range, deterministic rollover when a new day arrives, quota
exhaustion, stable historical replay, required disclosure presence/placement/version,
and proof that the model/caller cannot suppress the disclosure or select the lookback.

**Would change if:** the project adopts approved paid/bulk data access or empirical
validation demonstrates that 250 observations create unacceptable instability. A longer,
weighted, or regime-aware window requires a new human-approved calculator version.

## D16 / Person 2 D-02J — Conservative nearest-rank RT percentile

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:26-05:00

**Context:** statistical libraries implement percentile labels with incompatible rank and
interpolation conventions. RT needs one language-independent oracle for the approved 99th
percentile and sensitivity values, including explicit handling of favorable-only samples
and fractional basis points.

**Alternatives considered:**

- **A — Conservative nearest-rank.** Sort the horizon-matched USD cost changes, select
  rank `ceil(p * n)` without interpolation, floor the recommendation at zero, and round
  a positive fractional basis-point result upward.
- **B — Linear interpolation.** Produces smoother results but depends on a precisely named
  convention and may recommend a value that was never observed.
- **C — Average surrounding observations.** Easy to describe, but can reduce the result
  below the nearest observed adverse movement.
- **D — Customer-selected method.** Flexible, but enables method-shopping and makes the
  authorization input inconsistent across otherwise identical mandates.

**Decided:** Alternative A. RT uses the one-indexed nearest-rank quantile: for sorted
signed horizon changes `x[1..n]`, `Q(p) = x[ceil(p*n)]`. No interpolation is allowed.
The recommended margin is `ceil(max(0, Q(0.99)) * 10,000)` basis points. The displayed
95th and 97.5th sensitivities use the same quantile rule and unit conversion; the worst
observed sensitivity is the maximum signed horizon change, floored at zero for a margin.

**Why:** A creates a small deterministic oracle that can be reproduced by hand and
implemented identically across languages without relying on a library's unnamed default.
Upward conversion avoids understating a positive fractional basis-point exposure.

**Trade-off accepted:** nearest-rank outputs change in steps and can be more conservative
than an interpolated estimate. A zero floor discards favorable movement as a negative
margin but does not claim that zero observed adverse movement means zero future risk.

**Implementation contract:**

- Calculate signed changes in unrounded high-precision decimal arithmetic using the
  separately approved normalized `USD per source-currency unit` series.
- Sort ascending using numeric value. For percentile `p`, use one-indexed rank
  `ceil(p*n)` and select that exact observation; reject empty samples.
- Apply the zero floor only after selecting the signed quantile. Never discard favorable
  observations before ranking, because doing so changes the empirical distribution.
- Convert a non-negative fractional result to basis points by multiplying by 10,000 and
  applying mathematical ceiling. Do not use binary floating-point or banker's rounding.
- Apply the same rule to 95%, 97.5%, and 99%; display the maximum observed signed adverse
  movement separately. Preserve raw selected values, ranks, sample count, sorted-data
  digest, decimal precision/version, and final basis-point values.
- Canonical boundary semantics are part of the calculator version. Libraries may assist
  with sorting/decimal arithmetic but their percentile helpers are not authoritative.
- A zero recommendation retains every D10/D12/D15 disclosure, requires explicit human
  acceptance or override, and is not evidence that future loss is impossible.
- The LLM, UI, and caller cannot select interpolation, rounding, rank, floor, or precision.

**Verification:** NOT RUN. Required evidence includes hand-calculated odd/even fixtures,
single-element and empty samples, ranks at 95/97.5/99%, duplicate/tied values, all-negative,
zero, mixed, and all-positive changes, fractional basis points immediately below/at/above
an integer, decimal precision, cross-language parity, and proof that favorable values are
ranked before the zero floor is applied.

**Would change if:** independent numerical review shows that the method systematically
misstates the approved risk interpretation. Any interpolation, Expected Shortfall, or
rounding change requires a new versioned human decision and replay-impact analysis.

## D17 / Person 2 D-02K — Joint-currency banking calendar for RT horizons

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:28-05:00

**Context:** the approved customer settlement horizon is expressed in business days, but
weekdays are not necessarily banking days. USD and the quotation currency may observe
different holidays or closures, changing the actual interval over which USD cost is at
risk and therefore changing the historical movements used by RT.

**Alternatives considered:**

- **A — Joint currency banking calendar.** Count a day only when the relevant banking
  systems for both USD and the quotation currency are open; unsupported calendars fail
  closed. Most realistic, with additional calendar sourcing and test obligations.
- **B — Monday through Friday in UTC.** Simple and inexpensive but ignores national
  holidays and can understate or overstate the actual settlement interval.
- **C — Calendar days.** Easiest to implement but contradicts the approved business-day
  input and misrepresents operational settlement timing.
- **D — Customer-supplied calendar.** Flexible but permits unvalidated or manipulated
  closure rules to alter an authorization-relevant recommendation.

**Decided:** Alternative A. For a quote in source currency `C`, an RT business day is a
date on which both the approved USD banking calendar and the approved `C` banking calendar
are open. Horizon matching advances across joint-open dates only. If either calendar,
version, coverage period, or required closure status is unavailable, RT produces no
recommendation and the non-USD proposal cannot be authorized.

**Why:** A aligns the model horizon with when settlement can realistically progress and
prevents a holiday mismatch from shortening the measured exposure. It also creates a
clear Trial-by-Fire explanation and deterministic failure for unsupported currencies.

**Trade-off accepted:** authoritative holiday and exceptional-closure data add sourcing,
licensing, versioning, update, and testing work. The supported currency set will be smaller
until calendars are explicitly configured, and unexpected closures can still require an
approved update.

**Implementation contract:**

- Maintain a server-side allowlisted registry mapping each supported ISO 4217 fiat code
  to an approved banking-calendar identifier, source, timezone, coverage interval, and
  immutable version/digest. Currency-to-country inference by the LLM or caller is forbidden.
- A joint business date is open only when both USD and source-currency calendars explicitly
  mark it open. Weekends, holidays, and exceptional closures from either side are excluded.
- Unknown, ambiguous, missing, expired, conflicting, or out-of-coverage calendar state is
  not treated as open and yields no RT recommendation; do not silently fall back to weekdays.
- Starting from each historical observation date, advance to the observation associated
  with the `h`th subsequent joint-open date for horizon `h`. The exact observation-date
  alignment and missing-rate rule remain subject to a separate approval.
- Preserve calendar identifiers, source/version/digest, timezones, evaluated dates,
  exclusion reasons, joint-open sequence, and horizon endpoints with each RT result.
- The authenticated customer selects only the integer horizon `1..10`; the customer,
  carrier, caller, browser, and LLM cannot supply, modify, or override calendar contents.
- UI and structured results identify the two calendars and actual start/end dates used.
  Unsupported calendar coverage is explained as a safe refusal, not converted silently.
- Calendar updates are versioned and affect only new calculations. Historical results
  remain replayable against the exact calendar evidence originally used.

**Verification:** NOT RUN. Required evidence includes USD-only identity, mismatched US and
foreign holidays, weekends, consecutive closures, leap days, exceptional closures,
timezone/date-boundary cases, unknown currencies, missing/conflicting/out-of-coverage
calendars, horizons 1 and 10, immutable replay across a calendar update, and proof that
caller/model-supplied closure dates cannot affect the result.

**Would change if:** reliable calendar evidence cannot be obtained for the intended demo
pairs or settlement operations use a different formally documented convention. Any
weekday fallback, single-market calendar, or expanded coverage requires human approval.

## D18 / Person 2 D-02L — Official, versioned USD/COP calendar scope

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:33-05:00

**Context:** the joint-calendar rule in D17/D-02K requires an initial supported-currency
scope and evidence source. Broad calendar coverage would add vendors or unverified holiday
assumptions before the hackathon's USD/COP path is proven.

**Alternatives considered:**

- **A — Official, versioned USD/COP calendars only.** Use Federal Reserve banking-holiday
  evidence for USD and an approved Colombian official/statutory banking-calendar source
  for COP; all other non-USD currencies fail closed. No subscription cost.
- **B — Commercial global calendar API.** Broad coverage but adds cost, credentials,
  licensing, provider availability, and validation work.
- **C — Open-source holiday library.** Quick and broad, but country holidays are not
  necessarily banking or settlement holidays and package data is not authoritative.
- **D — Manually entered calendars for arbitrary currencies.** Flexible but difficult to
  verify consistently and prone to omissions or unreviewed changes.

**Decided:** Alternative A. The initial RT calendar registry is limited to USD and COP.
USD evidence comes from the Federal Reserve's official K.8 holiday schedule and applicable
Federal Reserve banking-service rules. COP requires a separately identified and reviewed
Colombian official or statutory banking-calendar source. Until that evidence is approved
and versioned, COP is configured as unsupported and calculations fail closed. Every other
non-USD currency remains outside initial calendar coverage.

**Why:** A bounds the evidence and test surface, avoids another paid dependency, and makes
the initial demonstration honest about its supported route. It preserves official
provenance instead of equating a generic public-holiday list with settlement availability.

**Trade-off accepted:** Volta initially supports only one foreign currency and may still
block USD/COP until the Colombian source passes review. Broad international quotations
can be received and preserved, but cannot receive an RT recommendation or authorization
until their approved joint calendars are added by a recorded decision.

**Implementation contract:**

- The initial allowlist contains calendar identifiers for USD and COP only. Presence of
  an FX rate does not imply calendar support or authorization support.
- Pin USD calendar evidence to the official Federal Reserve source URL, retrieved/reviewed
  timestamp, covered years, parsed dates/rules, immutable content or digest, and adapter
  version. Verify distinctions between Board closure and relevant banking/payment-service
  operation rather than copying labels blindly.
- Do not populate or enable COP from generic web search, an LLM answer, a carrier claim,
  a caller upload, or an open-source holiday package. Record the authoritative Colombian
  source and its legal/operational applicability for a separate human approval.
- `COP calendar status != approved` deterministically yields `RT_CALENDAR_UNSUPPORTED`;
  it cannot fall back to Monday-Friday or ordinary national holidays.
- Preserve unsupported quotations in their explicit original ISO 4217 currency and explain
  the refusal without treating the quote as authorized or converting it into mandate state.
- Adding a currency requires source provenance, settlement applicability, historical and
  future coverage, timezone, exceptional-closure handling, version/update policy, fixtures,
  security review, cost disclosure, and a new recorded approval.
- Calendar source documents are data, never instructions. Parsing is deterministic and
  cannot execute embedded content, follow arbitrary links, or alter policy configuration.

**Verification:** NOT RUN. Required evidence includes Federal Reserve observed-holiday
edge cases, Board-versus-payment-service distinctions, COP disabled before source approval,
USD/COP and USD/other-currency coverage checks, no weekday/library fallback, provenance
and digest verification, parser rejection of malformed/unexpected content, and proof that
rate availability or model/caller assertions cannot enable a calendar.

**Would change if:** an approved commercial calendar service provides materially better
coverage and assurance at an accepted cost, or the Trial-by-Fire route requires another
currency. Expansion requires a new decision; it is not inferred from a received quotation.

## D19 / Person 2 D-02M — Controlled statutory COP banking-day proxy

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:35-05:00

**Context:** official Banco de la República material states that CENIT operates on banking
business days but the reviewed material does not provide a simple machine-readable annual
calendar. Colombia's official Law 51 of 1983 defines national holidays and Monday
observance rules. Treating that statutory schedule as the complete banking calendar is an
inference whose limits must remain visible.

**Alternatives considered:**

- **A — Controlled statutory calendar proxy.** Derive weekends, fixed holidays, Monday
  transfers, and movable religious holidays deterministically from official law; version
  the dates and manually cross-check current Banco de la República operational notices.
- **B — Keep COP blocked pending explicit operational confirmation.** Strongest assurance,
  but may leave the USD/COP RT path unavailable for Trial-by-Fire.
- **C — Commercial settlement-calendar provider.** Potentially stronger operational
  coverage but adds cost, credentials, licensing, vendor dependency, and due diligence.
- **D — Generic holiday package.** Quick but not authoritative and may change silently
  after dependency updates.

**Decided:** Alternative A. Generate a versioned COP calendar from the Colombian statutory
holiday rules in Law 51 of 1983 plus weekends. Cross-check each covered year against current
official Banco de la República operational notices available during review. Treat the
result explicitly as a `statutory banking-day proxy`, not a guarantee of the operating
schedule of CENIT, Bre-B, a particular bank, or the final settlement rail. Known or
ambiguous exceptional closures require separate review and fail closed until resolved.

**Why:** A provides official legal provenance and a deterministic, auditable baseline
within the hackathon schedule while honestly retaining the distinction between statutory
holidays and actual payment-system operations.

**Trade-off accepted:** the proxy may omit exceptional closures, institution-specific
hours, payment-rail differences, emergency measures, or future legal amendments. Manual
cross-checking is operational work and cannot guarantee completeness. Volta must not
market the proxy as certified settlement availability.

**Implementation contract:**

- Pin the official SUIN-Juriscol Law 51 source and reviewed legal status, retrieval/review
  timestamp, source digest or immutable capture, parser/generator version, and covered years.
- Generate Saturdays and Sundays as closed. Encode each statutory fixed holiday, Monday
  transfer rule, and movable religious holiday using named deterministic algorithms and
  high-coverage test fixtures; do not depend on an unpinned holiday library at runtime.
- Produce a human-reviewable annual table before enabling a year. A reviewer records the
  official Banco de la República notices checked, discrepancies, resolution, approver,
  and calendar digest. Unreviewed years are unsupported.
- Calendar evidence carries the explicit assurance label `statutory banking-day proxy`.
  UI and structured RT output state that actual bank/payment-rail availability can differ.
- A detected official exceptional closure, legal amendment, contradictory notice, or
  unresolved ambiguity marks affected dates/coverage unsupported and blocks calculation;
  it is never patched from model output or silently treated as open.
- The customer, carrier, caller, browser, and LLM cannot add/remove holidays or approve a
  generated year. Manual review is an authenticated administrative action with audit history.
- Historical results retain the exact annual table and digest used. A corrected calendar
  versions new calculations and triggers replay-impact analysis without rewriting evidence.
- This decision approves the evidence method, not a generated date table. No COP calendar
  becomes enabled until its concrete covered-year table and review evidence exist and pass
  the required tests.

**Verification:** NOT RUN. Required evidence includes all fixed and Monday-transferred
holidays, Easter-derived holidays across representative/leap years, Saturday/Sunday rules,
year boundaries, timezone handling, law-source digest/version, unreviewed years, official
notice discrepancies and exceptional closures, immutable replay after correction, visible
proxy disclosure, and proof that external/model input cannot alter or approve dates.

**Would change if:** Banco de la República supplies an authoritative operational calendar
or an approved vendor provides stronger assurance at accepted cost. Replacing the proxy
requires provenance review, compatibility tests, replay-impact analysis, and human approval.

## D20 / Person 2 D-02N — Complete exact-date FX history for RT

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:38-05:00

**Context:** a joint calendar may identify an open banking date for which the FX provider
does not supply a valid observation. Skipping or inventing that date changes the actual
settlement horizon and can alter the recommended authorization margin.

**Alternatives considered:**

- **A — Complete exact-date sequence.** Require a valid provider observation on every one
  of the newest 250 consecutive joint-open dates and pair each start with the exact `h`th
  subsequent joint-open date; any gap produces no recommendation.
- **B — Skip missing dates.** Improves availability but silently stretches the economic
  horizon while continuing to label it as the customer-selected number of business days.
- **C — Carry the previous rate forward.** Common in some reports but falsely converts
  unavailable evidence into an observed unchanged market rate.
- **D — Interpolate missing rates.** Creates a smooth series by inventing
  authorization-relevant observations that the source never published.

**Decided:** Alternative A. RT requires the newest complete sequence of 250 consecutive
joint-open dates, with one valid source observation assigned to every date. A horizon
movement beginning at index `i` ends at the exact observation for index `i+h`. Missing,
ambiguous, duplicate, or invalid evidence for any required date yields no recommendation;
RT never skips, carries forward, interpolates, or asks an LLM to repair a value.

**Why:** A preserves the approved business-day semantics and gives each calculated
movement an exact auditable pair of market observations. A safe refusal is preferable to
quietly changing the horizon or manufacturing data.

**Trade-off accepted:** one data gap blocks the calculator even if surrounding rates are
available. Obtaining a complete sequence may require an older window, provider support,
or investigation, and can reduce Trial-by-Fire availability.

**Implementation contract:**

- Construct the ordered joint-open date sequence from the exact approved calendar
  versions first; then require exactly one valid normalized provider observation for every
  selected date. Provider timestamps must map under a separately documented canonical
  observation-date rule.
- Select the newest run of 250 consecutive joint-open dates for which the run itself is
  complete. Do not bridge a missing date by treating later dates as consecutive. If no
  complete qualifying run exists within approved source/calendar coverage, return no result.
- For horizon `h`, calculate movements only for index pairs `(i, i+h)`, yielding exactly
  `250-h` horizon-matched movements. Off-by-one alternatives are invalid.
- Duplicate observations, conflicting observations for one canonical date, invalid rate
  direction, non-positive/non-finite values, missing snapshots, or digest failure make
  that date invalid. Do not choose the most favorable duplicate.
- Preserve all 250 canonical dates and source evidence, gap scan, selected endpoints,
  horizon, expected movement count, rejected candidate runs, reason codes, and versions.
- Return a structured `RT_HISTORY_INCOMPLETE` refusal without leaking provider credentials
  or internal errors. The UI explains the missing date/evidence class and that no estimate
  was produced; the model cannot soften the refusal into an authorization.
- Source correction or backfill creates new immutable evidence and a new calculation. It
  never rewrites a previously refused or completed audit record.

**Verification:** NOT RUN. Required evidence includes one missing date at the start,
middle, and end; a valid older complete run; duplicates and conflicts; malformed/non-positive
rates; horizons 1 and 10 producing 249 and 240 movements; exact endpoint/off-by-one fixtures;
weekend and mismatched-holiday boundaries; no fill/interpolation; immutable backfill; and
proof that caller/model data cannot complete a run.

**Would change if:** an approved authoritative source explicitly defines a different
observation or holiday treatment suitable for settlement risk. Any imputation, gap
tolerance, or alternate-source splice requires a new human decision and validation.

## D21 / Person 2 D-02O — No financial floor or cap on RT recommendation

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:40-05:00

**Context:** the approved historical calculation may produce a zero or unusually large
margin. Automatically replacing those results with product-selected bounds would introduce
an unevidenced financial judgment and could conceal the model's actual output.

**Alternatives considered:**

- **A — No policy floor or cap.** Report the exact approved calculation, subject only to
  the already approved zero floor; disclose sensitivities and require explicit human
  acceptance or override.
- **B — Fixed minimum margin.** Guards against a calm sample but any selected percentage
  would be arbitrary without additional evidence.
- **C — Maximum recommendation cap.** Improves apparent usability but can materially
  understate observed currency risk.
- **D — Fixed minimum and maximum.** Predictable presentation but contradicts the dynamic
  method and hides its true result.

**Decided:** Alternative A. RT applies no financial-policy minimum above zero and no
financial-policy maximum. It returns the exact basis-point result from D16/D-02J alongside
the approved sensitivities and disclosures. A zero or large recommendation remains visible
and requires the same explicit authenticated human acceptance or override as any other
result. Technical validation rejects unsafe numeric representations rather than clipping
them and must not be described as a financial bound.

**Why:** A preserves model transparency and avoids smuggling an arbitrary risk appetite
into advisory code. The human mandate owner, not RT or an LLM, remains responsible for the
accepted margin under D10/D-02D.

**Trade-off accepted:** the calculator may produce commercially uncomfortable values or
zero after an unusually calm sample. Users may choose a lower override despite displayed
risk. Volta must preserve and explain that choice rather than imply the recommendation
guarantees sufficiency.

**Implementation contract:**

- Return the exact non-negative integer basis-point recommendation calculated under D16;
  do not clamp, smooth, substitute, or suppress a zero or large valid result.
- Display the raw selected quantile, recommended bps, resulting buffered USD amount,
  95th/97.5th/worst sensitivities, and all D10/D12/D15/D19 limitations before acceptance.
- A zero recommendation receives an explicit message that the selected historical window
  showed no positive movement at that quantile and that future adverse movement remains
  possible. A large result is not truncated for layout or persuasion.
- Define technical decimal/integer precision and maximum serialized size during interface
  design. Out-of-representation values return a structured calculation failure; they are
  never clipped to the largest representable or UI-friendly financial value.
- Human acceptance and override remain distinct auditable actions. Model narration,
  silence, default controls, or calculator output cannot create mandate authority.
- Do not claim that absence of a cap means all large recommendations are economically
  reasonable. The calculator reports its evidence; the customer decides risk tolerance.

**Verification:** NOT RUN. Required evidence includes exact zero, sub-basis-point ceiling,
ordinary, very large, and out-of-representation fixtures; unchanged sensitivity display;
no hidden UI truncation; structured technical failure instead of clipping; acceptance and
override audit separation; and proof that caller/model output cannot impose a bound.

**Would change if:** external legal, contractual, or empirically validated risk requirements
justify a bound. Such a bound requires a separate human-approved policy and must be shown
as distinct from the historical estimate rather than rewriting it.

## D22 / Person 2 D-02P — Heightened owner confirmation for lower RT overrides

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:41-05:00

**Context:** D10/D-02D permits the authenticated customer to accept or override RT, but an
override below the recommendation increases exposure and needs evidence of informed human
intent without turning the advisory calculator into the authorization authority.

**Alternatives considered:**

- **A — Explicit owner override with heightened confirmation.** Only the authenticated
  mandate owner may override; lower values require rationale, side-by-side USD impact and
  sensitivities, an unselected understanding confirmation, and a new mandate version.
- **B — Prohibit overrides below RT.** Strong paternal protection but makes RT binding
  authority and contradicts the approved customer-responsibility model.
- **C — Require two human approvers below RT.** Strong enterprise governance but adds
  identity/workflow scope inappropriate for the current individual-customer baseline.
- **D — Unrestricted override.** Simple but provides weak evidence that the owner saw and
  understood the increased exposure.

**Decided:** Alternative A. Only the authenticated current mandate owner may set an RT
override. If the override is below the recommendation, the owner must enter a non-empty
rationale, review the recommended and overridden basis points and buffered USD effects
side by side with all sensitivities/limitations, and perform a separate explicit
understanding confirmation that is not preselected. Acceptance creates a new mandate
version and causes every unresolved proposal to be evaluated again. A higher override
uses the normal explicit mandate-change confirmation and remains fully audited.

**Why:** A preserves human authority while making a reduction in protection deliberate,
visible, attributable, and replayable. It prevents voice text, model output, or a default
UI state from silently lowering the authorization buffer.

**Trade-off accepted:** a customer may still knowingly select an insufficient margin.
The additional friction can slow negotiation and does not prove financial sophistication
or eliminate product/legal obligations. Single-owner approval may be insufficient for a
future enterprise account.

**Implementation contract:**

- Authorize override operations against authenticated identity and current mandate
  ownership server-side. Voice identity, caller claims, LLM assertions, carrier messages,
  or possession of a proposal identifier are not sufficient.
- Compare exact integer basis points. `override < recommendation` invokes the heightened
  flow; equality is acceptance; a higher value is a normal explicit override. Negative,
  malformed, non-integer, or technically unsafe values are rejected.
- Before lower confirmation, show recommended/override bps, unbuffered and both buffered
  USD amounts, absolute/percentage protection reduction, 95th/97.5th/99th/worst values,
  data/calculator versions, and every mandatory limitation adjacent to the action.
- Require a non-whitespace rationale with a bounded safe length and a distinct unselected
  confirmation control. No generic model-generated rationale, silence, or single ambiguous
  voice utterance satisfies either requirement.
- Persist the rationale as untrusted user text with output encoding, the exact disclosure
  version shown, confirmation event, authenticated actor, timestamps, old/new mandate
  versions, RT evidence reference, and before/after values. Never execute or prompt-inject
  from the rationale.
- Use optimistic concurrency/idempotency so stale or duplicated confirmations cannot
  overwrite a newer mandate. Successful change atomically creates a new immutable version.
- Invalidate cached authorization decisions and re-evaluate every unresolved/pending
  proposal against the new mandate. Previously executed side effects are not retroactively
  rewritten; their original evidence remains immutable.
- The model may explain the structured flow but cannot submit, confirm, approve, or lower
  an override and receives no capability that bypasses the deterministic endpoint.

**Verification:** NOT RUN. Required evidence includes owner/non-owner identity, lower/equal/
higher values, missing/whitespace/oversized/injection-like rationale, unselected and stale
confirmation, duplicate/idempotent submission, concurrent mandate update, exact USD impact,
disclosure persistence, pending-proposal invalidation/re-evaluation, immutable prior actions,
and proof that voice/model/carrier content cannot complete the override.

**Would change if:** enterprise roles or regulation require dual control, suitability
checks, or prohibit lower overrides. Those requirements need a separate approved identity
and governance model; they must not be inferred by RT.

## D23 / Person 2 D-03A — Authoritative mandate changes through dashboard only

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:42-05:00

**Context:** D22 identifies the authenticated mandate owner but does not define which
interaction channel may create authority. Voice transcription and LLM interpretation are
probabilistic and exposed to caller manipulation, replay, ambiguity, and prompt injection.

**Alternatives considered:**

- **A — Authenticated dashboard only.** Voice/models may explain but cannot draft, accept,
  override, or mutate the authoritative mandate; the dashboard presents an exact diff for
  explicit confirmation.
- **B — Voice initiation with dashboard confirmation.** Preserves final dashboard authority
  but adds non-authoritative draft state and more confusion/injection/replay test surface.
- **C — Voice mutation with a spoken PIN.** Conversational but vulnerable to recording,
  interception, transcription error, social engineering, and injected dialogue.
- **D — Voice mutation after model confirmation.** Fast but places probabilistic
  interpretation in the authorization boundary and violates complete mediation.

**Decided:** Alternative A. Every authoritative mandate creation or mutation—including RT
acceptance/override, currency margin, cost cap, escalation rule, or other constraint—occurs
only through an authenticated dashboard flow mediated by deterministic server policy.
Voice, Realtime sessions, input/output models, callers, carriers, and model-issued tool
requests have no capability to create drafts or write mandate state.

**Why:** A makes the primary security principle structural: a caller statement cannot
modify authority because the call path has no mandate-write capability. It also creates a
clear Trial-by-Fire demonstration of prompt-injection resistance by architecture.

**Trade-off accepted:** the owner must leave or accompany the call experience with the
dashboard to change constraints. This adds friction and prevents a fully voice-only setup.
Channel separation does not by itself authenticate the owner; dashboard identity/session
requirements still need explicit design and testing.

**Implementation contract:**

- Expose mandate-write operations only to the authenticated dashboard backend boundary.
  Do not include mandate create/update/accept/override tools in Realtime or model tool sets.
- The voice path may retrieve a minimal policy-safe summary needed to explain a denial but
  cannot create a pending draft, confirmation token, mutation intent, or reusable write payload.
- Dashboard displays a canonical field-level before/after diff, affected pending proposals,
  disclosures, and policy consequences. Confirmation controls are unselected and bound to
  authenticated actor, current mandate version, exact canonical payload, and short expiry.
- Server-side policy independently parses, validates, authorizes, and atomically persists
  the confirmed change. Client UI state, model prose, and hidden fields are never authority.
- Use CSRF protection, secure session handling, reauthentication/step-up rules as separately
  approved, optimistic concurrency, idempotency, and immutable audit evidence. A stale or
  replayed confirmation fails without partial mutation.
- Any endpoint reachable with a voice/session/model credential is technically unable to
  invoke the dashboard mutation service. Prove capability separation, not merely prompt rules.
- After mutation, invalidate prior authorization caches and re-evaluate unresolved proposals
  as required by D22. Do not retroactively change completed side-effect evidence.
- Logs and UI explanations avoid exposing full mandate contents where unnecessary and never
  expose session credentials, confirmation tokens, or internal authorization details.

**Verification:** NOT RUN. Required evidence includes absent mandate-write voice tools,
direct endpoint calls with voice/model credentials, injected caller instructions, dashboard
owner/non-owner authorization, canonical diff tampering, CSRF, stale/expired/replayed tokens,
concurrent versions, duplicate requests, atomicity, audit attribution, pending-proposal
re-evaluation, and architectural proof that probabilistic components lack the capability.

**Would change if:** a future channel can provide independently verified strong human
authentication and deterministic transaction confirmation without granting the model
authority. Any voice-initiated draft or mutation requires a new threat model and approval.

## D24 / Person 2 D-03B — Supabase email OTP plus TOTP for mandate writes

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:44-05:00

**Context:** D23/D-03A confines mandate mutation to the dashboard, but channel separation
does not authenticate the mandate owner or protect a sensitive write after ordinary session
compromise. The repository already contains Supabase dependencies, but that scaffold did
not constitute approval of an identity design.

**Alternatives considered:**

- **A — Supabase email OTP plus required TOTP for mandate writes.** Passwordless primary
  sign-in with authenticator-app MFA/AAL2 for sensitive authority changes; Basic MFA is
  currently included in Supabase Free.
- **B — Supabase email OTP only.** Simpler, but compromise of email or an ordinary active
  session is sufficient to change financial authority.
- **C — GitHub OAuth through Supabase.** Convenient for developers but unsuitable as the
  default customer identity model and still requires step-up protection.
- **D — Local demo identity.** Fast but cannot substantiate trustworthy ownership or
  authorization claims.

**Decided:** Alternative A. Use Supabase Auth email OTP for the initial dashboard sign-in.
Mandate creation, RT acceptance/override, and every mandate mutation require a verified
TOTP enrollment and current AAL2 evidence, followed by Volta's deterministic short-lived
transaction confirmation. The backend independently verifies the signed JWT, issuer,
audience, expiry, session/subject, MFA assurance, mandate ownership, and current mandate
version before processing a write.

**Why:** A provides two distinct factors at no subscription charge for the hackathon and
keeps identity enforcement separate from voice/model content. It uses the scaffolded
provider while retaining deterministic application authorization and audit evidence.

**Trade-off accepted:** enrollment and TOTP entry add friction and account-recovery risk.
Email security still affects initial access, and TOTP is phishable. Supabase Free currently
lacks some plan-level session controls and retains Auth audit logs briefly, so Volta must
enforce sensitive-action freshness and durable audit evidence itself. The built-in SMTP
service is restricted to pre-authorized project-team addresses and is not a production
customer email service.

**Cost and scope contract:**

- Hackathon baseline subscription cost is USD 0 under the currently documented Supabase
  Free allowances and Basic MFA inclusion. Revalidate pricing/terms before deployment.
- Use only pre-authorized project-team email addresses with Supabase's built-in sender.
  External-customer email requires an approved custom SMTP provider, its monetary/privacy/
  deliverability costs, and a new recorded decision; do not silently add one.
- TOTP uses the customer's authenticator application and creates no per-message SMS cost.
  Phone MFA is outside scope and must not be enabled without cost/security approval.

**Implementation contract:**

- Use Authorization Code with PKCE where applicable and validate provider-issued tokens
  server-side against trusted signing keys/claims. Never decode without signature and claim
  verification, trust client-provided user IDs, or use model/caller identity assertions.
- Require verified email and enrolled/verified TOTP before the first mandate write. Enforce
  AAL2 and a separately approved recent-authentication window for every sensitive action;
  a long-lived refreshable session alone is insufficient.
- Bind Volta's one-time transaction confirmation to actor, session, mandate/version,
  canonical diff/payload digest, action, issue/expiry time, and nonce; consume atomically.
- Check the underlying Supabase session where strong logout/revocation guarantees are
  required rather than relying only on an unexpired JWT. Authentication-provider outage
  or unverifiable session state fails closed for writes.
- Use secure, `HttpOnly`, `Secure`, appropriately `SameSite` cookies or an equivalently
  reviewed token architecture; never store service-role credentials in browser code or
  expose them in logs, URLs, errors, source maps, or repository files.
- Apply CSRF defenses, strict redirect allowlists, rate limits, generic OTP error messages,
  replay protection, recovery controls, and durable Volta audit records independent of the
  provider's short free-plan Auth-log retention.
- Database authorization uses least privilege and RLS defense-in-depth, but the backend
  reference monitor still performs deterministic ownership and policy checks. Possession
  of an `authenticated` JWT alone is not authorization to mutate any mandate.
- Recovery, factor reset, email change, and owner transfer are high-risk flows and remain
  disabled until separately approved; administrators cannot bypass this through model tools.

**Verification:** NOT RUN. Required evidence includes OTP enrollment/sign-in, unverified
email, absent/invalid/replayed TOTP, AAL1 versus AAL2, wrong issuer/audience/signature,
expired JWT, revoked/missing session, non-owner, CSRF, redirect abuse, confirmation payload
tampering/expiry/replay/concurrency, cookie/token leakage checks, service-role absence from
the client, provider outage, durable audit retention, and voice/model inability to authenticate.

**Would change if:** provider terms, security behavior, delivery restrictions, or product
requirements no longer fit. Production external email, passkeys, different MFA, enterprise
SSO, recovery, or paid session controls each require explicit review and approval.

## D25 / Person 2 D-03C — Fresh TOTP and two-minute confirmation per mandate write

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:45-05:00

**Context:** an AAL2 session proves that MFA occurred but does not by itself prove immediate
second-factor participation in each authority change. Mandate writes are infrequent,
high-consequence actions, so recency and transaction binding must be explicit.

**Alternatives considered:**

- **A — Fresh TOTP for every mandate write.** Each write requires a new TOTP challenge,
  followed by a single-use confirmation bound to the exact transaction and valid for two
  minutes.
- **B — Five-minute MFA window.** Reduces repeated challenges but permits several authority
  changes from a briefly unattended or stolen session.
- **C — Fifteen-minute MFA window.** More convenient for configuration sessions but
  materially increases post-authentication exposure.
- **D — AAL2 session only.** Relies on potentially old MFA state and provides no sensitive-
  action recency guarantee.

**Decided:** Alternative A. Every mandate creation, RT acceptance, RT override, and other
mandate mutation requires a newly completed TOTP challenge for that action. Successful
verification creates a server-side transaction confirmation bound to the exact canonical
mutation; it expires two minutes after issuance and can be consumed exactly once.

**Why:** A produces direct evidence that the second factor participated immediately in
each authority change and minimizes what an unattended authenticated session can do. The
friction is acceptable because mandate writes should be uncommon.

**Trade-off accepted:** customers must enter TOTP repeatedly during configuration and may
experience expiration while reviewing a change. Clock skew, accessibility, and device-loss
support need careful handling; recovery remains deliberately unavailable pending approval.

**Implementation contract:**

- Do not treat an existing AAL2 claim alone as fresh authorization. Start and verify a new
  provider-backed TOTP challenge for each canonical mandate-write action.
- On successful challenge, issue/store an opaque, cryptographically random confirmation
  reference bound server-side to authenticated subject, Supabase session ID, mandate ID and
  current version, action, exact canonical payload/diff digest, issue time, expiry time,
  challenge evidence reference, and unused status.
- Expiry is exactly two minutes measured using trusted server time. `now < expires_at` is
  usable; `now >= expires_at` is expired. Browser/model/caller clocks are ignored.
- Atomically validate and consume the confirmation in the same transaction as the mandate
  write. Mark it consumed even if a duplicate client request races; idempotent response
  semantics must not permit a second mutation.
- Any payload, mandate version, actor, session, or action change requires a new TOTP
  challenge. Confirmation references cannot be transferred between users, tabs, mandates,
  actions, or sessions.
- Rate-limit challenge creation and verification by account/session/network signals without
  exposing whether an account or factor exists. Do not log TOTP values or confirmation
  secrets; redact sensitive provider errors.
- A timeout returns the user to review with a stable draft display but no authority. The
  user must inspect the current mandate/diff and complete a new challenge; never auto-submit.
- Voice/model paths cannot initiate challenges, receive confirmation references, or consume
  them. Dashboard client possession still does not replace all server-side binding checks.

**Verification:** NOT RUN. Required evidence includes a new challenge per action, previous-
AAL2 rejection, expiry immediately before/at/after two minutes, server/client clock skew,
single-use and concurrent consumption, payload/action/actor/session/mandate/version swaps,
duplicate idempotency, rate limiting, redaction, timeout/review behavior, provider outage,
and proof that voice/model paths cannot initiate or consume confirmation.

**Would change if:** usability testing demonstrates unacceptable friction and an alternative
provides equivalent transaction-bound proof. Any reusable freshness window, passkey, or
different confirmation lifetime requires a new approved threat-model decision.

## D26 / Person 2 D-04A — Two-phase deterministic external commitment

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:47-05:00

**Context:** a negotiated acceptance may create an external carrier obligation and an
internal committed record. Authorizing a proposal long before execution, or treating model
output as commitment authority, permits mandate, quote, FX, or state changes to bypass
complete mediation and makes timeout/retry behavior unsafe.

**Alternatives considered:**

- **A — Two-phase deterministic commit protocol.** Prepare an exact structured operation,
  then revalidate immediately before one idempotent external side effect; represent
  uncertain outcomes explicitly for reconciliation.
- **B — Authorize once at proposal creation and execute later.** Simpler but permits
  authorization evidence to become stale before the consequential mutation.
- **C — Dashboard approval for every commitment.** Strong human control but removes the
  autonomous in-mandate negotiation central to the challenge.
- **D — Output-model commit decision.** Conversationally smooth but makes probabilistic
  behavior an authorization authority.

**Decided:** Alternative A. The model can propose only a typed immutable commitment
candidate. Deterministic policy may create a short-lived `PREPARED` operation bound to the
exact current mandate/version, state/version, carrier/quote, comprehensive cost components,
FX and calendar evidence, accepted margin, all-in USD authorization value, and canonical
outbound commitment payload. Immediately before the sole external side-effect adapter is
invoked, policy revalidates every condition and atomically claims the operation for one
idempotent attempt. Terminal/safety states include `COMMITTED`, `DENIED`, `EXPIRED`, and
`UNKNOWN`; `UNKNOWN` requires reconciliation and cannot be retried as if nothing happened.

**Why:** A preserves autonomous action inside human-issued authority while proving complete
mediation at the moment that matters. It makes crashes, duplicate callbacks, and ambiguous
carrier responses explicit state-machine cases rather than accidental duplicate bookings.

**Trade-off accepted:** external systems and Volta's database cannot generally share one
atomic transaction. The protocol therefore adds leases, idempotency, durable outbox/audit
records, reconciliation, and more states. A carrier that lacks idempotency or status lookup
may be unsafe to support for binding commitments.

**Implementation contract:**

- Only typed canonical domain data enters policy. Free text and model rationale are evidence,
  never authoritative fields. Canonicalization/versioning occurs before hashes or signatures.
- `PREPARED` stores immutable references/digests for actor/operation, current mandate and
  state versions, carrier and quote identity/version/expiry, every comprehensive-all-in cost
  component, original currencies, FX snapshot/cross-check/margin, calculated USD values,
  calendar/RT evidence where applicable, proposed conditions, outbound payload, policy and
  schema versions, authorization result/reasons, and preparation/expiry timestamps.
- Preparation performs no external binding side effect and grants no reusable general
  permission. Its exact operation identifier and payload digest cannot authorize another offer.
- Immediately before dispatch, acquire an atomic claim/lease and re-read authoritative
  mandate, operation, quote, FX freshness/divergence, state, time window, resource limits,
  and revocation/cancellation flags. Any mismatch deterministically denies or expires before
  the adapter receives a request.
- The external adapter accepts only a policy-issued execution capability scoped to the exact
  claimed operation; tools/models cannot call it directly. Pass one stable idempotency key
  derived from the operation identity where the carrier supports it.
- Record request intent durably before dispatch without falsely marking commitment. Validate
  and preserve the external response, carrier reference, timestamps, payload/result digests,
  and reason-coded state transition. Emit notifications through a durable outbox after state
  transition; notification failure never changes authorization truth.
- Definite success becomes `COMMITTED` once. Definite rejection becomes a reason-coded safe
  terminal failure. Timeout, connection loss after dispatch, malformed/contradictory response,
  or crash with possible dispatch becomes `UNKNOWN`, blocks automatic retry and conflicting
  negotiation, and enters deterministic/manual reconciliation.
- A duplicate request/callback returns the existing operation result and cannot repeat the
  side effect. `COMMITTED` is immutable except for separately modeled cancellation/compensation;
  records are never overwritten to make state appear clean.
- Prepared lifetime, claim lease, supported-carrier idempotency/reconciliation requirements,
  and unknown-outcome escalation timing remain separate human decisions.

**Verification:** NOT RUN. Required evidence includes proposal without side effect, exact
payload/version binding, mandate/state/quote/FX changes between phases, expiry, concurrent
claims, duplicate dispatch/callback, crash before/during/after request, timeout with possible
success, malformed/conflicting carrier results, no-idempotency carrier, outbox failure,
`UNKNOWN` retry prohibition/reconciliation, and proof that model/tool paths lack adapter access.

**Would change if:** a carrier provides a stronger transactional interface or the product
requires human approval for specific commitment classes. No change may weaken immediate
pre-side-effect policy revalidation or permit ambiguous automatic retry.

## D27 / Person 2 D-04B — Thirty-second prepared-operation lifetime

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T14:55-05:00

**Context:** D26/D-04A requires a short-lived `PREPARED` operation but left its lifetime
undefined. Quote, FX, mandate, and negotiation state can change, so an executable capability
must remain close to the revalidation and dispatch moment.

**Alternatives considered:**

- **A — Thirty seconds.** Expire 30 seconds after trusted server preparation or at any
  earlier underlying validity boundary; dispatch still performs complete revalidation.
- **B — Two minutes.** More tolerant of processing delay but leaves stale executable state
  available four times longer.
- **C — Carrier quote expiry only.** Simple but ignores earlier FX, mandate, operation, and
  policy validity changes.
- **D — No fixed lifetime.** Relies solely on final revalidation and increases stale-state
  and replay exposure.

**Decided:** Alternative A. A `PREPARED` operation expires exactly 30 seconds after its
trusted server-side `prepared_at`, or sooner at the earliest bound quote, FX, mandate,
operation, policy, or other required evidence expiry. It cannot be extended, refreshed,
or revived; a new proposal/preparation is required after expiry. Final dispatch still
performs every D26 revalidation.

**Why:** A leaves enough time for normal server-side prepare-and-dispatch while sharply
limiting delayed/replayed executable state. It gives Trial-by-Fire a clear deterministic
expiry boundary without pretending TTL replaces complete mediation.

**Trade-off accepted:** transient latency or pauses can expire an otherwise valid offer,
requiring a new preparation and possibly new carrier interaction. This favors safety over
continuity and may need tuning from measured production latency.

**Implementation contract:**

- Set `expires_at = min(prepared_at + 30 seconds, every applicable bound validity end)`
  using trusted server time and explicit UTC instants. Caller, model, carrier, and browser
  clocks cannot determine or extend expiry.
- Boundary semantics are `now < expires_at` eligible for final revalidation and
  `now >= expires_at` expired. Acquisition/claim must atomically test this condition.
- Persist preparation/expiry instants, each candidate earlier bound and selected minimum,
  trusted-clock/version evidence, and the resulting reason code.
- Expired operations transition once to `EXPIRED`, cannot be claimed/dispatched, and cannot
  have their payload or timestamps edited. Duplicate expiry processing is idempotent.
- Creating a replacement requires a new operation ID, current evidence, policy evaluation,
  payload digest, and idempotency key. Never copy an old execution capability.
- A timer or background cleanup is not the security boundary; every read/claim/dispatch
  independently checks expiry. Cleanup may remove only according to approved retention rules.
- Final revalidation remains mandatory even one instant after preparation. Passing TTL is
  necessary but never sufficient authorization.

**Verification:** NOT RUN. Required evidence includes immediately before/at/after 30
seconds, an earlier quote/FX/evidence expiry, future/skewed client/model time, cleanup delay,
concurrent claim at the boundary, duplicate expiry, attempted extension/revival, replacement
identity/evidence, and proof that an unexpired operation still fails changed-state checks.

**Would change if:** measured end-to-end dispatch latency shows safe operations routinely
cannot finish preparation-to-claim within 30 seconds. Any increase requires latency evidence,
threat review, and human approval; processing must not extend TTL dynamically.

## D28 / Person 2 D-04C — No automatic redispatch after execution claim

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T15:01-05:00

**Context:** after an external dispatch is claimed, a worker can crash or lose the response
after the carrier has already accepted the request. Returning the operation to `PREPARED`
when a lease expires can cause a second binding commitment.

**Alternatives considered:**

- **A — Never automatically redispatch a claimed operation.** Atomic claim moves to
  `EXECUTING`; lost certainty becomes `UNKNOWN` and only status reconciliation may resolve it.
- **B — Redispatch automatically after lease expiry.** Improves availability but risks a
  duplicate commitment when the first request succeeded without a recorded response.
- **C — Redispatch only for carriers claiming idempotency.** Practical, but correctness then
  depends on a potentially incomplete or misunderstood external guarantee.
- **D — Let an operator reset to prepared.** Removes automated retry but still permits an
  unsafe resend and weakens immutable transition evidence.

**Decided:** Alternative A. Once policy atomically claims a `PREPARED` operation, it enters
`EXECUTING` and can never transition back to `PREPARED`. A crash, dispatch timeout,
connection loss, ambiguous/malformed response, stale executing watchdog, or any inability
to prove definite success or definite rejection transitions to `UNKNOWN`. Neither a worker,
scheduler, model, nor operator may redispatch that operation. Reconciliation may only query
or receive carrier status using the existing operation/idempotency/reference evidence.

**Why:** A makes at-most-one dispatch attempt the safe local invariant and prevents recovery
logic from converting uncertainty into a duplicate obligation. Availability loss is visible
and auditable rather than hidden behind a retry.

**Trade-off accepted:** operations can remain blocked in `UNKNOWN`, require carrier lookup
or human investigation, and delay negotiation. Even a carrier with strong idempotency is
not used for automatic redispatch under this baseline.

**Implementation contract:**

- Atomically compare-and-set `PREPARED -> EXECUTING` while checking D26/D27 policy,
  versions, expiry, and claim uniqueness. Persist claimant, attempt number fixed at one,
  trusted start time, idempotency key, request intent/payload digest, and audit event before I/O.
- State transitions are monotonic. No code path, administrative endpoint, migration, model
  tool, cleanup job, or lease expiry may transition `EXECUTING`/`UNKNOWN` to `PREPARED` or
  create another dispatch attempt for the same logical commitment.
- Configure a watchdog threshold separately from authorization TTL. Crossing it marks
  unresolved execution `UNKNOWN`; it does not release or reacquire an execution capability.
- Definite authenticated carrier success may transition `EXECUTING` directly to `COMMITTED`.
  Definite authenticated rejection may transition to the approved failure state. Anything
  ambiguous becomes `UNKNOWN` with reason-coded evidence.
- Reconciliation is read/status-only with respect to the carrier commitment operation. It
  uses the original idempotency key/carrier reference and cannot invoke a create/book/accept
  endpoint or generate a replacement commitment.
- A carrier status proving the original succeeded may transition `UNKNOWN -> COMMITTED` once;
  status proving definitive rejection may transition to the approved failure state. Lack
  of proof leaves `UNKNOWN`; absence of a result is not proof of rejection.
- A genuinely new business attempt, if ever permitted after definitive rejection, requires
  a new logical proposal/operation and fresh policy evaluation; that rule remains separate.
- Block conflicting negotiation/commitment while `EXECUTING` or `UNKNOWN`. Notify/escalate
  through the outbox without changing truth if notification fails.

**Verification:** NOT RUN. Required evidence includes concurrent claims, crash before and
after network send, timeout, response loss, malformed/contradictory result, watchdog expiry,
worker/scheduler/operator retry attempts, carrier idempotency claims, query-only reconciliation,
authenticated success/rejection resolution, absent status remaining unknown, immutable attempt
count, conflicting-operation block, and proof that models/tools cannot reacquire dispatch.

**Would change if:** a formally verified carrier protocol provides atomic exactly-once
semantics and the team approves relying on it. Even then, the change requires carrier-specific
tests and cannot become a generic retry policy.

## D29 / Person 2 D-04D — Canonical policy-generated spoken acceptance

**Status:** SUPERSEDED by D31/D-04F (originally approved)

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T15:41-05:00

**Superseded at:** 2026-08-29T16:15-05:00. The decision owner clarified that carrier
calls produce non-binding pre-agreements and that only a later official email can create
the operational commitment. Preserve this entry as decision history; do not implement it.

**Context:** in a telephone negotiation, the consequential external side effect may be the
acceptance sentence itself rather than a structured booking API. Allowing an output model to
compose final language after policy approval permits it to add, omit, or distort material
terms and makes partial/interrupted audio an ambiguous commitment.

**Alternatives considered:**

- **A — Policy-generated canonical acceptance phrase.** The output model proposes a typed
  acceptance, deterministic policy authorizes and generates the exact phrase, and audio
  transmission begins in `UNKNOWN` until separate carrier confirmation evidence exists.
- **B — Voice negotiation always non-binding.** Strongest legal/technical separation but
  weakens the autonomous voice commitment central to the demonstration.
- **C — Model-phrased acceptance after policy approval.** Natural conversation but allows
  post-authorization semantic drift in the actual consequential output.
- **D — Live human approval before acceptance.** Strong operational oversight but removes
  autonomous in-mandate commitment.

**Decided:** Alternative A. The models may propose only structured acceptance fields.
Following D26/D27/D28 checks, deterministic trusted code renders one versioned canonical
phrase containing the material approved terms; the model cannot edit or paraphrase it.
Immediately before the first acceptance audio frame is handed to the output channel, the
operation is atomically claimed and recorded as `EXECUTING`; once any such frame may have
left Volta, loss of complete, evidenced delivery or response produces `UNKNOWN`. It becomes
`COMMITTED` only under separately approved confirmation evidence. The phrase is never
automatically repeated.

**Why:** A preserves autonomous voice negotiation while moving commitment language into
the deterministic authorization boundary. It makes the exact spoken payload replayable and
treats audio uncertainty conservatively.

**Trade-off accepted:** canonical speech is less natural and may still be interrupted,
misheard, delayed, or legally interpreted differently. Technical state does not determine
whether a contract formed under applicable law. Without reliable carrier confirmation,
operations can remain `UNKNOWN` and block further commitment.

**Implementation contract:**

- Define a versioned renderer in trusted non-LLM code. Its inputs are only the exact typed
  fields authorized in `PREPARED`; free text, model prose, retrieved content, and caller
  wording cannot enter the commitment phrase.
- The phrase states the carrier/offer reference, comprehensive all-in price and explicit
  ISO 4217 currency, agreed service/scope, critical dates/window, and conditions needed to
  distinguish the accepted offer. Omitted/unknown required fields make rendering/authorization
  fail; never fill them with conversational inference.
- Store canonical text, normalized structured fields, renderer/schema/language version,
  payload digest, and the corresponding authorization evidence before audio transmission.
- Use only an approved deterministic TTS/output path for this phrase. The output model may
  introduce it or explain afterward but receives no capability to alter, append material
  conditions to, overlap, or synthesize the acceptance audio.
- Atomically claim/revalidate before handing the first frame to the channel. Preserve trusted
  frame/event timestamps and channel delivery callbacks as transport evidence without
  equating provider acceptance of a frame with the counterparty's contractual agreement.
- Any first-frame handoff followed by disconnect, cancellation, barge-in, partial playback,
  callback loss, timeout, or uncertain receipt becomes/remains `UNKNOWN`. Do not resume from
  the middle, repeat, paraphrase, or create a second acceptance operation automatically.
- Suppress all other model/tool audio while canonical acceptance is scheduled/transmitting.
  Prompt injection cannot make ordinary model speech resemble an authoritative acceptance;
  noncanonical attempts are denied and audited.
- The UI/audit record distinguishes `authorized text`, `transport attempted`, `transport
  evidence`, and `carrier confirmation`. It includes a legal/product limitation that Volta's
  technical state alone does not determine contract formation.
- Consent, recording, disclosure, retention, supported language, exact material fields, TTS
  behavior, and sufficient carrier-confirmation evidence remain separate approvals.

**Verification:** NOT RUN. Required evidence includes field omission/unknowns, model-added
terms, payload/render-version mismatch, deterministic repeatability, first-frame atomicity,
disconnect before/at/after first frame, barge-in and partial playback, callback loss, model
audio suppression, prohibited replay/paraphrase, concurrent acceptance attempts, audit-layer
distinctions, and proof that only policy capability can invoke canonical acceptance output.

**Would change if:** legal review or carrier process requires a structured written/API
confirmation, or speech delivery cannot be evidenced safely. In that case voice becomes
non-binding rather than allowing model-authored commitment language.

## D30 / Person 2 D-04E — Same-call DTMF carrier confirmation

**Status:** SUPERSEDED by D31/D-04F (originally approved)

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T15:43-05:00

**Superseded at:** 2026-08-29T16:15-05:00. DTMF confirmation is unnecessary because the
call does not commit. Carrier verbal confirmation supports accuracy of a non-binding
pre-agreement only. Preserve this entry as decision history; do not implement it.

**Context:** transport completion proves only that Volta attempted to play acceptance audio;
free-form carrier speech still depends on probabilistic audio capture, transcription, and
semantic interpretation. A deterministic confirmation signal is needed before resolving a
spoken acceptance from uncertainty to `COMMITTED`.

**Alternatives considered:**

- **A — Same-call DTMF confirmation.** After complete canonical playback, request a random
  operation-bound key; only a valid Twilio-signed DTMF event from the same live call may
  resolve the operation as committed.
- **B — Model-interpreted verbal confirmation.** Natural but makes ASR/LLM semantics part
  of the authorization boundary.
- **C — Completed acceptance playback means committed.** Deterministic transport evidence
  but no evidence that the carrier agreed.
- **D — Human dashboard review of the recording.** Stronger semantic oversight but delays
  autonomous completion and adds manual processing.

**Decided:** Alternative A. After the canonical acceptance phrase finishes with complete
transport evidence, trusted code gives a deterministic confirmation instruction and opens
a short, operation-bound DTMF challenge on the same live call. A valid Twilio-signature-
verified callback containing the expected key, correct call identity, operation/challenge,
state, and timing may transition `UNKNOWN`/`EXECUTING` to `COMMITTED` exactly once. Missing,
early, wrong, repeated, late, unsigned/invalid, or otherwise ambiguous input does not commit
and leaves the operation `UNKNOWN` for reconciliation.

**Why:** A uses a structured channel event that deterministic code can validate without
asking an LLM to decide what the counterparty meant. It preserves autonomous completion
and adds no service category beyond existing Twilio call duration.

**Trade-off accepted:** a keypress proves interaction with the designed call flow but not
the legal identity, authority, comprehension, or contractual intent of the person pressing
it. DTMF can be mistyped, inaccessible, delayed, or lost. Legal review remains necessary
before claiming that this evidence conclusively forms a contract.

**Implementation contract:**

- Generate the expected confirmation key using trusted cryptographic randomness from an
  approved DTMF set; bind its challenge record to operation ID, exact acceptance payload
  digest, Twilio Call SID, issue/expiry times, state/version, nonce, and unused status.
- Do not reveal or request the key until trusted transport evidence says the complete
  canonical acceptance phrase finished. A key received before challenge activation cannot
  be buffered or later reused as confirmation.
- Render confirmation instructions from a fixed versioned template that identifies the
  accepted offer/reference and states that the key confirms those exact terms. The output
  model cannot compose, omit, overlap, or alter this instruction.
- Verify Twilio webhook signatures over the exact externally received URL and parameters
  using the server-side Auth Token and current official validation procedure. Reject before
  parsing state when signature, canonical URL/proxy configuration, call identity, or expected
  account/application context is invalid. Never log the Auth Token.
- Atomically validate challenge state/timing/key/call/operation/payload and consume it in
  the same transaction as the single `COMMITTED` transition. Duplicate callbacks return
  the existing result without another transition or notification.
- A wrong/extra/multi-digit, missing, early, expired, call-disconnected, or conflicting event
  is reason-coded evidence and cannot create a fresh challenge or automatic acceptance replay.
- Verbal responses and transcripts may be retained as approved supporting evidence but are
  never the deterministic commit oracle. Silence and model confidence do not count.
- Preserve signature-validation outcome (not secret material), sanitized callback digest,
  Call SID/reference, challenge/template versions, expected/received outcome without exposing
  reusable secrets, timestamps, transport evidence, operation transition, and audit event.
- Confirmation window, DTMF key set/attempt policy, consent/recording, caller/carrier identity
  assurance, and reconciliation/escalation remain separate human decisions.

**Verification:** NOT RUN. Required evidence includes complete versus partial playback,
keypress before activation, expected/wrong/missing/multiple/late keys, replay/concurrent
callbacks, different Call SID/operation/payload, forged/malformed signatures, reverse-proxy
URL reconstruction, disconnects, duplicate notification suppression, supporting verbal
confirmation without DTMF, secret/log redaction, and proof that model tools cannot activate,
answer, extend, reset, or consume the challenge.

**Would change if:** accessibility, carrier workflow, legal review, or telephony behavior
makes DTMF unsuitable. Replacement must provide equally deterministic operation-bound
evidence or require human review; probabilistic verbal classification cannot silently replace it.

## D31 / Person 2 D-04F — Calls create pre-agreements; official email commits

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:15-05:00

**Context:** D29/D-04D and D30/D-04E incorrectly treated spoken acceptance during the
quotation call as the binding side effect. The decision owner clarified the intended
business process: calls collect non-binding carrier quotations/pre-agreements; Volta later
compares them and, according to a customer-selected mandate mode, either commits autonomously
or escalates for human approval. Commitment is communicated through an official email.
Volta does not manage payment.

**Alternatives considered:**

- **A — Non-binding calls; canonical email commitment with mandate-selected autonomy.**
  Carrier speech confirms captured pre-agreement accuracy only. Deterministic policy selects
  an eligible option, then either sends after autonomous authorization or dashboard approval.
- **B — Calls may themselves commit.** The superseded spoken-acceptance/DTMF design; this
  does not match the intended workflow and creates avoidable voice ambiguity.
- **C — Always require human approval.** Strong oversight but removes the customer's option
  to delegate autonomous in-mandate commitment.
- **D — Autonomous email without a mandate setting.** Simple but lets the system determine
  its own authority level rather than following explicit human-issued authority.

**Decided:** Alternative A. Telephone calls are quotation and negotiation channels only.
The model recaps the structured pre-agreement and asks the carrier/counterparty to confirm
that the captured terms are accurate; a positive response creates supporting evidence for
a `CARRIER_CONFIRMED_PREAGREEMENT`, never a commitment. After eligible pre-agreements are
compared, the authoritative mandate field `commitment_mode` determines the path:
`AUTONOMOUS` permits deterministic server policy to commit the selected eligible option
without transaction-specific human approval; `HUMAN_ESCALATION` requires authenticated
dashboard approval of that exact option. In both modes, the consequential side effect is
one policy-generated official commitment email sent to the verified carrier/provider
destination after immediate complete revalidation. Payment initiation, authorization,
collection, custody, and settlement are outside Volta's scope.

**Why:** A matches the actual business intent, preserves customer choice over delegated
authority, and removes probabilistic voice semantics from the commitment boundary. It keeps
the useful call recap while making the official written communication exact and auditable.

**Trade-off accepted:** email delivery is not equivalent to receipt, reading, acceptance,
or legal contract formation. Verbal carrier confirmation can be misheard or misclassified,
so uncertain pre-agreement fields must be reviewed or excluded rather than treated as fact.
Autonomous commitment increases customer-impact risk and needs strict mandate/configuration,
selection, destination, template, and delivery controls. Email provider costs, retention,
privacy, domain identity, and delivery evidence remain separate decisions.

**Supersedes:** D29/D-04D and D30/D-04E in full. Their approved history remains recorded,
but no canonical spoken acceptance or DTMF commitment flow may be implemented. D26/D-04A,
D27/D-04B, and D28/D-04C continue to govern preparation, expiry, single dispatch, and
unknown outcomes, with the official email send as the external commitment attempt.

**Implementation contract:**

- Call/session/model credentials have no commitment-email capability. During calls, tools
  may create or update only typed non-binding pre-agreement candidates through deterministic
  validation; state and UI label them visibly as non-binding.
- The input model extracts a typed candidate; trusted code validates required fields,
  currency/cost decomposition, quote identity/validity, service/scope, conditions, dates,
  carrier identity/reference, and evidence links. Unknown/ambiguous fields remain unknown.
- The output model may conversationally recap only from the validated structured candidate
  and ask whether it is accurate. Carrier speech is untrusted evidence: positive model/ASR
  interpretation proposes `carrier_confirmation`, while deterministic code binds transcript/
  audio evidence and confidence/ambiguity metadata. It never authorizes or commits.
- Contradiction, correction, low confidence, missing material terms, or unclear confirmation
  prevents `CARRIER_CONFIRMED_PREAGREEMENT`. The model cannot convert politeness, silence,
  partial assent, or unrelated affirmative language into authoritative terms.
- Candidate comparison is deterministic over complete, current, mandate-eligible normalized
  fields and an approved objective/tie-break policy. The LLM may explain results but cannot
  choose the winner or alter eligibility. Selection policy remains a separate approval.
- `commitment_mode` is an authoritative versioned mandate enum with no default. It can be
  created/changed only through the D23/D24/D25 dashboard flow. Callers, carriers, models,
  and per-call state cannot select or change it.
- `AUTONOMOUS` means policy may prepare the selected eligible candidate only within every
  current mandate constraint. `HUMAN_ESCALATION` means no email is prepared/sent until the
  authenticated owner approves the exact candidate and canonical email payload through a
  separately defined transaction-approval flow.
- Immediately before email dispatch, re-read and revalidate mandate/mode/version, candidate
  and selection versions, quote validity, comprehensive-all-in USD cost and FX evidence,
  carrier/destination verification, exact service/conditions/dates, absence of conflicting
  commitment, policy/template versions, and D26/D27 operation state. Any mismatch fails closed.
- Trusted deterministic code renders the canonical official email from approved structured
  fields and a versioned template. Models cannot edit subject, recipients, material terms,
  attachments, reply-to, headers, or body. Missing required fields blocks sending.
- Apply D28 at-most-one dispatch: durable intent before send; stable operation/idempotency
  evidence where supported; no blind resend after a possible attempt. Definite provider
  rejection is a failure; timeout/ambiguous acceptance or delivery becomes `UNKNOWN` for
  reconciliation. Delivery/receipt/read evidence must never be overstated.
- Preserve the pre-agreement and source evidence, recap and carrier response, eligibility/
  comparison result, mandate mode/version, human approval where required, canonical email
  and digest, verified destination provenance, provider request/result evidence, state
  transitions, notifications, and audit versions. Sensitive data follows approved minimization
  and retention rules.
- No component receives payment credentials or payment tools. Email content must not claim
  that Volta paid, transferred funds, guaranteed payment, or authorized a payment. Payment
  instructions received from callers/carriers are untrusted data and cannot trigger action.
- Product/legal wording distinguishes `pre-agreement recorded`, `commitment email attempted`,
  `email provider accepted`, `delivered` where evidenced, and any later carrier acknowledgment.
  Volta's internal label alone does not decide legal contract formation.

**Verification:** NOT RUN. Required evidence includes call-only capability restrictions,
complete/corrected/ambiguous recap, silence/polite affirmation/prompt injection, typed unknowns,
non-binding labels, missing `commitment_mode`, autonomous versus escalation paths, mandate
mode mutation only through dashboard, deterministic comparison and tie behavior, stale quote/
FX/mandate before email, recipient/header/template injection, exact email rendering, provider
timeout/rejection/duplicate callbacks, no resend from `UNKNOWN`, audit distinctions, and proof
that no payment capability or claim exists.

**Would change if:** legal review establishes a different commitment mechanism, a carrier
requires portal/API confirmation, or official email cannot provide suitable evidence. Any
new commitment channel needs its own complete-mediation and uncertainty decision; calls
remain non-binding unless the decision owner explicitly changes this rule.

## D32 / Person 2 D-04G — Lowest eligible buffered USD candidate; escalate if none

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:18-05:00

**Context:** D31/D-04F requires deterministic comparison of carrier-confirmed
pre-agreements but did not define `best`. The decision owner also requires escalation when
no candidate satisfies the price constraint so the responsible person—not the agent—can
decide whether to set a higher mandate bound or take another action.

**Alternatives considered:**

- **A — Lowest comprehensive buffered all-in USD cost.** Filter every hard mandate
  constraint first; select the lowest policy-evaluated USD value and apply deterministic
  tie-breaks. Escalate without commitment when no candidate is eligible.
- **B — Customer-configured weighted score.** More expressive but requires approved weights,
  normalization, provenance, missing-data, and anti-gaming rules.
- **C — Customer-configured priority order.** Easier than a weighted score but adds mandate
  and UI complexity and can produce unintuitive lexicographic results.
- **D — Model-selected winner.** Flexible but nondeterministic and vulnerable to carrier
  persuasion, prompt injection, and explanation drift.

**Decided:** Alternative A. Policy first evaluates every complete, current,
carrier-confirmed pre-agreement against every hard mandate constraint. Among eligible
candidates it selects the lowest comprehensive all-in USD authorization value after the
approved FX conversion and accepted safety margin. Exact ties resolve by earliest compliant
delivery, then earliest trusted carrier-confirmation timestamp, then lexicographically
smallest immutable candidate ID. If no candidate satisfies the price bound, Volta creates a
reason-coded `NO_ELIGIBLE_CANDIDATE` escalation for the responsible mandate owner and sends
no commitment email. The owner may keep the bound, change the mandate through D23–D25, seek
new quotations, or abandon the operation; Volta cannot increase or waive the bound itself.

**Why:** A makes `best` reproducible from already approved cost and eligibility evidence.
It prevents an LLM from trading away price or other hard constraints and keeps exceptional
risk appetite with the responsible human.

**Trade-off accepted:** lowest eligible cost does not optimize soft service quality,
reliability, sustainability, relationship value, or unmodeled carrier risk. Earliest delivery
is only a tie-break after every hard service requirement passes. A future richer objective
requires trusted data and a new decision.

**Implementation contract:**

- Take an immutable comparison snapshot of all candidate/version identifiers and the exact
  authoritative mandate/version. Exclude, with reason codes, any candidate that is incomplete,
  unconfirmed, expired, stale, unsupported, conflicting, or violates any hard constraint.
- Compute each eligible value using D9 comprehensive cost, D7/D13/D14 FX evidence, and the
  D8/D10–D22 accepted mandate margin. Compare exact integer USD minor-unit authorization
  values; never compare formatted strings, floats, original-currency amounts, or model scores.
- Sort eligible candidates by the tuple `(buffered_all_in_usd_minor_units,
  compliant_delivery_instant, carrier_confirmed_at, immutable_candidate_id)` ascending.
  Require canonical UTC delivery instants and trusted confirmation timestamps; ambiguous
  tie-break data makes the candidate ineligible rather than guessed.
- Re-run full eligibility and ranking during D26 preparation and immediately before D31
  email dispatch. If the selected candidate, winner tuple, mandate, quote, FX, or competing
  candidate set changed, invalidate preparation and recompute; never commit a stale winner.
- If at least one candidate passes all constraints, use the winner under either D31 mode.
  `AUTONOMOUS` permits preparation without transaction-specific approval;
  `HUMAN_ESCALATION` presents that exact winner for approval.
- If none passes specifically because buffered all-in USD exceeds the price bound, create
  `NO_ELIGIBLE_CANDIDATE` with a safe comparison showing the bound, lowest candidate amount,
  excess in USD, other exclusion reasons, quote expiries, and evidence versions. Do not
  disclose unnecessary carrier-sensitive details across tenants.
- No commitment email, booking, promise, payment action, or automatic mandate mutation occurs
  from the no-candidate state. Voice/model output may explain choices but cannot suggest that
  silence or conversational assent raises the cap.
- Only the current authenticated mandate owner may change the bound, using a canonical diff,
  fresh TOTP, and two-minute single-use confirmation under D23–D25. The owner may instead
  explicitly keep it, request a new negotiation round, or abandon/cancel the operation.
- Every mandate change versions authority and triggers complete candidate re-evaluation;
  it does not retroactively make an earlier denial authorized. Preserve the escalation,
  owner decision, new comparison, and all prior immutable evidence.
- No eligible candidate for a non-price reason also fails closed with reason-coded escalation;
  the system never relaxes service, date, scope, currency, cost-completeness, identity, or
  other constraints merely because price is acceptable.

**Verification:** NOT RUN. Required evidence includes one/many/no candidates, equal and
near-equal minor-unit costs, every tie-break layer, original-currency traps, stale/expired/
incomplete/unconfirmed candidates, price-only and mixed exclusions, candidate arrival/change
during preparation, autonomous and human modes, no-email/no-payment escalation, owner/non-owner
bound changes, fresh-MFA enforcement, re-evaluation after a new version, and proof that
model/caller/carrier content cannot rank, relax, or increase authority.

**Would change if:** users require approved soft preferences or risk-adjusted carrier quality.
Any scoring/priority extension needs explicit criteria, trusted provenance, normalization,
missing-data behavior, explainability, anti-gaming tests, and human approval.

## D33 / Person 2 D-04H — Resend Free for official commitment email

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:21-05:00

**Context:** D31/D-04F makes an official email the consequential commitment attempt, but
the repository contains no transactional email provider. The hackathon needs a provider
with authenticated-domain sending and delivery/bounce events at a disclosed cost.

**Alternatives considered:**

- **A — Resend Free.** REST API, webhooks, one custom domain, 3,000 emails/month and
  100/day at USD 0/month under the currently documented plan.
- **B — Amazon SES.** Low usage-based price (currently about USD 0.10 per 1,000 outbound
  messages à la carte, plus applicable data/AWS charges) but more IAM, domain, region,
  sandbox, and event infrastructure.
- **C — Existing organizational SMTP.** Potentially no incremental fee, but unknown quotas,
  authorization, credentials, sender policy, and delivery-event evidence.
- **D — Mock email.** No external cost or credentials but cannot demonstrate an official
  commitment attempt.

**Decided:** Alternative A. Use Resend's Free transactional-email plan for the hackathon
commitment channel, subject to the currently documented 3,000-message monthly and 100-message
daily limits, one verified custom domain, and webhook availability. Trusted server code sends
the D31 canonical email and verifies provider events. No account, domain, credential, or live
send is authorized merely by this documentation decision; setup occurs only in the later
approved development/configuration phase.

**Why:** A provides the fastest credible API and event path at no provider subscription cost
for hackathon volume, leaving engineering time for deterministic authorization and failure
tests rather than cloud email infrastructure.

**Trade-off accepted:** Free-plan quotas, shared sending infrastructure, provider availability,
30-day provider data retention, one-domain limit, terms, and lack of paid guarantees constrain
the system. Provider acceptance or delivery events do not prove that the carrier read, agreed
with, or is legally bound by the message.

**Cost and scope contract:**

- Baseline Resend subscription cost is USD 0/month while usage remains within 100 emails/day
  and 3,000 emails/month. Meter both limits in trusted server state and fail closed before send
  when no quota is safely available; do not auto-upgrade or incur overage.
- A sending domain is required. Domain registration/renewal, DNS administration, taxes,
  payment-card/FX charges, and staff time are not included in USD 0. If no existing approved
  domain is available, purchase and cost approval are separate decisions.
- Current paid reference is Resend Pro at USD 20/month for 50,000 emails, with paid overages
  as separately published. Volta cannot upgrade, enable overage, or attach a payment method
  without explicit human cost approval.
- Volta must retain required audit evidence independently under an approved retention policy;
  provider retention is not the authoritative audit store.

**Implementation contract:**

- Place the Resend API key and webhook secret only in approved server-side secret storage.
  Never expose them to dashboard/realtime clients, source control, logs, URLs, model context,
  error bodies, test fixtures, screenshots, or generated artifacts.
- Verify the custom sending domain and configure/review SPF, DKIM, and DMARC before live
  commitment sends. Sender/display name/reply-to are allowlisted configuration, not model input.
- Resolve recipient addresses only from a verified, versioned carrier/provider contact record
  bound to the selected pre-agreement. Caller speech, transcript, model output, free-text quote
  fields, or email body cannot directly become `To`, `CC`, `BCC`, or reply-to headers.
- Render subject/body from a versioned deterministic template and typed authorized fields;
  prevent header, HTML, URL, Unicode-confusable, and attachment injection. No attachments or
  links are permitted until separately approved.
- Enforce server-side daily/monthly quota counters with concurrency-safe reservation before
  D26 dispatch. Quota absence/ambiguity denies before provider I/O; provider usage telemetry
  is cross-checked but does not replace local evidence.
- Use one stable operation idempotency/reference where supported, durable send intent, and
  D28 at-most-one attempt. API timeout, connection loss, or ambiguous provider response becomes
  `UNKNOWN`; never blind-resend. Definite provider rejection is reason-coded failure.
- Verify webhook authenticity using Resend's current official signature procedure over the
  exact raw request. Bind event/message ID to the original operation and reject forged,
  replayed, out-of-order, cross-tenant, or contradictory events. Webhooks cannot mutate mandate.
- Model provider lifecycle precisely: request attempted, provider accepted, delivered where
  evidenced, delayed, bounced, complained, or unknown. Never label API acceptance as delivery
  or delivery as carrier agreement/legal formation.
- Minimize recipient/contact/contract data sent to the provider, disclose the processor as
  required, and approve retention/deletion/region/privacy terms before live personal data.
- Provide a non-live fake adapter for deterministic tests. Test mode cannot set production
  commitment state or be visually indistinguishable from a real send.

**Verification:** NOT RUN. Required evidence includes no/malformed/exposed keys, verified and
unverified domains, SPF/DKIM/DMARC configuration evidence, recipient/header/body injection,
wrong/cross-tenant contact, 99/100/101 daily and 2,999/3,000/3,001 monthly boundaries,
concurrent reservation, timeout/rejection/ambiguous response, duplicate sends, valid/forged/
replayed/out-of-order webhooks, lifecycle semantics, audit retention independent of provider,
test-versus-live separation, and proof that models cannot address or send email.

**Would change if:** free-plan terms, limits, deliverability, data handling, or reliability no
longer fit, or an existing approved organizational service is safer. Any provider/plan/domain
change requires cost, privacy, security, migration, and failure-semantics approval.

## D34 / Person 2 D-04I — Resend for separate recap and commitment email flows

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:37-05:00

**Context:** D31/D-04F separates non-binding call pre-agreement evidence from the later
official commitment email, and D33/D-04H selects Resend Free for commitments. The system
also needs to decide whether non-binding recap email uses the same provider, a second
provider, or no email channel.

**Alternatives considered:**

- **A — Resend for both, with strictly separate flows.** One vendor/credential and webhook
  surface, but independent message types, templates, policy permissions, states, and evidence.
- **B — SendGrid for recaps and Resend for commitments.** Preserves a parallel implementation
  proposal but adds another vendor, credential, cost/privacy surface, and failure model.
- **C — Dashboard-only recaps.** Minimizes external disclosure but removes the carrier's
  written opportunity to identify errors in the captured pre-agreement.
- **D — SendGrid for both.** Replaces the approved provider and requires new provider,
  security, privacy, and cost approval.

**Decided:** Alternative A. Resend is the only email provider in the approved baseline, but
Volta implements two structurally separate capabilities:

1. `PREAGREEMENT_RECAP` sends a clearly labeled non-binding recap of validated call evidence
   so the carrier can review/correct captured terms. It can never authorize selection,
   commitment, mandate mutation, or payment.
2. `OFFICIAL_COMMITMENT` sends only the exact deterministic commitment authorized under
   D26–D33, after autonomous policy approval or transaction-specific human escalation.

Provider reuse does not merge the flows or their state machines.

**Why:** A minimizes credentials, vendor due diligence, integration time, quota accounting,
webhook code, and monetary exposure while preserving the essential evidence-versus-authority
boundary. A single provider adapter can share transport mechanics without sharing policy
capabilities or semantic state.

**Trade-off accepted:** a Resend outage or quota failure affects both channels, creating a
shared availability dependency. Recap content still discloses negotiation information to an
external processor and recipient. Provider-level message events can be confused across flows
unless operation type and identity are strongly bound.

**Cost and quota contract:**

- Both inbound and outbound messages across both flows consume the single D33 Free allowance
  of 100 messages/day and 3,000/month; they are not separate quotas.
- Reserve quota for higher-priority `OFFICIAL_COMMITMENT` messages. Exact reservation and
  shedding rules remain a separate approval; recap traffic may never exhaust commitment quota.
- Baseline provider subscription remains USD 0/month within the combined allowance. No
  automatic upgrade, overage, second Resend account, or SendGrid fallback is permitted.
- Domain/DNS, privacy, storage, monitoring, engineering, taxes, and any later paid-plan costs
  remain as disclosed in D33.

**Implementation contract:**

- Define distinct typed commands, authorization checks, canonical templates, subject prefixes,
  sender/reply-to policy, provider tags/metadata, operation identifiers, audit event types,
  webhook transition maps, and UI badges for `PREAGREEMENT_RECAP` and `OFFICIAL_COMMITMENT`.
- A recap command accepts only validated evidence references and a verified carrier contact.
  It is labeled prominently `NON-BINDING PRE-AGREEMENT RECAP — NOT A COMMITMENT`, requests
  corrections through an approved channel, and never states booked/awarded/committed/paid.
- Recap body may use model-generated summary fields only after deterministic schema validation,
  provenance binding, output encoding, and clear attribution to evidence. Unknown/ambiguous
  material values remain visibly unknown; the model cannot invent or resolve them.
- Official commitment subject/body/material fields are rendered solely by trusted deterministic
  code from the exact D26 `PREPARED` operation. No recap/model/free-text field can flow into
  the commitment command except through separately validated typed authoritative data.
- Use separate least-privilege internal capability tokens/ports. Possession of recap-send
  capability cannot invoke commitment send, choose `commitment_mode`, mark a candidate eligible,
  or transition commitment state.
- Bind every provider request and webhook event to tenant, message type, operation/message ID,
  recipient/contact version, canonical payload digest, provider message ID, and expected state.
  Cross-type events fail closed and are audited.
- Lifecycle names remain type-qualified. `PREAGREEMENT_RECAP_PROVIDER_ACCEPTED` or delivered
  never means commitment; `OFFICIAL_COMMITMENT_PROVIDER_ACCEPTED` is still not proof of delivery,
  reading, counterparty agreement, payment, or legal formation.
- Deduplicate and apply D28 no-blind-resend independently per message operation. A failed recap
  cannot trigger an official commitment, and a commitment failure cannot be concealed by a
  successful recap event.
- Apply data minimization separately: recap includes only negotiation evidence needed for
  correction; commitment includes only approved contract terms. Do not include transcripts,
  audio, secrets, internal mandate limits, alternative bids, RT internals, or unnecessary PII.
- Tests and local adapters must make message type unmistakable and cannot create production
  lifecycle evidence. SendGrid credentials/configuration are outside the approved architecture.

**Verification:** NOT RUN. Required evidence includes compile-time/runtime capability
separation, distinct templates/subjects/tags/states, model prompt injection into recap,
unknown/ambiguous fields, verified versus attacker-controlled recipient, cross-type provider
events, quota exhaustion/reservation, provider outage, duplicate/unknown send outcomes,
non-binding wording, deterministic commitment rendering, data minimization, and proof that a
successful recap can never authorize or represent commitment or payment.

**Would change if:** one-provider concentration creates unacceptable availability/privacy risk
or recipients require a different verified channel. A second provider or dashboard-only recap
requires cost, privacy, security, routing, failover, and state-semantics approval; it cannot be
introduced as an automatic fallback.

## D35 / Person 2 D-04J — Existing team-controlled email domain or subdomain

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:38-05:00

**Context:** D33/D34 require authenticated carrier-facing email through Resend, which needs
a verified sending identity. The architecture must decide whether to reuse a team-controlled
domain, purchase a dedicated domain, rely on a provider test domain, or use personal identity.

**Alternatives considered:**

- **A — Existing team-controlled domain or delegated subdomain.** No new registration cost
  when suitable ownership exists; supports isolated DNS records and stable project ownership.
- **B — Purchase a dedicated Volta domain.** Clear isolation but adds registration/renewal,
  tax/payment, ownership, recovery, and DNS-administration decisions.
- **C — Resend testing domain.** Useful for restricted development recipients but unsuitable
  as the official carrier-facing commitment identity.
- **D — Personal email/domain.** Fast but mixes personal and project identity and weakens
  continuity, ownership, recovery, and auditability.

**Decided:** Alternative A. Use an existing domain controlled by the team or a dedicated
subdomain delegated by its authorized administrator. The exact domain is not yet known and
remains an explicit unresolved input; it must never be inferred or invented. No live recap
or commitment email is enabled until ownership and DNS control are verified and the approved
SPF, DKIM, DMARC, sender, reply-to, and recovery configuration passes review.

**Why:** A avoids unnecessary monetary cost while establishing a stable organizational
identity separable from individual accounts. A delegated subdomain can isolate Volta's
sending reputation and credentials without purchasing a new domain.

**Trade-off accepted:** Volta depends on the domain owner and DNS administrator for timely,
correct configuration and recovery. Existing-domain reputation or conflicting SPF/DMARC
policy can affect delivery. DNS changes can impact other mail systems if scoped incorrectly.

**Cost and scope contract:**

- Incremental domain-registration cost is USD 0 only if an appropriate team-controlled
  domain/subdomain already exists and its administrator approves use. Existing renewal,
  registrar, DNS-hosting, administration, monitoring, and staff costs still exist but are
  not newly incurred by Volta under this decision.
- Any domain purchase, paid DNS service, certificate, deliverability service, or registrar
  change requires a separately itemized USD cost decision. Volta cannot purchase automatically.
- Resend Free plan/domain limits remain governed by D33/D34. Domain reuse does not grant
  permission to exceed quota or add providers.

**Implementation contract:**

- Obtain the exact ASCII/IDNA-canonical domain or delegated subdomain from an authenticated
  authorized team/domain administrator. Record ownership authority, intended purpose,
  registrar/DNS provider, approver, review timestamp, and non-secret evidence.
- Prefer a dedicated subdomain when available to isolate sending reputation and DNS changes.
  Do not modify the organizational apex or existing MX/SPF/DMARC records without explicit
  administrator review and a documented impact/rollback plan.
- Configure only the DNS records issued/required for the approved Resend project, verify them
  through both provider status and independent DNS lookup, and preserve record names/types/
  non-secret values, TTLs, timestamps, and verification evidence. Never expose API credentials.
- SPF must not create multiple conflicting SPF records or exceed lookup limits. DKIM selectors
  are provider-bound and reviewed. DMARC alignment/policy/reporting must be explicitly approved
  before enforcement changes; do not weaken an existing organizational policy to make setup pass.
- Allowlist exact `From`, envelope sender where visible, display name, and `Reply-To` separately
  for recap and commitment flows. Models, callers, carriers, tenants, and request payloads cannot
  choose or override headers/domains.
- Production mode fails closed when provider domain verification, DNS evidence, approved sender,
  or alignment status is absent/failed/stale. Test-domain messages are visibly non-production
  and can never transition a real operation.
- Define administrator access with least privilege and MFA, recovery ownership, credential/
  DNS rotation, offboarding, and periodic verification before live use. Personal account loss
  must not orphan the domain or provider project.
- Monitor bounces, complaints, spoofing/alignment failures, unexpected DNS changes, and domain
  verification loss. Such events pause affected sends without changing mandate or commitment truth.

**Verification:** NOT RUN. Required evidence includes exact-domain approval, IDNA/confusable
names, delegated-subdomain isolation, existing SPF/DMARC conflict, DKIM selector validation,
independent DNS lookup, wrong/unverified/stale provider domain, sender/reply-to/header spoofing,
DNS change/rollback, administrator MFA/offboarding, test-versus-production separation, and
fail-closed behavior after verification or alignment loss.

**Would change if:** no suitable existing domain is available or its owner rejects delegation.
Then a dedicated purchase or another organizational domain requires its own ownership, USD cost,
privacy, DNS, recovery, and reputation decision; personal identity is not an automatic fallback.

## D36 / Person 2 D-04K — Verified carrier directory with controlled email onboarding

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:43-05:00

**Context:** D31–D35 require recap and official commitment emails, but a recipient extracted
from speech, transcript, quotation text, or model output can be wrong or attacker-controlled.
Volta needs a deterministic trust source that also permits onboarding a new carrier contact.

**Alternatives considered:**

- **A — Verified carrier directory with controlled onboarding.** Use an existing owner-approved
  contact; new/changed addresses require dashboard owner approval plus mailbox-control challenge.
- **B — Pre-registered addresses only.** Strong and simple but prevents new-carrier commitment
  until a separate administrative process finishes.
- **C — Mailbox challenge only.** Proves mailbox control but not authority to act for the carrier.
- **D — Address stated during the call.** Convenient but vulnerable to transcription error,
  prompt injection, misdirection, spoofing, and unauthorized disclosure.

**Decided:** Alternative A. Every recap or commitment recipient must resolve from a tenant-
scoped, versioned carrier contact record. Existing verified records are created/approved by
the authenticated mandate owner or an approved carrier-directory administrator. A proposed
new or changed email address remains `UNVERIFIED` until the owner approves its association
with the exact carrier and the mailbox successfully completes a single-use ownership challenge.
Only then may trusted code mark it eligible. The model may extract/propose an address as
untrusted evidence but cannot create, approve, challenge, verify, select, or mutate a contact.

**Why:** A prevents caller/model-controlled addressing while retaining a practical path for
new carriers. It separates two different claims: the owner vouches for carrier association;
the challenge proves control of the destination mailbox.

**Trade-off accepted:** the two-step process adds delay, email quota, delivery dependency,
administrative workload, and possible inability to commit during the initial call. It still
does not prove the contact's legal authority to bind the carrier or protect against a
compromised mailbox/domain.

**Cost and quota contract:**

- Verification messages use the single D33/D34 Resend Free quota and must be counted separately
  from recaps and commitments. They cannot consume quota reserved for official commitments.
- Baseline provider subscription remains USD 0 within combined limits. There is no automatic
  SMS/phone validation, third-party enrichment, domain-intelligence purchase, or paid fallback.
- Staff verification time, carrier coordination, bounced challenges, privacy handling, and
  directory maintenance are operational costs even when no provider fee is incurred.

**Implementation contract:**

- A carrier record has immutable ID/tenant, canonical legal/display identity, approved aliases,
  status, provenance, and version. A contact record binds canonicalized email to carrier ID,
  role/purpose, status, owner approver/evidence, mailbox-challenge evidence, timestamps,
  revocation, and version; never use email address as the carrier primary key.
- Normalize email conservatively for comparison without assuming provider-specific dot/plus
  equivalence. Preserve the exact delivery form. Reject control characters, CR/LF, comments,
  multiple addresses, display-name injection, invalid IDNA/domain syntax, and unsafe lengths.
- A model/call-extracted address creates at most a typed `CONTACT_PROPOSAL` containing source
  evidence and confidence/ambiguity; it cannot become a Resend recipient or directory record.
- Owner approval occurs only in the authenticated dashboard with canonical carrier/contact
  diff and D23–D25 fresh TOTP transaction confirmation. It binds the proposed address to one
  tenant/carrier and does not itself mark mailbox control verified.
- Mailbox challenge content is a fixed non-binding verification template. Use a cryptographically
  random, hashed-at-rest, single-purpose token bound to tenant/carrier/contact/version/address,
  issuing actor/session, issue/expiry, nonce, and unused state. Exact lifetime/attempt policy
  remains a separate approval.
- Challenge completion proves access to that mailbox only. It cannot accept a pre-agreement,
  commitment, mandate, terms, payment, or legal-authority claim and cannot modify another field.
- Atomically consume a valid challenge and record both requirements before transitioning
  `UNVERIFIED -> VERIFIED`. Wrong/expired/replayed/cross-tenant/cross-contact tokens fail closed.
- At every recap/commitment preparation and immediately before dispatch, resolve the exact
  current verified contact version server-side and recheck active carrier/contact status,
  tenant, permitted message type/role, revocation, domain/address, and selected candidate.
  Stale or changed contacts invalidate preparation.
- Never accept `To`, `CC`, `BCC`, reply-to, display name, or carrier address in the send API.
  The command carries only the verified contact ID/version; the trusted adapter resolves headers.
- Revocation is immediate for new sends and audited. It does not erase historical messages.
  Pending/unknown commitment operations using the contact are blocked and escalated.
- Minimize and protect directory PII with approved access, encryption, audit, export, retention,
  correction, and deletion rules. UI/API responses mask addresses where full disclosure is
  unnecessary; never expose cross-tenant existence through errors or challenge behavior.

**Verification:** NOT RUN. Required evidence includes existing/new/changed contacts,
owner/non-owner and mailbox-only cases, malformed/Unicode/confusable/CRLF/multi-address input,
model/caller proposals, wrong/expired/replayed/cross-tenant tokens, concurrent approval and
challenge, contact change/revocation before send, wrong message-role use, header injection,
quota reservation, enumeration resistance, PII masking, immutable history, and proof that send
commands cannot directly address email.

**Would change if:** a carrier registry, contractual onboarding process, or enterprise identity
provider supplies stronger authorization evidence. It may replace or augment the owner step only
after provenance, legal authority, privacy, cost, revocation, and failure behavior are approved;
mailbox control alone remains insufficient.

## D37 / Person 2 D-04L — Fifteen-minute single-use carrier mailbox challenge

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:45-05:00

**Context:** D36/D-04K requires mailbox-control verification but leaves token lifetime,
replacement, reuse, and issuance abuse undefined. A challenge enables a financially
consequential destination and therefore cannot remain reusable or indefinitely valid.

**Alternatives considered:**

- **A — Fifteen-minute, single-use challenge.** One active challenge per contact; replacement
  invalidates the prior token; rate limit issuance to three/contact/hour and ten/tenant/day.
- **B — One-hour challenge.** More tolerant of delivery delay but increases stolen/forwarded
  link exposure.
- **C — Twenty-four-hour challenge.** Convenient for asynchronous onboarding but too broad
  for an imminent commitment workflow.
- **D — No expiry.** Simple but unsafe against replay, mailbox compromise, forwarding, and
  forgotten onboarding links.

**Decided:** Alternative A. A challenge expires exactly 15 minutes after trusted server-side
issuance, is valid for one atomic consumption, and only the newest challenge for a specific
tenant/carrier/contact version may be active. Replacement invalidates the previous challenge.
Issuance is limited to three per contact in a rolling hour and ten per tenant in a rolling day.
Expiry or rate limit never verifies the contact or changes mandate/commitment state.

**Why:** A bounds exposure while allowing ordinary email delivery and immediate onboarding.
Single-active and single-use semantics make replay/replacement outcomes deterministic, while
issuance limits constrain email bombing, quota depletion, and enumeration.

**Trade-off accepted:** delayed email or human response may require a replacement and repeated
owner coordination. Tenant-level limits can block legitimate bulk onboarding. Distributed rate
state and concurrency add implementation work.

**Implementation contract:**

- Generate at least 128 bits of cryptographically secure random token material. Send the raw
  token only in the verification URL; store only a keyed hash/digest with key version and the
  D36 binding metadata. Never log, persist, expose, or place the raw token in model context.
- Set `expires_at = issued_at + 15 minutes` using trusted server UTC. Boundary semantics:
  `now < expires_at` may validate; `now >= expires_at` is expired. Client/email/model time is ignored.
- Before issuance, atomically reserve both rolling-window limits: maximum three issued challenges
  for the exact contact in any preceding 60 minutes and ten for the tenant in any preceding
  24 hours. Count successful provider submissions and ambiguous send attempts conservatively;
  definite pre-dispatch validation failures do not consume email quota but remain audited.
- Maintain at most one active challenge for the exact contact version. A replacement transaction
  marks every prior active challenge invalid before creating/sending the new one. Failure or
  uncertainty sending the replacement does not reactivate an older token.
- Atomically verify digest using constant-time comparison; bind tenant/carrier/contact/version/
  address/purpose; check newest/active/unused/unexpired status and both D36 owner approval and
  current contact state; then consume once and transition to verified. Concurrent/repeated use
  returns a generic invalid/used response without another state change.
- A contact/address/carrier association change or revocation invalidates all challenges immediately.
  Verification of one address/version cannot transfer to an alias or replacement.
- Challenge endpoints reveal no carrier/contact/account existence through response body, timing,
  redirect, or resend behavior. Apply network/account abuse controls in addition to the approved
  per-contact/tenant issuance limits, without using attacker-controlled headers as sole identity.
- The fixed challenge email and landing page state only that mailbox control is being verified;
  they contain no pre-agreement/commitment terms, mandate limits, alternative bids, payment request,
  transcript, or confidential operational data and cannot confirm/accept anything else.
- Preserve non-secret issuance/provider/result/expiry/replacement/consumption audit evidence and
  reason codes. Expired/invalid raw tokens must not be retained for debugging.

**Verification:** NOT RUN. Required evidence includes 14:59/15:00 boundaries, server/client clock
skew, single/concurrent/replayed use, replacement before and after provider ambiguity, old-token
invalidation, contact/address/version/revocation changes, digest/key rotation, constant-time path,
2/3/4 per-hour and 9/10/11 per-day issuance boundaries, rolling-window edges, concurrent quota
reservation, cross-tenant/contact tokens, enumeration/timing behavior, quota accounting, secret
redaction, and proof that challenge completion cannot accept terms or mutate authority.

**Would change if:** measured delivery latency or accessibility evidence shows 15 minutes is
unworkable. Any longer lifetime or higher issuance limit requires abuse/quota analysis and human
approval; no adaptive model-selected extension is permitted.

## D38 / Person 2 D-04M — Fresh TOTP for each escalated commitment approval

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:47-05:00

**Context:** D31/D-04F permits a mandate to require `HUMAN_ESCALATION`, but D25/D-03C
explicitly governs mandate writes rather than transaction-specific commitment approvals.
A stolen or unattended ordinary dashboard session must not be sufficient to send the
official commitment email.

**Alternatives considered:**

- **A — Fresh TOTP plus two-minute exact-transaction confirmation.** Reuse D25's mechanism
  and bind it to the selected candidate, evidence, recipient, mandate, and canonical email.
- **B — Ordinary authenticated dashboard approval.** Less friction but session compromise
  can create a carrier commitment.
- **C — Email approval link.** Convenient but turns email access/forwarding/replay into
  commitment authority.
- **D — Voice approval.** Violates the dashboard-only boundary and reintroduces probabilistic
  identity, transcription, and intent.

**Decided:** Alternative A. Every transaction under `commitment_mode=HUMAN_ESCALATION`
requires the current authenticated mandate owner to review the exact selected option and
canonical official email, complete a new TOTP challenge, and consume a two-minute single-use
transaction confirmation. The confirmation binds every authorization-relevant input and is
invalidated by any change. It authorizes one dispatch attempt under D26–D28; it does not alter
the mandate, permit payment, or authorize a replacement/retry.

**Why:** A gives human-escalation mode evidence of immediate second-factor participation and
exact informed intent equivalent to mandate changes, without allowing the model or email
channel to approve its own proposed action.

**Trade-off accepted:** repeated TOTP and a short review window add friction and can allow
quotes/FX evidence to expire. The owner may still approve a poor but mandate-compliant option.
TOTP is phishable and does not substitute for clear terms or secure endpoint/session controls.

**Implementation contract:**

- The approval UI is available only to the current authenticated mandate owner at AAL2 and
  starts a fresh provider-backed TOTP challenge for this exact action; prior AAL2 or a D25
  mandate-write confirmation cannot be reused.
- Before challenge, display carrier/legal identity, verified contact and role, service/scope,
  origin/destination, dates/windows, every comprehensive cost component/original currency,
  FX snapshot/rate/age/cross-check/margin, unbuffered/buffered all-in USD values, mandate cap,
  selection/tie-break evidence, competing eligible alternatives, material conditions,
  exclusions/unknowns, quote expiry, and the exact canonical email subject/body.
- Issue an opaque confirmation bound server-side to actor, Supabase session ID, tenant,
  operation/candidate/version, comparison snapshot/winner, mandate ID/version/mode, every
  quote/cost/FX/RT evidence version, verified carrier/contact/version, exact recipient/header/
  template/payload digest, policy/schema versions, TOTP challenge evidence, issue/expiry,
  nonce, and unused status.
- Use D25 boundary semantics: expires exactly two minutes after trusted server issuance;
  `now < expires_at` may be consumed, `now >= expires_at` is expired. Consume atomically with
  operation preparation/authorization so concurrent/replayed submissions cannot create another.
- Immediately before email dispatch, D26 complete mediation re-reads every bound authoritative
  value and recomputes eligibility/winner. Any change—including price, terms, quote status,
  FX freshness/divergence, mandate, recipient/contact, candidate set, selection, template/email,
  revocation, or operation state—invalidates approval and requires fresh review/TOTP.
- Approval is explicit with no preselected control, batch approval, wildcard, standing token,
  model-generated assent, silence, or voice proxy. The owner must see the complete current
  payload; truncated/hidden material terms block confirmation.
- One successful approval authorizes only the D28 single dispatch attempt. Provider timeout/
  ambiguity becomes `UNKNOWN`; approval cannot be reused to resend, switch recipient/carrier,
  change content, or create a new operation.
- Denial/expiry records reason-coded immutable evidence and sends nothing. The owner may request
  new quotations or later approve a freshly evaluated operation but cannot edit authoritative
  fields inside the approval screen.
- Audit approval presentation/version, exact payload digest, actor/session/TOTP evidence reference,
  timestamps, outcome, revalidation, dispatch attempt, and provider lifecycle without storing
  TOTP codes, tokens, or unnecessary PII.
- Email, voice, model, carrier, administrator, and recap capabilities cannot start, satisfy,
  consume, or bypass transaction approval. Payment remains out of scope.

**Verification:** NOT RUN. Required evidence includes AAL1/old-AAL2/fresh-TOTP paths,
owner/non-owner, complete/truncated UI data, two-minute boundaries, replay/concurrency, binding
substitution for every enumerated field, quote/FX/mandate/contact/candidate/template changes,
winner recomputation, denial/expiry, one dispatch then timeout/unknown, retry/switch attempts,
audit redaction, and proof that voice/model/email/admin/recap paths cannot approve.

**Would change if:** a stronger phishing-resistant factor or enterprise dual-control workflow is
approved. Any reusable approval window, batch authorization, different lifetime, or alternate
channel requires a new threat-model decision; it cannot inherit mandate-write authority silently.

## D39 / Person 2 D-04N — Explicit commitment mode per operation mandate

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:49-05:00

**Context:** D31/D-04F defines `AUTONOMOUS` and `HUMAN_ESCALATION` but does not say whether
the selection applies account-wide, inherits from earlier work, or is issued separately for
each shipment/operation. Inherited autonomous authority can unintentionally govern a later,
higher-risk operation.

**Alternatives considered:**

- **A — Explicit per-operation mandate choice.** Owner selects one mode while creating each
  operation mandate; no preselection, account default, or inheritance.
- **B — Account-wide default.** Convenient but lets an old choice silently grant authority
  to materially different future operations.
- **C — Account default with per-operation override.** Flexible but adds precedence and
  creates risk that an inherited value is overlooked.
- **D — System/model-selected mode.** Lets probabilistic risk perception determine authority
  and violates human-issued deterministic authorization.

**Decided:** Alternative A. `commitment_mode` is a required versioned field of the exact
operation mandate. The owner explicitly selects `AUTONOMOUS` or `HUMAN_ESCALATION` during
the authenticated dashboard mandate-creation flow. The UI has no selected default; submission
without an explicit selection fails. A new operation never copies the mode from an account,
template, previous operation, model suggestion, URL, browser storage, or carrier interaction.
Changing mode uses D23–D25 and invalidates/re-evaluates every unresolved candidate/operation.

**Why:** A makes delegated authority visible, scoped, and auditable for each economic task.
It prevents convenience state from silently broadening autonomy and produces a clear
Trial-by-Fire distinction between otherwise similar operations.

**Trade-off accepted:** the owner must make an additional choice for every operation and
cannot rely on a reusable default. Repeated configuration adds friction, and choosing
`AUTONOMOUS` still carries the risk of a policy-valid but undesirable commitment.

**Implementation contract:**

- Domain/schema accepts exactly the enum `AUTONOMOUS | HUMAN_ESCALATION`; null, absent,
  unknown, legacy, duplicated, case-coerced, or model-invented values fail closed. No
  application/database default may populate the field.
- Dashboard presents both modes neutrally with concise consequences and neither control
  preselected. The owner must actively select one before the canonical mandate diff and
  D23–D25 fresh-TOTP confirmation.
- Bind mode to tenant, owner, operation/mandate ID and version, canonical payload digest,
  actor/session/TOTP evidence, timestamps, and audit history. It is never a mutable call/session flag.
- Templates may leave the mode explicitly unset but cannot supply an authoritative value.
  Clone/copy/import operations clear the field and require a new selection.
- API clients must send an explicit value in the dashboard-authorized canonical payload;
  server-side policy ignores browser storage, query parameters, hidden fields, model tool
  arguments, caller/carrier claims, and account metadata as authority.
- Mode changes create a new immutable mandate version and use fresh TOTP. They invalidate
  prepared/approved authorization, ranking caches, and pending commitment approvals; every
  unresolved candidate is evaluated against the new version.
- A change to `AUTONOMOUS` cannot dispatch an already selected/prepared candidate as a side
  effect of mandate mutation. After the new version commits, selection and D26 preparation
  start afresh against current quotes, FX, contacts, quota, and policy.
- A change to `HUMAN_ESCALATION` immediately prevents autonomous preparation/dispatch and
  requires a new D38 approval for any future exact commitment. In-flight/unknown attempts
  remain governed by immutable D28 reconciliation rather than being erased.
- Audit/UI/API always display the effective per-operation mode and mandate version near
  selection and commitment state. The model may explain it but cannot recommend or manipulate
  the control during an authoritative flow unless an approved advisory design is added.

**Verification:** NOT RUN. Required evidence includes missing/null/unknown/case variants,
no UI/database default, account/template/clone/browser/query/model inheritance attempts,
each mode's path, owner/non-owner creation/change, fresh TOTP, concurrent/stale mandate
versions, autonomous-to-human and human-to-autonomous changes, cache/preparation/approval
invalidation, no dispatch during mutation, unknown in-flight operation preservation, and
clear audit/display of effective mode.

**Would change if:** enterprise customers require an approved policy template or organization-
level ceiling on autonomous use. Such inheritance must be restrictive, visibly resolved,
versioned, and separately approved; no account-level autonomy default is introduced implicitly.

## D40 / Person 2 D-04O — Reserve half of Resend Free quota for commitments

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:51-05:00

**Context:** D33/D34/D36 make official commitments, non-binding recaps, and carrier mailbox
challenges share Resend Free's current 100-message daily and 3,000-message monthly limits.
Lower-consequence traffic must not consume all capacity before an authorized commitment.

**Alternatives considered:**

- **A — Reserve half for commitments.** Protect 50 daily and 1,500 monthly messages for
  `OFFICIAL_COMMITMENT`; challenges/recaps share only the other half and cannot borrow.
- **B — Dynamic reservation from active operations.** More efficient but forecast and
  concurrency errors can leave an authorized commitment without capacity.
- **C — First-come, first-served.** Simple but allows verification/recap traffic to exhaust
  the channel required for a commitment.
- **D — Automatic paid upgrade.** Improves availability but violates explicit USD spend
  approval and could create uncontrolled recurring/overage charges.

**Decided:** Alternative A. Of the currently documented Resend Free allowance, 50 messages
per provider day and 1,500 messages per provider billing month are protected exclusively for
`OFFICIAL_COMMITMENT`. Mailbox challenges and `PREAGREEMENT_RECAP` together may consume at
most the other 50/day and 1,500/month. Commitments may use available unreserved capacity in
addition to protected capacity. Lower-priority traffic can never borrow unused protected
capacity, even near reset.

**Why:** A gives deterministic capacity guarantees and quota oracles that are easy to test
under concurrency. Wasted capacity is preferable to an authorized commitment failing because
recaps or verification messages consumed the free allowance.

**Trade-off accepted:** up to half the free allowance can remain unused, and non-binding
onboarding/recap traffic may be denied while provider capacity is technically available.
Provider counting/reset semantics and external usage can still create disagreement with local
counters; ambiguity fails closed.

**Cost and quota contract:**

- Provider subscription remains USD 0/month within the current free limits. No paid upgrade,
  overage, second account, SendGrid fallback, or message deferral past policy validity occurs
  automatically.
- Provider billing-period/day definitions, timezone, recipient counting, inbound-email counting,
  test messages, retries, and provider-side sends must be verified against current terms before
  implementation. Local counters use matching periods; uncertain semantics reserve conservatively.
- Challenges remain additionally constrained by D37. Passing a per-contact/tenant challenge
  limit does not imply shared non-commitment quota is available.

**Implementation contract:**

- Maintain concurrency-safe server-side counters/reservations for four scopes: total daily,
  total monthly, non-commitment daily, and non-commitment monthly. Partition by exact provider
  account/project and canonical provider reset periods; do not trust browser/model counters.
- Before any send attempt, atomically reserve one unit in all applicable total scopes. A challenge
  or recap must also reserve one unit in both non-commitment scopes and is denied at 50/day or
  1,500/month even if total quota remains. A commitment is eligible up to 100/day and 3,000/month.
- Boundary semantics: existing count `< limit` permits one reservation; count `>= limit` denies.
  The reservation itself increments usage atomically before provider I/O.
- Definite pre-dispatch validation/policy failures create no provider reservation. Once provider
  I/O may have occurred—including timeout/connection ambiguity—the reservation remains consumed.
  Definite provider rejection accounting follows verified provider quota semantics and cannot be
  released merely to improve availability.
- Provider callbacks, usage API, and dashboard telemetry reconcile local evidence but cannot
  create extra capacity, decrement committed reservations without proven semantics, or authorize
  sends. Local/provider disagreement pauses the affected class and escalates.
- High-priority commitment capacity does not weaken D26–D28: quota reservation is necessary but
  never sufficient authorization, and an ambiguous commitment attempt is never resent.
- Denied challenges/recaps return reason-coded safe status and do not queue across a reset without
  a new current request/evidence check. An authorized commitment denied for total quota becomes a
  visible escalation/blocked operation; it does not switch provider or claim commitment.
- Expose current safe remaining capacity and reset time to authorized operators with no tenant/
  recipient leakage. Audit reservations, type, operation/contact ID, period IDs, provider result,
  reconciliation, and reason codes without message bodies or secrets.

**Verification:** NOT RUN. Required evidence includes non-commitment counts 49/50/51 daily and
1,499/1,500/1,501 monthly, total counts 99/100/101 and 2,999/3,000/3,001, commitment use of
unreserved/protected capacity, prohibited lower-priority borrowing, simultaneous reservations,
period/timezone boundaries, provider/local disagreement, inbound/recipient/retry counting,
pre-dispatch failure versus ambiguous attempt, provider outage, challenge-limit composition,
reset with stale requests, and proof that model/caller cannot classify or alter quota type.

**Would change if:** verified usage shows this partition materially blocks legitimate work or
the provider changes its allowance. Any ratio/limit/paid tier change requires current pricing,
capacity, abuse, and USD cost approval; unused protected quota is not automatically reallocated.

## D41 / Person 2 D-04P — Explicit verbal confirmation with deterministic evidence gates

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:54-05:00

**Context:** a carrier's spoken response to Volta's recap is evidence that the non-binding
pre-agreement terms were understood, but speech recognition and model interpretation are
probabilistic. A generic "yes," silence, correction, or injected instruction must never be
promoted into confirmation or commitment.

**Alternatives considered:**

- **A — Natural verbal confirmation plus deterministic evidence gates.** The model proposes a
  constrained outcome, while trusted code verifies ordering, version binding, completeness,
  contradictions, and evidence anchors before accepting `AFFIRMED`.
- **B — Any positive-language model classification.** Conversationally easy, but vulnerable to
  unrelated assent, transcription error, corrections, and prompt injection.
- **C — Require keypad confirmation.** More deterministic at the input edge, but degrades the
  natural call flow and still does not prove which complete term set the keypress addressed.
- **D — Never accept call confirmation.** Safest against speech ambiguity, but prevents a usable
  pre-agreement workflow and moves every candidate to manual review.

**Decided:** Alternative A. The output model recaps the complete validated structured terms and
asks a direct confirmation question. The input model may only propose `AFFIRMED`, `CORRECTED`,
`REJECTED`, or `AMBIGUOUS`. Trusted server-side code alone decides whether the evidence satisfies
the selected outcome. This confirms only a non-binding pre-agreement under D31; it never creates
a mandate, selects a winner, commits, sends an official email, or handles payment.

**Why:** A preserves the requested natural conversation while keeping probabilistic components
outside the authorization boundary. Binding assent to the exact recap version prevents stale or
generic language from silently changing commercial terms.

**Trade-off accepted:** legitimate confirmations may fail closed because of interruptions, poor
audio, conflicting transcripts, or incomplete terms. The call gets at most one clarification
attempt; unresolved evidence escalates rather than being guessed.

**Implementation contract:**

- Construct the spoken recap from a validated structured candidate. Before speaking, persist its
  immutable candidate ID/version and recap digest; material fields must be complete under D9/D31.
- Bind evidence to tenant, operation, call/session ID, candidate ID/version, recap digest, recap
  and response turn IDs or audio offsets, timestamps, and model/schema versions. Neither model nor
  caller may supply or rewrite authoritative identifiers.
- A candidate can become `AFFIRMED` only when the proposed affirmation follows the complete recap
  and direct question in the same call/session, all material fields remain unchanged, and no
  corrective or contradictory content occurs after that recap.
- `CORRECTED` updates the candidate through the validated proposal path, creates a new candidate/
  recap version, and requires a new complete recap and confirmation. Earlier assent is invalid.
- `REJECTED` remains unconfirmed. `AMBIGUOUS` permits exactly one fixed, non-leading clarification
  question; a second ambiguity, no answer, interruption, or unusable evidence remains unconfirmed
  and escalates.
- Silence, politeness, an unrelated "yes," assent before the recap, low-confidence recognition,
  conflicting ASR evidence, and meta-instructions are not affirmation. Untrusted text cannot alter
  these gates or the authoritative mandate.
- Only deterministically `AFFIRMED` candidates may enter D32 eligibility/ranking. Confirmation is
  evidence, not authorization: all later selection and D31/D38 commitment gates still apply.
- Audit the proposed outcome, deterministic result, reason codes, evidence references, versions,
  clarification count, and transition without logging secrets. Audio/transcript retention,
  consent, access, and deletion policy require a separate approved decision.

**Verification:** NOT RUN. Required DUT-S cases include affirmation after the exact recap;
affirmation before recap; unrelated assent; silence; rejection; correction followed by stale
assent; corrected version with fresh assent; contradiction after assent; missing material fields;
interruption; one and two ambiguities; low-confidence/conflicting ASR; replay across candidate,
call, tenant, or recap versions; prompt-injection attempts; concurrent updates; and proof that an
affirmed pre-agreement cannot directly invoke commitment or email dispatch.

**Would change if:** validated call testing shows natural confirmation cannot meet acceptable
false-accept and false-reject bounds. Any replacement must retain exact-term/version binding and
deterministic server-side acceptance; convenience alone cannot move authority into a model.

## D42 / Person 2 D-13A — Transcript-only evidence retained for one year

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T16:59-05:00

**Context:** Volta's current call architecture produces a transcription but does not capture or
retain call audio. D41 requires auditable confirmation evidence, and the decision owner requires
the available transcript to remain reviewable for audit purposes for one year.

**Alternatives considered:**

- **A — Transcript and audit evidence for 30 days.** Reduces exposure but does not meet the
  requested audit period.
- **B — Transcript-only evidence for one year.** Preserves the evidence Volta actually has while
  avoiding a new raw-audio collection path.
- **C — Audio and transcript for one year.** Provides stronger replay evidence but contradicts
  the current no-audio architecture and materially increases privacy, storage, and access risk.
- **D — Customer-configurable retention.** Flexible but creates multiple deletion regimes and
  considerably more policy and verification work.

**Decided:** Alternative B, with an explicit architectural prohibition on audio capture or
storage. Retain each call transcript and its directly linked structured audit metadata for one
year from the end of the call, solely for audit and authorized investigation. This is not
Alternative C because no audio exists in the approved data flow.

**Why:** B supplies the exact evidence available for D41 and later dispute review without
expanding collection to a more sensitive modality. A fixed period also permits deterministic
retention and deletion tests.

**Trade-off accepted:** reviewers cannot replay the original audio or independently resolve ASR
errors. A transcript must therefore never be represented as a recording or perfect ground truth;
uncertain/conflicting transcription evidence continues to fail closed under D41.

**Implementation contract:**

- The voice pipeline must not enable call recording, persist raw audio, place audio in logs/traces,
  or introduce an audio-storage provider. Any future audio capture requires a new explicit decision.
- Store the transcript with tenant, operation, call/session, candidate/recap versions, bounded turn
  or offset references, timestamps, transcription provider/model/version where available, D41
  result/reason codes, and integrity/linkage metadata required for audit.
- Calculate expiry deterministically as one calendar year from authoritative call-end time; define
  leap-day and deletion-job timing semantics before implementation and expose overdue deletion as
  an operational failure rather than silently extending retention.
- On expiry, delete the transcript from primary storage and address replicas, exports, caches,
  traces, and backups according to an approved deletion contract. Never use expired content for
  model context, analytics, or authorization.
- Transcripts remain untrusted evidence and cannot mutate mandates or authorize commitments.
  Minimize unrelated speech and secrets in logs; do not duplicate transcript bodies into audit logs.
- This decision fixes modality and retention duration only. Notice/consent, authorized roles,
  encryption/key management, legal holds, deletion latency/backups, subject requests, and
  observability-provider handling remain separate decisions and must not be inferred here.

**Verification:** NOT RUN. Required evidence includes proof no audio artifact/provider recording
is created; exact call-to-transcript/audit linkage; one-year boundary including leap-day cases;
deletion across every approved copy; overdue-deletion alerting; tenant isolation; transcript/log
minimization; expired-evidence rejection; ASR uncertainty failing closed; and proof that transcript
content cannot alter a mandate, policy result, or commitment state.

**Would change if:** applicable legal obligations, an approved legal hold, customer contractual
requirements, or validated risk analysis require a different period. Any exception must be
explicitly authorized, scoped, auditable, and must not silently introduce audio recording.

## D43 / Person 2 D-13B — Explicit transcription notice without consent gate

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:03-05:00

**Context:** D42 retains call transcripts for one year but prohibits audio recording. The called
party must receive a clear disclosure, while the decision owner does not want the automated flow
to request or depend on affirmative consent.

**Alternatives considered:**

- **A — Notice plus affirmative consent.** Stronger proof of agreement but adds a consent gate and
  prevents the requested notice-only call flow.
- **B — Explicit notice without consent gate.** Discloses actual processing and retention without
  asking a consent question or interpreting continued participation as authorization.
- **C — Depend on external contracts or customer representations.** Less call friction but Volta
  cannot deterministically prove that the called party received the disclosure.
- **D — No notice.** Simplest flow but hides material data processing and increases privacy,
  trust, and deployment risk.

**Decided:** Alternative B. Before substantive negotiation, Volta plays a deterministic notice
that the call is being monitored and transcribed for audit purposes and that the transcript is
retained for one year. Volta does not ask for consent, classify a response as consent, or require
consent to proceed under this product policy.

**Required wording semantics:** the notice must describe transcription, not audio recording.
Because D42 prohibits capturing or storing audio, saying "this call is recorded" would be
factually false. The exact localized script may vary only if it preserves: (1) monitoring and
transcription are occurring, (2) the audit purpose, and (3) the one-year transcript retention.

**Why:** B implements the requested low-friction disclosure while keeping the system honest about
the actual data modality. Deterministic playback avoids relying on the model to remember, alter,
or omit the notice.

**Trade-off accepted:** notice without affirmative consent may be insufficient in some deployment
jurisdictions, contractual contexts, or customer policies. This architecture decision is not a
legal conclusion. Deployment remains blocked wherever verified applicable requirements demand
consent or different wording until a compliant, separately approved policy is implemented.

**Implementation contract:**

- A trusted call-state component, not either model, selects and plays the complete notice before
  substantive negotiation or use of transcript content for negotiation decisions.
- Record notice script ID/version, language, start/completion timestamps, call/session ID, and
  delivery result. Do not store a fabricated consent event or infer consent from continued speech.
- If delivery fails, is interrupted, or cannot be verified complete, do not start substantive
  automated negotiation; retry the complete notice once or end/escalate without a pre-agreement.
- Caller speech, model instructions, carrier requests, and prompt injection cannot skip, shorten,
  contradict, or mark the notice complete.
- The notice is not a mandate mutation, identity proof, pre-agreement confirmation, commitment,
  waiver, or authorization for any unrelated data use.
- Legal review must determine supported jurisdictions, languages, caller/called-party rules, and
  any contexts requiring consent before production deployment. Unsupported or unknown contexts
  fail closed rather than silently applying this notice-only baseline.

**Verification:** NOT RUN. Required evidence includes notice before substantive negotiation;
exact semantic fields in every supported localization; interruption and delivery failure; one
complete retry; model/caller attempts to skip or rewrite it; absence of consent records; no audio
recording; correct one-year wording; and proof that notice completion grants no policy authority.

**Would change if:** legal review, carrier contracts, customer policy, or supported-jurisdiction
requirements demand affirmative consent or different disclosures. Such a change must be explicit,
jurisdiction-scoped, versioned, and tested; the model cannot choose the applicable regime.

## D44 / Person 2 D-13C — Restricted and audited transcript-body access

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:08-05:00

**Context:** D42 retains transcripts for one year, creating a sensitive evidence store containing
carrier speech and potentially commercial or personal data. Ordinary authentication, possession
of an operation identifier, or model access must not be sufficient to retrieve transcript bodies.

**Alternatives considered:**

- **A — Restricted audit access.** Permit only the tenant owner or an explicitly assigned
  auditor/security role, require fresh TOTP for body access, audit every attempt, and prohibit
  bulk export by default.
- **B — Every authenticated tenant operator.** Operationally simple but exposes complete call
  content to users who may need only status or structured terms.
- **C — Platform security administrators only.** Minimizes tenant access but prevents customers
  from investigating their own negotiations without platform escalation.
- **D — Model-accessible transcripts.** Enables automation and analytics but expands prompt-
  injection, data-exfiltration, and unintended secondary-use paths.

**Decided:** Alternative A. Transcript metadata and transcript bodies are separate resources.
Only the owning tenant's authenticated owner or a user with an explicitly assigned auditor/security
role may request a body, and each body-access session requires fresh TOTP. Models, callers,
ordinary operators, carrier identities, public/support links, and generic service integrations
receive no transcript-read capability. Bulk export is disabled by default.

**Why:** A supports legitimate customer audit and incident investigation while applying least
privilege, step-up authentication, tenant isolation, and an observable access trail. It avoids
making a year of transcripts convenient context for compromised accounts or injected models.

**Trade-off accepted:** investigations require more friction and administrative role management.
Users without the required role cannot self-serve transcript bodies, even if they participated in
the operation; summarized structured terms may be provided separately under their own policy.

**Implementation contract:**

- Assign and revoke auditor/security roles only through the authoritative authenticated admin
  path. Roles are tenant-scoped, deny by default, non-self-assignable, and never inferred from
  email domain, call identity, model output, operation participation, or possession of an ID.
- Require a fresh server-verified TOTP challenge before the first transcript-body read in a
  short-lived access session. Bind the session to actor, tenant, purpose, device/session, and
  maximum expiry; the exact lifetime requires separate approval before implementation.
- Reauthorize every request server-side for tenant ownership, current role, current access session,
  transcript existence/retention state, and any legal-hold/restriction state. Object identifiers
  are never authorization.
- Default APIs and lists expose only minimized metadata and must not embed transcript snippets.
  Search indexes, browser previews, notifications, error messages, logs, traces, analytics, and
  model context must not receive transcript bodies.
- Disable bulk download/export and cross-call transcript search until separately approved. Any
  emergency platform access requires a separately defined break-glass policy; no implicit support
  or database-administrator exception is authorized here.
- Append an immutable audit event for every allowed and denied body-access attempt containing the
  actor, tenant, transcript/call reference, purpose, authentication assurance, timestamp, result,
  reason code, and request correlation—not the transcript body or authentication secret.
- Revocation, tenant removal, session expiry, transcript expiry, or authorization uncertainty
  fails closed immediately. Cached pages and downloadable artifacts must not outlive access.

**Verification:** NOT RUN. Required evidence includes owner and assigned-role access; ordinary
operator/model/caller denial; cross-tenant IDOR attempts; revoked role/session; missing/stale TOTP;
direct API and guessed-ID access; list/search/error/log/trace leakage; allowed and denied audit
events; concurrent revocation; transcript expiry; browser caching; and proof bulk export is absent.

**Would change if:** validated customer workflows require delegated reviewers or regulated export.
Any expansion must define least-privilege scope, authentication strength, export encryption,
recipient controls, expiry/revocation, auditability, and abuse limits before access is enabled.

## D45 / Person 2 D-13D — Five-minute transcript-viewing session after fresh TOTP

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:11-05:00

**Context:** D44 requires fresh TOTP before transcript-body access but left the resulting access
window unresolved. Requiring TOTP for every transcript is highly restrictive; a long reusable
window creates avoidable exposure from a hijacked or unattended authenticated browser.

**Alternatives considered:**

- **A — Five-minute same-session window.** Supports a short audit investigation while limiting
  reuse and preserving per-request authorization.
- **B — One transcript per TOTP.** Strongest transaction binding but creates significant friction
  when an authorized investigator must compare several calls.
- **C — Fifteen-minute window.** More convenient but triples the exposure period after step-up.
- **D — Thirty-minute window.** Easiest for extended review but disproportionate for sensitive
  transcript bodies and more vulnerable to unattended-session access.

**Decided:** Alternative A. A fresh, server-verified TOTP creates a non-renewable five-minute
transcript-viewing session bound to the same authenticated actor, tenant, browser/session, and
approved transcript-access purpose. Every transcript-body request during that window is still
reauthorized under D44; the window is not a bearer capability or blanket export permission.

**Why:** A balances realistic multi-call audit work with a short exposure window. Per-request
checks ensure the step-up session cannot preserve access after underlying authority changes.

**Trade-off accepted:** a legitimate investigation lasting longer than five minutes requires a
new TOTP. A user may need to reauthenticate while reading, and unsaved views must close safely.

**Implementation contract:**

- Measure five minutes using trusted server time from successful TOTP verification; use an
  absolute expiry and never extend it because of activity, reads, refreshes, or model/client input.
- Bind the access session to actor ID, tenant ID, authenticated session/device identifier, purpose,
  authentication event ID, issued time, and expiry. Store only the minimum verifier/session state;
  never log the TOTP value or reusable authentication secrets.
- Revalidate current authentication, tenant membership, D44 role, transcript ownership, retention
  status, and session binding for every body read. Client-side timers and hidden UI are not controls.
- Invalidate immediately on logout, authenticated-session revocation, TOTP-factor reset/removal,
  role revocation, tenant switch/removal, relevant security event, or transcript expiry/deletion.
- Expiry boundary is strict: trusted time earlier than expiry may proceed after all other checks;
  time equal to or later than expiry denies. Clock uncertainty or store failure fails closed.
- The session authorizes interactive transcript-body viewing only. It does not authorize bulk
  export, download, printing, API tokens, model context, cross-tenant search, mandate mutation,
  confirmation, or commitment.
- Audit issuance, each use, expiry, invalidation, and denied reuse with reason codes, excluding
  transcript bodies, TOTP values, and session secrets.

**Verification:** NOT RUN. Required evidence includes reads just before/at/after five minutes;
non-sliding expiry; browser/session, actor, tenant, and device swaps; logout and every revocation
condition; concurrent reads; server clock/store failure; guessed/replayed session identifiers;
per-request role and ownership checks; and proof the window cannot enable export or model access.

**Would change if:** usability testing shows five minutes prevents legitimate audit work and a
longer interval passes equivalent threat review. Any change requires explicit approval and must
retain fixed expiry, same-session binding, revocation, per-request authorization, and auditability.

## D46 / Person 2 D-13E — Active deletion within 24 hours and backup purge within 30 days

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:12-05:00

**Context:** D42 sets a one-year transcript retention period, but deletion from the primary table
alone would leave searchable indexes, caches, exports, replicas, traces, or backups containing
usable copies. The expiry contract needs bounded, testable deletion across the full data lifecycle.

**Alternatives considered:**

- **A — Active deletion within 24 hours plus backup purge within 30 additional days.** Provides a
  practical operational window and a finite maximum for residual backup copies.
- **B — Backup purge within seven days.** Minimizes residual retention but may require expensive
  or unsupported backup granularity and could weaken disaster recovery.
- **C — Backup purge within ninety days.** Easier for many backup regimes but materially extends
  sensitive-data exposure beyond the intended retention period.
- **D — Delete active storage only.** Simplest implementation but permits indefinite, unaudited
  copies and reappearance after restoration.

**Decided:** Alternative A. No later than 24 hours after the D42 one-year expiry, the transcript
must be inaccessible and removed from every active system. Any residual copy in immutable or
rotating backups must be purged or irreversibly expire no later than 30 additional calendar days.
An authoritative deletion tombstone prevents backup restoration from making expired content
active or readable during that residual period.

**Why:** A creates deterministic service-level boundaries for both ordinary deletion and disaster-
recovery media. Tombstones make restoration safe without pretending an immutable backup can
always delete an individual object immediately.

**Trade-off accepted:** a deleted transcript may physically remain encrypted in restricted backup
media for up to 30 days after active deletion, but it cannot be used or restored into service.
Providers unable to meet the deadline cannot hold transcript backups in the approved architecture.

**Implementation contract:**

- Calculate D42 expiry using authoritative call-end time, then enqueue deletion independently of
  model behavior or user traffic. Complete active deletion by expiry plus 24 hours.
- Active scope includes primary/replica rows, object storage, search/vector indexes, caches,
  temporary files, analytics/observability payloads, generated previews, and any approved exports.
  References required for audit may retain a non-content tombstone, never transcript text.
- Persist an integrity-protected tombstone keyed by opaque transcript identity with expiry,
  deletion initiation/completion, scope/version, reason, and backup purge deadline. It contains no
  transcript content or directly identifying speech.
- Every backup restore must apply current tombstones before restored data becomes queryable. An
  expired transcript discovered during restore is deleted/quarantined without model or operator
  access; restore does not restart retention.
- Inventory every storage copy and provider before implementation. Contractual/provider deletion
  guarantees must support the 30-day bound; absence of evidence fails closed for transcript use.
- Monitor deletion lag. At 24 hours, any active remnant is a security incident and remains access-
  denied; at 30 additional days, any backup remnant is a provider/control failure requiring
  escalation. Jobs may retry deletion but never extend either deadline silently.
- Legal holds are not implicitly authorized. A future hold requires a separate scoped decision,
  legal authority, access restrictions, expiry/review, and an auditable release process.

**Verification:** NOT RUN. Required evidence includes just-before/at/after one-year expiry;
completion before 24 hours; every enumerated active copy; cache/index invalidation; failed/retried
jobs; tombstone integrity; restore before and after expiry; no resurrection; backup purge by day
30; provider evidence; leap-day/calendar boundaries; cross-tenant isolation; and alert/escalation
without content leakage.

**Would change if:** verified infrastructure cannot meet the deadline or applicable obligations
require a shorter period. A longer period is not an implementation convenience: it requires new
explicit risk, provider, contractual, privacy, schedule, and USD cost approval.

## D47 / Person 2 D-12A — Four-level data classification with highest-class inheritance

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:15-05:00

**Context:** Volta handles public documentation, internal operations, commercial quotations,
mandates, transcript evidence, authentication material, and audit records. A uniform "private"
label cannot drive least-privilege access, logging, retention, model disclosure, or export policy.

**Alternatives considered:**

- **A — Four levels: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, and `RESTRICTED`.** Distinguishes
  ordinary commercial data from transcript, authorization, authentication, and security evidence.
- **B — Three levels: public, internal, and sensitive.** Simpler but gives quotations and highly
  sensitive authorization/transcript evidence indistinguishable controls.
- **C — Two levels: public and private.** Fastest but too coarse for deterministic enforcement.
- **D — Customer-defined classification systems.** Flexible but creates inconsistent semantics,
  configuration burden, and policy-test explosion during the hackathon.

**Decided:** Alternative A. Every stored field, event, payload, and derived artifact has a schema-
defined classification. A composite or derivative inherits the highest classification of any
source field unless a separately approved, deterministic declassification transform proves the
sensitive content was removed. Customer/model labels cannot lower authoritative classification.

**Classification baseline:**

- `PUBLIC`: material explicitly approved for unrestricted publication, such as public product
  documentation. Data is not public merely because it appears in a public-source workflow.
- `INTERNAL`: low-sensitivity team operational material not approved for public release, such as
  non-customer synthetic test coordination and ordinary internal run status.
- `CONFIDENTIAL`: tenant/account information, carrier directory records, quotations, structured
  commercial terms, routes, schedules, comprehensive costs, FX snapshots, pre-agreements,
  commitment messages, and non-public business configuration.
- `RESTRICTED`: transcript bodies; credentials, authentication factors and secrets; mandate
  authorization evidence; transaction-bound approvals/capabilities; security-sensitive audit
  evidence; deletion/access tombstones; and any raw content capable of granting, reconstructing,
  or materially attacking authority. Secrets are never intentionally stored in business records.

**Why:** A provides enough separation to minimize model, logging, support, and operator exposure
without building a customer-specific policy language. Highest-class inheritance prevents a benign
wrapper or summary label from laundering sensitive fields into a weaker channel.

**Trade-off accepted:** schemas and transformations require explicit labels and enforcement tests.
Overclassification may reduce observability or convenience, but uncertainty fails toward the
higher class until a human-approved schema decision resolves it.

**Implementation contract:**

- Maintain a versioned server-side classification registry at field/event/artifact level. Unknown,
  unlabeled, dynamically added, or conflicting fields default to `RESTRICTED` and fail closed at
  disclosure boundaries.
- Enforce classification at collection, persistence, query, API serialization, model/tool context,
  logging/tracing, analytics, notifications, export, backup, and deletion—not only in the UI.
- Models receive only the minimal allowlisted fields required for the current proposal. `RESTRICTED`
  data is excluded by default; transcript use required for live interpretation is a narrowly scoped
  processing path, not permission to retain it in model context, traces, training, or later calls.
- Logs contain opaque references and reason codes rather than confidential/restricted bodies.
  Redaction is defense-in-depth; prohibited fields must be omitted before the logging boundary.
- A derived summary remains at the highest source class unless a versioned deterministic transform
  with tests explicitly maps it lower. Model-generated summaries cannot declassify data.
- Cross-tenant access is prohibited at every class. Classification never substitutes for tenant,
  role, purpose, authentication, retention, or transaction authorization checks.
- Public release requires an explicit trusted approval transition and immutable provenance;
  repository location, URL availability, caller statements, or model output cannot mark data public.
- Audit each allowed/denied disclosure using metadata and classification reason codes without
  copying the protected content into the audit record.

**Verification:** NOT RUN. Required evidence includes each class at every disclosure boundary;
unknown-field fail-closed behavior; composites with one higher-class field; nested/renamed/encoded
fields; model/log/trace/notification/export leakage; attempted model/customer relabeling;
deterministic summary declassification; cross-tenant requests; schema-version drift; and proof that
redaction failure does not expose fields that should have been omitted before logging.

**Would change if:** validated product requirements need finer regulated-data categories or
customer policy overlays. Extensions must preserve global meanings, highest-class inheritance,
deny-by-default unknowns, deterministic enforcement, migration tests, and explicit USD/schedule
approval for materially broader compliance controls.

## D48 / Person 2 D-14A — Application-level envelope encryption with a USD 0 demo adapter

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:18-05:00

**Context:** D47 classifies transcripts and authorization evidence as `RESTRICTED`. Provider-level
encryption alone leaves plaintext visible at the database/service boundary. The decision owner
selected application-level envelope encryption but requires a free demo alternative or simulation
rather than silently activating a paid managed KMS.

**Alternatives considered:**

- **A — Provider-managed encryption and TLS only.** Lowest schedule/cost burden but database or
  provider compromise can expose plaintext restricted data.
- **B — Application-level envelope encryption behind a key-provider interface.** Separates stored
  ciphertext from key custody and supports production KMS plus a clearly restricted free demo
  adapter.
- **C — Client-side encryption.** Strong infrastructure separation but prevents required server-
  side transcription, policy, and authorized audit workflows.
- **D — Ad hoc/custom cryptography and key storage.** Avoids a service dependency but creates
  unacceptable nonce, algorithm, secret-storage, rotation, and recovery risk.

**Decided:** Alternative B. Restricted transcript content and any later explicitly enumerated
restricted payload are encrypted by the trusted application using authenticated envelope
encryption. The persistence layer stores ciphertext plus non-secret cryptographic metadata and a
wrapped data-encryption key (DEK), never the plaintext DEK. A narrow key-provider interface permits
a production managed KMS/HSM adapter and a USD 0 demo-only adapter without changing ciphertext or
policy semantics.

**Demo/cost constraint:** approved incremental monetary spend is USD 0. No cloud billing account,
paid KMS key, paid operation, HSM, managed Vault, marketplace service, automatic upgrade, or
overage is authorized. The exact free/simulated adapter remains a separate decision. It must be
prominently identified in configuration, UI/demo claims, audit evidence, and the security dossier
as non-production; production mode refuses to start with it.

**Why:** B demonstrates defense beyond database encryption while preserving a clean path to proper
production key custody. The simulation is confined to custody/orchestration: Volta must still use
standard, real authenticated encryption rather than fake or reversible demonstration cryptography.

**Trade-off accepted:** losing or corrupting the wrapping key can make retained evidence
unrecoverable, while compromise of the demo adapter can expose all ciphertext it protects. Key
availability also becomes a fail-closed runtime dependency, and application-level encryption
limits database search/indexing over protected bodies.

**Implementation contract:**

- Use a reviewed standard cryptographic library and an approved authenticated-encryption scheme;
  algorithm, nonce construction, DEK size, key hierarchy/derivation, rotation period, and library
  require a follow-on decision before implementation. Do not design a new cipher or protocol.
- Generate a fresh random DEK at the approved envelope scope. Bind ciphertext using authenticated
  associated data to tenant, record/artifact ID, schema/classification version, purpose, and key-
  provider/key version so ciphertext or wrapped-key swaps fail authentication.
- Keep plaintext and unwrapped DEKs only for the shortest processing interval, never in database,
  logs, traces, exceptions, browser storage, model-retained context, or durable job payloads; clear
  references where the runtime permits and avoid unnecessary copies.
- The database stores ciphertext, nonce/algorithm/version, wrapped DEK, key reference/version, AAD
  schema/version, and integrity-safe linkage. Metadata cannot be caller/model supplied authority.
- Decryption is a privileged server-side operation composed with D44/D45 authorization, purpose,
  tenant, retention, and audit gates. Possessing ciphertext, IDs, or a key-service token is not
  sufficient authorization.
- Key-provider credentials live only in an approved secret/identity facility, use least privilege,
  and never enter the repository, conversation, client, model context, transcript, or logs.
- Provider unavailability, authentication failure, unknown algorithm/key version, AAD mismatch,
  corruption, or configuration ambiguity fails closed without plaintext fallback or silent key
  regeneration. Recovery and rotation preserve D42/D46 retention/deletion semantics.
- Enforce environment separation. Demo ciphertext/keys and synthetic evidence cannot be promoted
  to production; the production adapter and its current USD costs require explicit approval.

**Verification:** NOT RUN. Required evidence includes ciphertext-only persistence; unique DEKs/
nonces at the approved scope; AAD tenant/record/schema/purpose swaps; wrapped-DEK/ciphertext swaps;
tampering; key-provider outage; wrong/missing/rotated key; restart/recovery; logs/traces/exceptions;
authorization composition; deletion; cross-environment promotion denial; production startup block
with demo adapter; and proof the demonstration uses real authenticated encryption.

**Would change if:** the selected production platform provides equivalent application-layer
envelope encryption and independently controlled keys with verifiable semantics. Any weakening,
new provider, algorithm, paid tier, recovery path, or scope expansion requires explicit security,
schedule, operational, and USD cost approval.

## D49 / Person 2 D-14B — Local OpenBao Transit dev server as demo key provider

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:20-05:00

**Context:** D48 requires a USD 0 demo adapter behind Volta's envelope-encryption key-provider
interface. The adapter should demonstrate an external cryptographic-service boundary without
creating a paid cloud account or misrepresenting demo key custody as production-grade security.

**Alternatives considered:**

- **A — Local OpenBao Transit in dev mode.** Demonstrates a real Transit API and versioned
  encryption keys at USD 0 provider charge, but official documentation says dev mode is insecure,
  in-memory, non-TLS by default, automatically privileged, and never suitable for production.
- **B — In-process fake KMS.** Easiest and USD 0, but keeps the wrapping key in the application
  process and demonstrates less separation.
- **C — Google Cloud KMS Autokey free allowance.** More production-shaped, but requires billing
  enrollment and can create charges outside qualifying key/operation limits.
- **D — Proper self-hosted OpenBao.** No software-provider fee on existing hardware and potentially
  production-capable, but adds TLS, storage, initialization/unseal, backup, policy, and operations
  work beyond the demo schedule.

**Decided:** Alternative A. The demo/test adapter uses a local loopback-only OpenBao Transit dev
server to wrap/unwrap D48 DEKs. It is used only with synthetic or explicitly authorized demo data,
is visibly labeled `DEMO_ONLY`, and is rejected by production/staging configuration. No OpenBao
installation or implementation is authorized by this documentation decision.

**Evidence checked:** official OpenBao Transit documentation states that Transit performs
cryptographic operations without storing submitted application data and supports versioned keys.
Official dev-server documentation warns that dev mode is insecure, in-memory, automatically
initialized/unsealed, non-TLS on loopback by default, and must never run in production:
https://openbao.org/docs/secrets/transit/ and
https://openbao.org/docs/next/concepts/dev-server/ (checked 2026-08-29).

**Why:** A makes the key-provider boundary and failure modes visible in the demo while retaining
zero provider spend. Its limitations are explicit controls and claims, not hidden assumptions.

**Trade-off accepted:** restart destroys demo key state and can make demo ciphertext permanently
unreadable. A local process compromise or leaked dev token defeats key separation. Lack of TLS is
accepted only on loopback for disposable demo/test use; no network-accessible deployment is allowed.

**Cost contract:** incremental provider/subscription/license charge approved under this decision is
USD 0. Existing-machine CPU, RAM, disk, electricity, download bandwidth, container/runtime storage,
developer setup/maintenance time, and demo-recovery time remain real non-provider costs. No hosted
OpenBao, cloud VM, domain/certificate purchase, paid support, paid KMS, billing enrollment, or
automatic fallback/upgrade is approved.

**Implementation contract:**

- Bind the dev server only to `127.0.0.1`/local process networking; never expose its port through a
  tunnel, public interface, shared LAN, hosted runner, or demo URL. Network ambiguity fails closed.
- Use a dedicated disposable Transit mount/key and least-capability application token where dev
  mode permits. Root/dev tokens, unseal material, and addresses are injected through approved local
  secret configuration and never committed, printed, captured in screenshots, logged, traced, or
  sent to a model/transcript.
- Startup requires an explicit demo/test environment plus an independent `DEMO_ONLY` acknowledgement.
  Production/staging startup, non-loopback address, persistent customer data, or non-synthetic PII
  with this adapter fails closed before accepting calls or ciphertext.
- The application still performs the real D48 envelope format and authenticated encryption using
  the later-approved algorithm/library; do not replace cryptography with encoding or a fake cipher.
- Restart/key loss produces explicit `DEMO_KEY_UNAVAILABLE` evidence and no plaintext fallback,
  silent new-key recovery, or false successful-decryption claim. Demo reset deletes disposable
  ciphertext and audit fixtures through a controlled test-data procedure.
- Pin and verify the selected OpenBao version/artifact before installation; document reproducible
  start/stop/reset steps and current security limitations. Installation remains a separately
  authorized development action.
- UI, README, security dossier, and pitch must state that local dev-mode key custody is simulated
  and unsuitable for production. Production requires a separately approved managed or hardened
  key service, deployment design, disaster recovery, and complete USD cost review.

**Verification:** NOT RUN. Required evidence includes loopback-only binding; production/staging
startup rejection; missing acknowledgement; token/log/trace/repository scan; real Transit wrap/
unwrap; ciphertext/AAD tampering; server unavailable; restart/key loss; accidental new-key creation;
non-synthetic data rejection; version pinning; controlled cleanup; and no plaintext fallback.

**Would change if:** a verified, guaranteed-zero-charge managed KMS becomes available without
billing/overage exposure and fits the schedule, or the team approves the costs and operations of a
production-grade provider. Dev mode can never be promoted merely by changing an environment flag.

## D50 / Person 2 D-11A — Order lookup followed by verified-directory callback

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T17:22-05:00

**Context:** inbound callers may report delays or request changes concerning an existing order.
An order number locates an operation but may appear in email, paperwork, forwarded messages, or a
breach; knowledge of it does not prove that the caller controls the authorized carrier channel.

**Alternatives considered:**

- **A — Order number plus verified callback.** Use the number only to locate the operation, then
  initiate a new call to the carrier phone number in the D36 verified directory before disclosure
  or operation-specific action.
- **B — Order number plus inbound caller-ID match.** Faster and avoids another call, but caller ID
  can be spoofed and routing/forwarding can make it unreliable evidence.
- **C — Order number alone.** Lowest friction and cost but authenticates knowledge, not identity.
- **D — Order number plus verified-mailbox challenge.** Strong channel control but adds latency and
  consumes D37/D40 non-commitment email capacity.

**Decided:** Alternative A. The inbound caller may provide an order number solely as an untrusted
lookup proposal. Trusted code resolves it without disclosing whether protected details match, then
starts a new outbound callback to the currently verified carrier phone contact associated with the
operation. Only the verified callback session may enter the authenticated inbound-service flow.

**Why:** A separates an easily shared identifier from proof of carrier-channel control and defeats
an attacker who knows a valid order number but does not control the verified directory number.

**Trade-off accepted:** every legitimate inbound event incurs delay and an additional outbound
telephony leg. A carrier temporarily unable to receive the callback must escalate rather than
receive protected details or modify the operation through the inbound call.

**Cost contract:** callback duration, destination/country rates, origination number, carrier fees,
taxes/surcharges, recording/transcription/Realtime usage, retries, failed/answered calls, and any
provider minimums are operating costs that must be counted in the current USD cost baseline before
live use. This decision does not approve a provider, paid tier, unlimited retries, automatic credit
purchase, or spend beyond the explicit team budget. If budget/quota is unavailable, escalate.

**Implementation contract:**

- Accept an order number as typed untrusted input with strict format/length/rate limits. Use
  constant-shape responses and do not reveal existence, tenant, carrier, route, status, price,
  contact, or other protected data on the inbound leg.
- Resolve tenant/operation/carrier and the current verified callback number entirely from trusted
  state. Caller-supplied numbers, caller ID, speech, model output, transcript content, prior contact,
  or an order record's free text cannot select or replace the callback destination.
- Before dialing, revalidate operation state/version, carrier-directory record/version/status,
  callback purpose, tenant policy, jurisdiction/support status, notice policy, budget/quota, abuse
  limits, and absence of an active conflicting callback. Fail closed on ambiguity or stale data.
- Create a short-lived, single-use callback challenge bound to tenant, operation/version, carrier,
  verified contact/version, inbound call/session, purpose, and expiry. The exact expiry, attempt
  limits, and answered-party confirmation require follow-on approval.
- End the inbound call or place it in a non-sensitive terminal state before callback; never bridge,
  transfer, or preserve inbound authorization. A returned callback is a new session.
- On the callback, complete D43 notice before substantive processing. Successful connection alone
  does not authorize changes, commitments, mandate mutation, or disclosure beyond the minimum
  needed for the separately approved inbound workflow.
- Timeout, busy/no-answer, wrong person, voicemail, forwarding ambiguity, number change, provider
  error, or challenge mismatch remains unauthenticated and escalates. Do not fall back to caller ID,
  order-number knowledge, email supplied during the call, or model judgment.
- Use concurrency-safe attempt accounting and one active challenge per operation/carrier purpose.
  Audit inbound lookup, redacted resolution, callback authorization/attempt/result, channel/contact
  versions, costs, and reason codes without transcript bodies or full phone numbers.

**Verification:** NOT RUN. Required evidence includes valid/invalid/guessed/enumerated order IDs;
constant-shape responses; caller-ID spoof; caller-supplied callback number; stale/revoked/changed
directory contact; cross-tenant IDs; concurrent callbacks; budget/quota denial; busy/no-answer/
voicemail/forwarding/wrong person; provider timeout; replay; prompt injection; and proof the inbound
leg cannot read protected details or cause any operation mutation.

**Would change if:** carriers adopt a stronger mutually authenticated inbound channel or validated
operations show callback latency is unacceptable. Any replacement must authenticate channel
control independently of the order number and receive separate security, cost, and test approval.

## D51 / Person 2 D-11B — Five-minute, one-attempt verified callback challenge

**Status:** APPROVED under the decision owner's blanket approval of recommended architecture

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** D50 left callback lifetime, retry count, and answered-party proof unresolved.

**Alternatives considered:** A: five minutes, one attempt, and repeat the same order number on the
callback; B: ten minutes/two attempts; C: fifteen minutes/three attempts; D: unbounded. A minimizes
replay, nuisance calls, and cost; B/C improve availability at increasing attack/cost surface; D is
not deterministic or cost-bounded.

**Decided:** A. Create one single-use challenge expiring five minutes after trusted creation time;
dial the D36 verified number once. After D43 notice, the answering party must independently provide
the same canonical order number. Do not speak it first. Busy, voicemail, no answer, mismatch,
ambiguity, forwarding uncertainty, expiry, or provider ambiguity leaves identity unverified and
escalates. Attempts are atomically claimed before dialing and possibly dispatched calls consume the
attempt and applicable USD budget. Verification authenticates the carrier channel for this one
operation/purpose/session only and grants no mandate or commitment authority.

**Verification:** NOT RUN. Test time boundaries, one atomic attempt under concurrency, replay,
wrong/partial/spoken-first order IDs, voicemail/forwarding, provider timeout, contact-version swap,
cost accounting, and zero protected disclosure before success.

## D52 / Person 2 D-05A — Immediate revalidation plus opaque one-use execution claim

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** D26 requires a short-lived execution capability but did not choose direct revalidation
versus a signed bearer artifact.

**Alternatives considered:** A: re-run deterministic policy and atomically claim a server-side
operation row; B: HMAC bearer token; C: Ed25519 capability; D: reuse the earlier policy decision.
A has the smallest key/replay surface inside the current single backend; B/C help service separation
but add cryptographic credentials and bearer replay risk; D permits stale authorization.

**Decided:** A. Immediately before the sole side-effect adapter call, trusted server code re-reads
and revalidates the exact current mandate/state/evidence, then atomically transitions the prepared
operation into a one-use claimed state in the authoritative database. The adapter accepts only an
opaque server-side claim reference over an internal typed call, not a caller/model/browser-visible
token. No HMAC/Ed25519 authorization token is added for the hackathon. D27 expiry and D28 unknown-
outcome rules still apply. Database/claim failure denies; it never falls back to the old decision.

**Verification:** NOT RUN. Test stale state between prepare/execute, claim races, duplicate/replay,
guessed IDs, adapter invocation without a live claim, crash boundaries, and zero second side effect.

## D53 / Person 2 D-04Q — Three proposal-only model tools and no generic connectivity

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** the model-facing capability surface must implement the proposer boundary physically.

**Alternatives considered:** A: three narrow proposal tools; B: one generic action tool; C: direct
business mutation tools guarded by prompts; D: remote MCP/HTTP/SQL access. A is least-privilege and
testable; B creates ambiguous unions; C/D create excessive agency and bypass paths.

**Decided:** expose only `propose_terms`, `propose_confirmation_evidence`, and
`request_escalation`. `propose_terms` covers quote/counteroffer/correction proposals only;
`propose_confirmation_evidence` is limited to D41's four values; escalation records a typed reason
and evidence references but cannot choose an approver or alter state. Trusted orchestration injects
a minimized, immutable `SessionPolicyView`; the model gets no mandate-read tool. Every schema is
versioned, bounded, rejects unknown fields, normalizes before policy, and produces zero side effects
on error. No commit/email/telephony/mandate/auth/admin, filesystem, shell, arbitrary HTTP/SQL, remote
MCP, dynamic tool discovery, or tool-generated credential reaches either model. Tool availability is
static per session and `parallel_tool_calls` is disabled.

**Verification:** NOT RUN. Enumerate the actual session tool list; fuzz fields/types/sizes/encoding;
attempt hidden/direct tools and MCP; swap authoritative IDs; run parallel/replay calls; prove every
model path terminates at proposal/evidence/escalation and cannot reach a side-effect adapter.

## D54 / Person 2 D-09A — One targeted clarification, then deterministic escalation

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** unlimited clarification loops increase cost and let ambiguity drift into guessed terms.

**Alternatives considered:** A: one targeted clarification for each material ambiguity, maximum two
clarification turns per proposal version; B: model decides when to stop; C: immediate escalation for
all ambiguity; D: fixed three retries. A preserves recoverable calls with deterministic bounds; B is
unbounded/probabilistic; C over-escalates; D repeats questions without considering material fields.

**Decided:** A. `CLARIFY` is allowed only for a specifically identified, recoverable missing or
ambiguous material field. Ask a fixed, non-leading question, once for that ambiguity and at most two
clarification turns across the proposal version. A correction creates a new version but does not
reset a call-level maximum of four total clarification turns. Repeated ambiguity, contradiction,
identity/authority conflict, unsupported condition, policy/provider uncertainty, or exhausted limit
becomes `ESCALATE`; explicit hard violations become `DENY`; neither can be conversationally bargained
into `ALLOW`. D41's stricter one-confirmation clarification remains controlling.

**Verification:** NOT RUN. Test every outcome boundary, per-field/version/call counters, correction
loops, multilingual/noisy answers, contradictions, technical failure, and unchanged side-effect count.

## D55 / Person 2 D-10A — Neutral injection handling with repeat-attack escalation

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** injection can change model behavior even though D1 prevents it from changing authority.

**Alternatives considered:** A: ignore role/meta-instructions, continue safe business processing,
then escalate repeated attacks; B: argue/refuse at length; C: end on the first suspicious phrase;
D: use a classifier as authorization. A minimizes disclosure and denial-of-service; B leaks behavior;
C is easy to weaponize; D makes a probabilistic detector authoritative.

**Decided:** treat all caller/retrieved/model text as data. Never reveal or paraphrase hidden prompts,
tools, credentials, policy internals, or detection rules. Process independently valid business terms
through D53 while ignoring claimed roles/overrides. Give at most one neutral reminder that Volta can
operate only under the current mandate. A second material injection attempt in the call, or any
attempt to obtain secrets/privileged execution, triggers reason-coded escalation/end without a side
effect. Detection is telemetry only; missing a detection cannot expand authority. Logs omit attack
bodies and retain only bounded category/reason/evidence references.

**Verification:** NOT RUN. Run direct/indirect, multilingual, padded, encoded, fake-tool/JSON,
system-role, secret-exfiltration, and mixed valid-term attacks; metamorphically prove policy invariance.

## D56 / Person 2 D-14C — AES-256-GCM per-artifact envelopes and 90-day KEK rotation

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** D48/D49 selected envelope encryption but left algorithm, scope, nonce, and rotation open.

**Alternatives considered:** A: AES-256-GCM with a fresh DEK per restricted artifact and 90-day KEK
rotation; B: one tenant DEK; C: ChaCha20-Poly1305; D: custom/deterministic encryption. A has broad
reviewed-library/provider support and smallest compromise scope; B enlarges blast radius; C is sound
but adds no demonstrated platform benefit; D risks nonce/plaintext-confirmation failures.

**Decided:** use a vetted library's AES-256-GCM with a cryptographically random 256-bit DEK and
96-bit nonce per restricted artifact; nonce reuse under a DEK is forbidden. Bind D48 AAD exactly and
store its canonical version. OpenBao Transit wraps DEKs under a versioned AES-256-GCM KEK; use
separate keys per environment and opaque tenant-derived context where supported. Production KEKs
rotate at least every 90 days and immediately after suspected compromise; demo keys are disposable
per run. New writes use the newest version; old wrapped DEKs are rewrapped asynchronously, while key
versions remain decryptable until every dependent artifact and D46 backup remnant expires. Key
destruction requires dependency proof and two-person production approval. No plaintext search index.

**Verification:** NOT RUN. Known-answer/library round trips, random nonce/DEK uniqueness, tampering,
AAD/ciphertext/key swaps, rotation/rewrap races, old-version retirement, loss/recovery, and leak scans.

## D57 / Person 2 D-15A — Local allowlisted observability; vendor tracing disabled

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** traces help debugging but can replicate transcripts, PII, prompts, tool arguments, and
secrets into additional systems with different retention.

**Alternatives considered:** A: local structured metadata only, OpenAI tracing off, no Langfuse;
B: OpenAI Traces; C: self-hosted Langfuse; D: hosted Langfuse/full payloads. A minimizes vendors,
cost, and leakage; B/C add value but another sensitive copy; D is incompatible with minimization.

**Decided:** set Realtime `tracing` to null and add no Langfuse. Emit server-side allowlisted events
containing opaque tenant/call/operation/proposal IDs, versions, state transition, policy outcome/reason,
latencies, retry/idempotency counters, token/audio usage, provider result class, and USD cost—never
speech/transcript bodies, email/phone bodies, prompts, tool raw arguments, secrets, auth material, or
encryption plaintext. Operational events expire after 30 days; security/authorization audit metadata
needed to explain a commitment is retained one year, separate from transcript bodies. Aggregated
non-identifying cost/reliability metrics may remain one year. OpenAI's default API abuse-monitoring
retention (currently documented as up to 30 days) is an external processor fact, not Volta tracing or
zero retention; ZDR eligibility is not assumed.

**Verification:** NOT RUN. Schema allowlist/property tests, canary secrets/PII, error/exception paths,
provider payloads, trace-off config, 30-day/one-year deletion, access controls, and manual log review.

## D58 / Person 2 D-16A — Cost-controlled GPT-Realtime-2.1 baseline

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** model/version/reasoning settings affect speech quality, latency, cost, and tool behavior.

**Alternatives considered:** A: GPT-Realtime-2.1 for bounded integration/demo calls and model-free
deterministic development; B: use 2.1 for every test; C: use 2.1 Mini everywhere; D: floating legacy
model. A tests the final behavior without uncontrolled spend; B wastes paid audio; C may reduce demo
quality; D creates drift/deprecation risk.

**Decided:** configure exact model ID `gpt-realtime-2.1`, reasoning effort `low`, audio output, static
D53 tools, `tool_choice=auto`, `parallel_tool_calls=false`, vendor tracing off, and a bounded output-
token limit initially 512. Treat lack of Structured Outputs as authoritative: strict server schemas
remain mandatory. Deterministic DUT-S and fixture replays make no API call; only explicitly budgeted
integration, Trial-by-Fire, and final demo runs use 2.1. Current official listed prices checked
2026-08-29 are USD 4/M text input, USD 24/M text output, USD 32/M audio input, and USD 64/M audio
output tokens; usage and cached-input semantics must be measured from provider evidence. No auto-
upgrade, fallback model, reasoning increase, or spend/credit purchase. Version/config changes require
the regression suite and manual live-call inspection.

**Verification:** NOT RUN. Verify session-created configuration, actual tool list, no structured-output
assumption, cost counters, max-output behavior, interruption/silence/alphanumeric cases, and no fallback.

## D59 / Person 2 D-17A — Deterministic suite plus local Promptfoo red team

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** security evidence needs both exact authorization oracles and adversarial conversation tests.

**Alternatives considered:** A: pytest/Hypothesis/state-machine tests plus pinned local Promptfoo;
B: manual attacks only; C: Promptfoo only; D: add garak and PyRIT now. A balances breadth and schedule;
B is irreproducible; C cannot prove deterministic invariants; D expands setup/supply-chain scope.

**Decided:** DUT-S uses pytest, Hypothesis, metamorphic and stateful tests as the release authority.
DUT-C uses a pinned, locally executed Promptfoo configuration against mocks first and a separately
budgeted small 2.1 run; disable hosted sharing/telemetry and store only sanitized fixtures/results.
Garak/PyRIT are deferred unless all critical gates are green before H12 and installation is separately
reviewed. Dependency hashes/locks and licenses must be recorded; no package installation occurs in
this architecture session. A stochastic pass can never override a deterministic failure.

**Verification:** NOT RUN. Pin/install review, offline mock run, hostile corpus coverage, sanitized
artifacts, deterministic reproducibility, bounded paid cases, and manual inspection of every side effect.

## D60 / Person 2 D-18A — Evidence-based milestone and release gates

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** “looks good” and invented percentages cannot determine whether a security-critical demo ships.

**Alternatives considered:** A: exact invariant gates plus observed evidence; B: aggregate pass rate;
C: manual judgment; D: ship with known critical failures. A makes failures actionable; B can hide one
catastrophic case; C is inconsistent; D violates the safety claim.

**Decided:** preserve H4/H7/H10/H14/H20/H21 gates from the Person 2 plan. Every critical deterministic
test must pass; required integration/live tests must be actually run; no known P0/P1 may remain at
scope freeze or submission. P0 includes authorization/mandate bypass, duplicate commitment, secret
exposure, cross-tenant restricted-data access, or false committed state. P1 includes exploitable
identity bypass, stale authorization, material PII leakage, unbounded spend/side effects, or failure
to fail closed. P0/P1 cannot be “accepted”; reduce scope or block release. Unrun evidence is `NOT RUN`,
flaky is failure, and a model success percentage is supplemental only. Manual/visual/live-phone review
is mandatory when tools, policy/mutation, crypto, tracing, model configuration, state machine, or P0/P1
fixes change and at clean-room submission review.

**Verification:** NOT RUN. The gate itself is verified by CI required checks, immutable run manifests,
failure injection, fresh-clone rehearsal, and signed-off manual checklists with no fabricated results.

## D61 / Person 2 D-19A — PR-only governance with secret and dependency gates

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** the public repository and four parallel developers create merge, credential, and supply-
chain risk. Current partner branches are intentionally not merged into this Person 2 branch.

**Alternatives considered:** A: protected main, PRs, scoped ownership/checks, secret scanning; B:
trusted direct pushes; C: one shared branch; D: long-lived isolated branches. A gives review/evidence;
B/C bypass controls; D creates late conflict and stale security assumptions.

**Decided:** no direct or force push to main; all changes use scoped branches/PRs. Require green lint,
types, tests, layering, secret scan, dependency review where available, and current changelog/decision
log for shared contracts. Require Person 2 review for `policy/`, `tools/`, auth/identity, commitment
adapters, security migrations/config, and security docs; repository owner retains merge authority.
Enable GitHub secret scanning/push protection and protected-branch required checks if available at no
unapproved cost; otherwise run a pinned local/CI secret scanner and document the platform gap. Never
bypass a real secret: revoke/rotate first, remove it safely, investigate exposure, and add regression.
Use GitHub CLI/OS credential storage, built-in least-privilege `GITHUB_TOKEN`, pinned actions/dependencies,
lockfiles, and minimal workflow permissions. No merge is authorized by this ADR.

**Verification:** NOT RUN. Inspect branch settings/permissions, required checks/CODEOWNERS, deliberate
fake-secret block, workflow permissions/pins, dependency lock integrity, PR review, and clean clone.

## D62 / Person 2 D-00A — Predevelopment remains documentation-only until official rules are verified

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** the supplied PDFs are exports of prior analysis/chat, not authoritative organizer terms.
They describe the challenge but do not establish binding pre-event coding, eligibility, reuse, credit,
or submission rules.

**Alternatives considered:** A: continue architecture/docs but block product implementation until
official rules are obtained; B: assume prebuilding is allowed; C: stop all documentation; D: hide
predevelopment. A preserves progress and integrity; B risks disqualification; C is unnecessary;
D is deceptive.

**Decided:** this session and branch remain documentation/read-only architecture work. Before product
code, dependency installation, live service configuration, or reuse of prior implementation, obtain
and archive/link current official organizer rules and record: start-time/prebuild allowance, permitted
assets/open source/AI, team/ownership, required disclosures, judging/submission, data/call consent,
sponsor credits, and public-repo requirements. Ambiguity is escalated to organizers in writing. Keep
authorship/provenance and disclose prior scaffolds. No retrospective claim that the supplied chat PDFs
are official rules. If rules prohibit this work, quarantine it and rebuild only what is permitted.

**Verification:** supplied PDFs inspected; official rule evidence **NOT AVAILABLE**. Development gate
remains BLOCKED until a human records the official source and resolution.

## D63 / Person 2 D-20A — Narrow, evidence-qualified final security claims

**Status:** APPROVED under blanket approval

**Approved at:** 2026-08-29T17:29:41-05:00

**Context:** the jury must understand what architecture and observed tests prove without interpreting
a design, model guardrail, or simulated component as a production guarantee.

**Alternatives considered:** A: narrow claims tied to run evidence and explicit limitations; B:
absolute “secure/prompt-injection-proof/compliant” claims; C: avoid security claims; D: quote only test
pass percentages. A is truthful and differentiating; B is false; C hides the product's core; D omits
coverage and residual risk.

**Decided:** claim only that Volta *architecturally separates* probabilistic proposals from a
deterministic reference monitor, and—only after observed evidence—that tested forbidden proposals
produced zero consequential side effects in the enumerated suite. State that prompt injection can
still alter conversation, transcripts are probabilistic, callback proves control of a registered
channel rather than a natural person's identity, email commitment/legal enforceability depends on
external contracts/law, notice-only transcription needs jurisdictional review, OpenAI may retain API
content under applicable data controls, OpenBao dev mode is simulated/non-production, provider and
network failures remain, and payment is outside scope. Never claim “hack-proof,” “zero risk,” “legal
compliance,” “zero retention,” “zero cost,” “perfect transcription,” or “all tests passed” without the
corresponding verified evidence. Demo labels distinguish SIMULATED, LIVE, NOT RUN, UNKNOWN, and
COMMITTED; manual/live-phone inspection and residual risks appear in the dossier.

**Verification:** NOT RUN. Final claim review compares every slide/README/demo label to immutable test,
provider, cost, and manual evidence; unsupported language blocks submission until removed or proven.

## D64 / Person 2 D-00B — Development authorized on the rebased Person 2 branch

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T18:09:00-05:00

**Context:** D62 paused implementation pending broader organizer rules. After rebasing current main,
the owner explicitly instructed Codex to accept the integrated changes and implement the security and
tool layer on `docs/approve-d01-reference-monitor`.

**Alternatives considered:** A: retain the D62 hold; B: implement only deterministic, testable
security/tool code on the Person 2 branch while keeping live external effects disabled; C: implement
and exercise live calls/email immediately; D: write directly to main. A does not follow the new human
instruction; C creates monetary and real-world side effects without configured evidence; D violates
the PR workflow. B advances the authorized work without spending money or contacting third parties.

**Decided:** Alternative B. This explicit authorization supersedes D62's implementation hold for
local and branch development. It does not authorize direct changes to main, real calls, real email,
payments, secret exposure, or claims that unexecuted live tests passed.

**Verification:** OBSERVED for local implementation checks recorded in the accompanying changelog;
live-provider, live-phone, persistence, and manual/visual evidence remain NOT RUN.

## D65 / Person 2 D-16B — Preserve the integrated cascade and apply the kernel around it

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T18:09:00-05:00

**Context:** rebased main contains the working STT → LLM → TTS cascade and the partners' composed
multilingual negotiation personality, while earlier Person 2 D58 described a Realtime implementation.

**Alternatives considered:** A: preserve the cascade and make each model/tool output an untrusted
proposal; B: discard it for Realtime; C: maintain both stacks. A retains working team code and one
test surface; B adds rewrite and merge risk; C doubles vendor, cost, and security surfaces.

**Decided:** Alternative A. D65 supersedes D58's Realtime-specific implementation selection. The
security contract is transport-independent: the cascade proposes typed data, deterministic policy
authorizes, and only a separate server-side capability can claim an exact prepared payload once.
The partners' voice personality remains, with authority wording corrected to describe phone results
as non-binding pre-agreements and official email as a later policy-mediated commitment attempt.

**Verification:** OBSERVED through unit, layering, prompt-contract, replay, strict-type, lint, and
full local test execution. Live voice behavior and real provider effects remain NOT RUN.

## D66 / Person 2 D-16C — Measured low-latency cascade without moving authorization

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T18:57:00-05:00

**Context:** the owner requested sentence-level measurement and optimization for real-time speech
while the deterministic kernel remains the only authority. The prior simulator reported audio
duration but could not distinguish endpointing, model, TTS, or first-audio delay.

**Alternatives considered:** A: measure only total call time; B: replace the cascade with a new
speech stack; C: instrument every latency boundary and optimize prompt/chunk/model settings inside
the existing cascade; D: use a second model as a safety checker. A is not diagnostic; B adds rewrite
risk; D adds probabilistic latency without authority. C preserves team work and measures bottlenecks.

**Decided:** Alternative C. Use monotonic per-turn timestamps for STT endpoint delay, first model
chunk, TTS-to-first-frame, end-to-end first audio, response completion, and barge-in clear. Every
sample carries an evidence label (`SIMULATED`, `SIMULATED_TRANSPORT_LIVE_LLM`, or `LIVE_PSTN`). Keep
the canonical long personality prompt as documentation and compile a security-equivalent runtime
prompt under half its size, with stable rules before dynamic operation data. Use the configured
model's minimal supported reasoning, 300 output tokens, and shorter clause chunks. Authorization,
ranking, commitment preparation, and single-use claim remain deterministic and unchanged.

**Observed evidence:** one live-LLM/fake-STT/fake-TTS turn produced first model chunk at 1,153.6 ms,
first audio at 1,154.1 ms, and completed at 1,456.1 ms. This single sample meets the provisional
1.5-second median target but cannot establish a median, p95, network, STT, TTS, or PSTN claim. A
separate attempted 160-token/low-effort profile failed closed with `response.incomplete`; an
unsupported `none` effort for the configured `gpt-5-mini` also failed closed. Both were rejected.

**Verification:** automated latency/chunk/prompt tests plus full local verification are required.
At least 20 live turns and real PSTN/STT/TTS measurement remain NOT RUN; report median, nearest-rank
p95, maximum, interruption cases, and provider/model configuration before tuning thresholds further.

## D67 / Person 2 D-16D — Precompiled trusted facts for common spoken answers

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T19:05:00-05:00

**Context:** the first duration-budget run correctly flagged a 23-word, approximately 9.2-second
answer. The model copied a verbose authoritative pickup range even after receiving an 18-word target.

**Alternatives considered:** A: relax the duration target; B: truncate generated text after a word
limit; C: ask a second model to shorten it; D: compile exact trusted facts into short canonical spoken
phrases only when a strict grammar matches. A hides poor interaction; B can delete material terms; C
adds latency and probabilistic drift. D preserves exact values without giving the model authority.

**Decided:** Alternative D. Normalize only an exact full-match Spanish date-range grammar into a
short canonical phrase and expose it as a trusted fast fact in the runtime prompt. Unmatched or
ambiguous values are never rewritten or inferred. Ordinary turns are measured against 18 words and
an approximate six-second budget; overages are warned, not truncated. Exact safety/commitment recaps
remain exempt when completeness requires more words.

**Observed evidence:** one live-LLM/fake-transport turn emitted first audio at 953.7 ms, completed at
1,299.2 ms, and spoke 10 words with an estimated 4.0-second duration: “Del 2 al 4 de septiembre de
2026. ¿Tiene chasis?” This is SIMULATED_TRANSPORT_LIVE_LLM evidence, not PSTN/TTS proof.

**Verification:** strict full-match/no-match tests, prompt invariants, duration-budget tests, and the
complete local suite are required. Other languages/date grammars and 20+ real PSTN turns remain NOT RUN.

## D68 / Person 2 D-16E — English policy-mediated conversational demo

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T19:16:00-05:00

**Context:** the owner requested an English conversational demo in which the existing personality
remains useful while caller statements cannot override the deterministic mandate. Before this
decision, the model could converse but the session supplied no policy-mediated tools.

**Alternatives considered:** A: rely on the security prompt; B: put policy imports directly in the
voice layer; C: mediate explicit structured conversational facts through `voice → tools → policy`
and filter acceptance claims; D: claim complete natural-language enforcement before implementing
typed extraction for every quote field. A leaves authorization probabilistic; B violates the import
DAG; D would be a false assurance. C adds a deterministic denial path without moving authority into
the model and preserves the existing architecture.

**Decided:** Alternative C. The demo company, call scenarios, greeting, dates, and generated speech
are English. An explicit numeric USD amount is converted into a typed proposal and evaluated by the
kernel before the model runs. A non-ALLOW result produces a fixed English denial and team escalation.
Generated acceptance or commitment claims are replaced with a fixed non-binding statement. This
adapter may deny but never authorize a commitment; caller claims such as “your boss approved it” do
not modify the mandate.

**Limits and residual risk:** enforcement currently recognizes explicit numeric USD expressions and
a conservative set of acceptance phrases. It does not yet provide comprehensive extraction of
spoken number words, foreign-currency quotes, all-in component completeness, dates, equipment,
identity, or every paraphrase. The live model remains intelligent conversationally but untrusted.
No actual carrier booking, email, persistence, provider telephony, or human handoff is connected.

**Observed evidence:** lint and strict typing passed; all 55 local tests passed, including layering
and hostile conversation tests. A live-model/fake-STT/fake-TTS English sample answered the pickup
question coherently in nine words with first audio at 1,460.9 ms. A local hostile scenario bypassed
the model and rejected both a USD 10,500 offer and “your boss already approved” against a USD 9,000
demo cap. These are simulated-transport observations, not PSTN evidence.

**Verification:** comprehensive typed conversational extraction, foreign-exchange evidence,
persistence, actual escalation routing, live PSTN/STT/TTS, and manual phone inspection remain NOT RUN.

## D69 / Person 2 D-16F — Grammar-bound typed quote extraction and output containment

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T19:31:00-05:00

**Context:** after D68 proved a narrow explicit-USD denial path, the owner authorized implementation
for spoken-number amounts, foreign currencies, itemized components, pickup date, equipment, carrier
identity, validity, and creative acceptance/commitment paraphrases.

**Alternatives considered:** A: ask the model to interpret and authorize all fields; B: use an
unbounded semantic classifier as the enforcement boundary; C: compile explicit English grammars into
a per-call typed draft, clarify missing/ambiguous facts, bind identity from trusted session metadata,
and send only complete proposals to deterministic policy; D: silently default missing fields from the
demo operation. A and B remain probabilistic; D violates the no-inference invariant. C preserves
natural conversation outside security-sensitive turns while keeping authorization deterministic.

**Decided:** Alternative C. English number words through millions, digit amounts, explicit USD/MXN/
EUR/CAD/GBP names or codes, named cost components, exact month-day-year pickup/validity, bounded
relative validity, and allowlisted equipment aliases populate append-only per-call drafts. Bare
“dollars”, “pesos”, numberless currencies, short forms such as “eight five”, and missing quote fields
clarify rather than infer. Conflicting component restatements escalate instead of overwrite. Carrier
IDs and contact IDs come only from trusted session configuration; contradictory spoken company claims
escalate. Non-USD proposals require an immutable injected FX snapshot no older than policy permits and
the human-approved mandate margin. Complete eligible results remain non-binding pre-agreements.

Generated output is screened for a conservative family of binding speech acts including accept,
agree, confirm, commit, book, award, approve, “lock it in”, “you have the load”, “consider it booked”,
“move forward”, and equivalent configured forms. Matches are replaced by a fixed non-binding response.

**Accepted limitation:** no finite phrase grammar can prove containment of every creative semantic
paraphrase. This control prevents the tested families but is defense-in-depth; consequential state
changes remain protected by typed policy evaluation and the separate one-use commitment claim. The
demo has no live FX fetcher or verified identity adapter, so FX evidence is dependency-injected and
identity is pre-bound session data. Unsupported languages/forms fail to clarification only when they
match a security-sensitive grammar; full multilingual extraction remains NOT RUN.

**Observed evidence:** formatting, lint, strict typing, import-layer tests, all 71 local tests, and
three full fake-transport scenarios passed. Spoken USD 10,500 was denied in 9.3 ms first-audio
simulated time; two-turn USD 7,000 linehaul plus USD 500 fuel became only a non-binding pre-agreement;
MXN without approved FX evidence escalated. These are SIMULATED observations, not PSTN evidence.

**Verification:** real STT variants, accents/noise, live immutable FX ingestion, verified-directory
identity binding, persistence, warm transfer, property/fuzz testing, and live PSTN/manual inspection
remain NOT RUN.

## D70 / Person 2 D-00C — Integrate security into current main's live evidence and handoff path

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T19:47:00-05:00

**Context:** PR #6 became conflict-blocked after main added persisted bidirectional transcript
evidence, recap/brief generation, recap delivery, Supabase contracts, deterministic handoff tooling,
and stricter VAD settings. The owner instructed Person 2 to integrate against the logic currently in
main rather than preserve obsolete branch implementations.

**Alternatives considered:** A: keep the branch unchanged and leave the PR unmergeable; B: select the
Person 2 versions wholesale and discard main's new live path; C: select main wholesale and discard
the deterministic kernel; D: use main's current live composition as the base and layer Person 2
mediation, observability, and tests into the same session. A blocks delivery; B deletes partner work;
C removes the security boundary. D preserves both systems at their intended trust boundaries.

**Decided:** Alternative D. Main's evidence callbacks, transcript persistence, recap flow, handoff
detector/callback, VAD defaults, domain/port exports, configuration, migrations, and tests are
authoritative. The current VoiceSession additionally retains latency telemetry and routes every
security-sensitive turn through the conversation guard before model output. Both policy and handoff
tool exports coexist without widening the import DAG. Production handoff prompts and fallback speech
are English; multilingual hostile fixtures remain valid input tests.

**Conflict policy:** both changelog histories are retained and timestamp ordered; both ugly-case
families are retained and uniquely numbered. No existing migration was edited. Conflicting shared
exports and settings were combined rather than choosing one team's version.

**Verification:** full post-merge formatting, lint, strict typing, architecture, unit, integration,
telephony, persistence, notification, handoff, conversation, and hostile suites are required before
push. Real PSTN, live Supabase migration application, real SendGrid delivery, and manual phone
inspection remain NOT RUN.

## D71 / Person 2 D-05B — Recap ranking is analysis-only until policy claim integration

**Status:** APPROVED

**Approved by:** Person 2 / human decision owner

**Approved at:** 2026-08-29T19:50:00-05:00

**Context:** main advanced during D70 with `award_from_recaps.py`. Its default dry-run scopes calls
to one RFQ and creates an explainable ranking, but `--commit` trusted model-extracted recap fields,
created manual FX snapshots, wrote offers/VERBAL commitments, accepted a force-incomplete override,
and `--sms` contacted the selected carrier without the approved typed policy/one-use claim gates.

**Alternatives considered:** A: accept the script because it does not write `COMMITTED`; B: delete
the partner workflow; C: immediately map an undocumented deployed database schema into the full
policy coordinator; D: preserve analysis/draft behavior and deterministically block every mutation,
notification, and incomplete-award flag pending an explicit typed adapter. A violates D26-D31 and
AGENTS invariants because VERBAL state and carrier SMS are consequential; B discards useful partner
work; C would guess schema/evidence semantics. D keeps the demo analysis while failing closed.

**Decided:** Alternative D. Model extraction and weighted ranking may produce analysis artifacts and
non-binding English drafts only. `--commit`, `--sms`, and `--force-incomplete` return explicit
errors before database or network actions. The internal write helper independently rejects
`commit=True` so argument-parser bypass cannot restore the side effect. Re-enabling requires typed
`QuoteProposal` construction from auditable evidence, immutable approved FX snapshots, current
`Mandate` evaluation, deterministic selection, exact recap evidence, selected commitment mode,
immediate revalidation, and an opaque one-use claim consumed by the allowlisted adapter.

**Verification:** static quality checks, full suite, direct CLI-gate tests, and internal-helper bypass
tests are required. Deployed advanced-schema inspection, real FX ingestion, database writes, SMS,
official commitment email, and live carrier effects remain NOT RUN.
