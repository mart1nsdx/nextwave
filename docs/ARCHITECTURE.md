# Architecture — why the folders are the way they are

Read this before adding a directory, moving code between packages, or widening `ALLOWED`
in `backend/tests/test_layering.py`. `AGENTS.md` states the rules; this file states the
reasoning behind them, so that a rule can be applied — or challenged — on its merits.

---

## 1. The one idea

> **Speech is probabilistic. Authority is deterministic.**

A voice agent's input is a stranger improvising on a phone line. Some of what it hears is
true, some is mistaken, and some is an attempt to talk the agent past its limits. A system
that treats that stream as instructions will eventually book a truck it was never
authorized to book.

So Volta splits along trust. The LLM *proposes*; a deterministic policy engine — plain
Python, no model in the loop — *decides*. Everything below follows from that split, and
the directory tree is the split made physical.

## 2. The rule for whether a directory exists

> A directory exists only if it has **a distinct reason to change** *and* **a distinct
> trust level**. Two candidates that always change together at the same trust level are
> one directory, not two.

The second half is what makes this tree different from a generic FastAPI app. Conventional
layouts group by *technical kind* — `models/`, `services/`, `utils/`. That grouping puts
the code that parses a counterparty's sentence in the same package as the code that
authorizes a payment, because both are "services". Here they are as far apart as the
import graph allows.

## 3. The packages

All paths under `backend/app/`.

| Package | Distinct reason to change | Trust level |
| --- | --- | --- |
| `domain/` | The vocabulary of the business changes (a Quote grows a field) | N/A — inert types |
| `config/`¹ | A deployment variable appears | N/A — inert |
| `policy/` | The rules of authority change | **Trusted.** Sole authority |
| `repo/` | The persistence backend changes | Trusted — obeys, doesn't decide |
| `ledger/` | What counts as evidence changes | Trusted — append-only |
| `notify/` | Non-binding recap or official commitment email changes | Trusted — obeys |
| `agent/` | The agent negotiates better/differently | **Untrusted.** Prompts are content |
| `market/` | Multi-carrier strategy changes | Trusted — but must ask `policy` |
| `tools/` | The model gets a new capability | **The boundary.** Widest blast radius |
| `voice/` | A speech vendor changes, or we swap one out | Untrusted — carries model output |
| `telephony/` | Twilio changes, or the PSTN misbehaves | Untrusted — carries stranger audio |

¹ `config.py` is a module, not a package, but it is a layer for import purposes.

Two splits that are worth defending explicitly, because they look mergeable:

- **`voice/` vs `telephony/`.** Both are "voice". They are two different vendor surfaces
  with two different failure modes: Twilio drops audio frames and redelivers webhooks; the
  speech vendors change model ids and session semantics. Merging them means one directory
  that breaks for two unrelated reasons, owned by two different people, on a 24-hour clock.
  The seam is `voice/frames.py`: the pipeline consumes mu-law frames through a Protocol and
  never learns that Twilio exists — which is also what lets it be tested with no PSTN leg.
- **`agent/` vs `policy/`.** Both concern "what the agent should do". But prompts are
  *content the counterparty can influence*, and policy is *authority they cannot*. Merging
  them is precisely the mistake that lets "your boss approved 10,500" become a real
  authorization. The separation is the product.

## 4. The dependency graph

The contract lives in `backend/tests/test_layering.py` as data:

```
telephony ─► voice ─► tools ─► market ─► ledger ─► repo ─► domain
               │       │        │                          ▲
               ▼       ▼        ▼                          │
             agent   notify   policy ─────────────────────►┘
```

**The graph flows one way: from the adapters that hear the counterparty, down toward
deterministic authority.** `policy/` sits at the bottom and imports nothing but types.

That direction is the whole design. Because `policy/` cannot import `voice/`, it
cannot call a model. Because it cannot import `telephony/` or `httpx`, it cannot reach
the network. Because it cannot import `agent/`, no prompt text can reach it. The
invariant "the LLM never writes a commitment" is therefore not a rule someone has to
remember at 4am — it is a property of the import graph, checked on every test run.

How each edge earns its place:

| Invariant (AGENTS.md) | The structure that enforces it |
| --- | --- |
| #1 The LLM never writes a commitment | `policy/` is a sink; `tools/` is the only place a proposal meets `policy.evaluate()` |
| #2 The mandate is immutable from inside the call | Mandate lives in `domain/`, is evaluated in `policy/`; neither is reachable from `agent/` or `voice/` |
| #3 Calls are non-binding; one authorized email attempts commitment | `policy` selects and revalidates; `notify` may dispatch only one claimed canonical payload; `ledger` preserves outcome/uncertainty |
| #4 Never overwrite silently | `ledger/` is append-only by construction, not by convention |
| #5 RFQ and AWARD are separate phases | `market/` owns phase state; `tools/` cannot award without going through it |
| #6 Fail closed | `policy/` is synchronous and total — it always returns a decision, and the default is deny |
| #7 Handlers are idempotent | Idempotency keys live in `ledger/`, which every mutating path already touches |
| #8 Never infer numbers or dates | Extraction is in `agent/` (untrusted, may return "incomplete"); validation is in `policy/` |

Three tests keep this honest:

- `test_imports_respect_layering` — every `app.*` import is checked against `ALLOWED`,
  absolute and relative forms both.
- `test_every_package_declares_its_contract` — a new directory under `app/` fails the
  build until someone declares what it may import. Adding a package becomes a deliberate
  act rather than a side effect of needing somewhere to put a file.
- `test_layering_map_is_acyclic` — a cycle would mean two packages are really one, and
  the split is decorative.

## 5. Traceability — every required capability has an owner

From `docs/CHALLENGE.md` §3. If a folder can't be traced to a row here, it shouldn't exist.

| Required capability | Owning packages |
| --- | --- |
| Real outbound PSTN calls | `telephony/` |
| Inbound calls understood and acted on in real time | `telephony/` → `voice/` → `tools/` |
| Negotiate rate and window inside a mandate | `agent/` proposes, `policy/` authorizes |
| ≥3 carriers in parallel, quotes played against each other | `market/` |
| Auditable comparison of why the winner won | `market/` + `ledger/`, surfaced in `dashboard/` |
| Pre-agreements, selection, and commitments remain distinct | `policy/` + `market/` state machines and `ledger/` |
| Separate recap and official commitment email flows | `notify/`; only a claimed/revalidated operation may dispatch the latter |
| Every affirmation links to transcript evidence | `ledger/` (turn/time references); no call audio is captured or stored |
| Call brief: actions taken and things mentioned | `ledger/` |
| Conversation and system stay consistent | `tools/` is the only path between them, in both directions |
| Escalate mid-call without hanging up | `telephony/` (warm transfer) + `notify/` (context handoff) |
| Barge-in | `telephony/` (`clear`) + `voice/` (local VAD, turn handling) |
| Mandate cannot be moved by the counterparty | `policy/`, unreachable from anything that hears audio |

## 6. What we deliberately did not build

Naming the rejected options matters as much as the tree itself: a structure is only
justified if the alternatives were considered and lost on the merits.

| Rejected | Why |
| --- | --- |
| `services/`, `utils/`, `common/`, `core/` | Grouping by technical kind, not by trust. `utils/` in particular becomes the drawer where a policy helper eventually lands next to a string formatter — exactly the mixing this design exists to prevent. Nothing goes in a folder because it fits nowhere else. |
| A top-level `models/` | Same problem one level up. `domain/` holds types because they are *shared vocabulary*, not because they are "models"; behaviour lives with the layer that owns the decision. |
| An abstraction layer over the LLM provider | We have one provider and 24 hours. A swap layer written before a second provider exists encodes guesses about what varies. `voice/` is already the seam if we ever need it. Note this does *not* apply to STT/TTS, where the Protocols exist because we genuinely expect to swap vendors mid-hackathon on latency and accuracy. |
| A generic negotiation framework | Manzanillo→Guadalajara done well beats a framework done badly. Generality is the expensive kind of technical skill — impressive to build, hard to defend when it has one caller. |
| A multi-agent supervisor | A second model supervising the first adds a probabilistic check on top of a probabilistic system. Our safety check is an `if` statement, on purpose. |
| RAG / a vector DB | Nothing in the flow needs semantic retrieval. The mandate is a small struct; carriers are a list. |
| A repo-wide `src/` layout | The split that matters is `backend/` vs `dashboard/` — two runtimes, two languages, two package managers. A shared `src/` would imply a shared build there isn't. |
| A shared types package between backend and dashboard | Real value at scale, but it needs a codegen step and a build order. The dashboard reads five JSON shapes. Not worth the tooling on this clock. |

## 7. Where does my new code go?

Ask, in order:

1. **Does it decide whether something is allowed?** → `policy/`. If you were about to put
   that decision in a prompt or a tool handler, stop; this is the mistake the architecture
   exists to prevent.
2. **Is it a type shared by two or more packages?** → `domain/`.
3. **Does it talk to a vendor?** → `telephony/` (Twilio), `voice/` (speech: STT, LLM, TTS),
   `notify/` (SMS/email), `repo/` (Supabase). One vendor surface per package; inside
   `voice/` each provider is one module behind a Protocol.
4. **Does it record what happened?** → `ledger/`.
5. **Is it a new capability for the model?** → `tools/`, and say so in the PR. Adding a
   tool widens what a stranger on the phone can reach.
6. **Is it multi-carrier strategy?** → `market/`.
7. **Is it wording?** → `agent/`.
8. **None of the above?** That is a signal, not a gap. Say so in the PR before creating a
   package — `test_every_package_declares_its_contract` will stop you anyway.

## 8. Glossary

**Drayage** — the truck leg from port to warehouse. **Carrier / dispatcher** — the
trucking company and the human answering its phone. **Mandate** — the human's prior
authorization (price cap, window, allowed actions). **Commitment** — an authorized,
evidenced obligation. **Barge-in** — caller interrupts mid-sentence; the agent stops
talking and listens. **Escalation** — handing a live call to a human without hanging up.
**RFQ** — the quote-gathering phase, which creates no obligation. **Award** — the single
call that closes with the winner.

## 9. Approved Person 2 baseline

The concise, decision-complete security architecture, operational lifecycle, data/crypto rules,
tool surface, provider constraints, delivery schedule, and external blockers are in
`docs/PERSON2_ARCHITECTURE_BASELINE.md`. If older scaffold language conflicts with an approved
decision, the newest non-superseded entry in `docs/DECISION_LOG.md` controls.
