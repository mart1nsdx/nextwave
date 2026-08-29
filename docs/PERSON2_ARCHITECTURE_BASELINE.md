# Volta Person 2 architecture baseline

**Status:** architecture decision-complete as of D63; implementation and verification are not started.

This is the short handoff. `docs/DECISION_LOG.md` remains authoritative for alternatives, rationale,
trade-offs, costs, and verification. Conflicts resolve in favor of the newest approved, non-superseded
decision. Tests not actually executed are `NOT RUN`.

## Decision-register closure

| Original area | Approved decisions | Result |
| --- | --- | --- |
| D-00 competition/predevelopment | D62 | Documentation may continue; implementation blocked pending official rules |
| D-01 enforcement architecture | D1 | Deterministic reference monitor is the authorization root |
| D-02 mandate semantics | D7-D22 | Comprehensive all-in USD, controlled FX and advisory RT baseline |
| D-03 mandate mutation/authentication | D23-D25 | Dashboard-only, email OTP enrollment, fresh TOTP per write |
| D-04 model/tool and commitment surface | D26-D41, D53 | Proposal-only models; calls pre-agree; one email attempts commitment |
| D-05 side-effect authorization | D26-D28, D52 | Immediate revalidation plus opaque one-use database claim |
| D-06 commitment state machine | D26-D31 | Prepared/claimed/committed/denied/expired/unknown with no blind retry |
| D-07 market/award semantics | D31-D32 | Parallel non-binding candidates, one deterministic winner |
| D-08 objective/tie breakers | D32 | Lowest eligible buffered all-in USD; deterministic tie handling |
| D-09 clarify/escalate | D41, D54 | Bounded precise clarification; otherwise deny/escalate |
| D-10 injection response | D1, D55 | Neutral containment; repeat attack escalates; detector non-authoritative |
| D-11 inbound identity | D36-D37, D50-D51 | Order lookup plus single verified-directory callback challenge |
| D-12 classification/minimization | D47 | Four levels, highest-class inheritance, restricted-by-default |
| D-13 transcript retention/access | D42-D46 | No audio; one-year transcript; restricted access; bounded deletion |
| D-14 crypto/key management | D48-D49, D56 | Envelope encryption; demo OpenBao; AES-256-GCM and rotation |
| D-15 observability/redaction | D57 | Local allowlist, vendor tracing off, bounded metadata retention |
| D-16 Realtime model/config | D58 | Cost-controlled GPT-Realtime-2.1 configuration |
| D-17 red-team toolchain | D59 | Deterministic suite plus pinned local Promptfoo |
| D-18 acceptance criteria | D60 | Exact evidence gates; no known P0/P1 |
| D-19 repository governance | D2-D6, D61 | PR-only, protected checks, secret/dependency gates |
| D-20 final claims | D63 | Narrow evidence-qualified claims and explicit limitations |

## Trust flow

```text
caller / provider / transcript
          |
          v
untrusted input model -- typed proposal --> deterministic security kernel
                                              | DENY / CLARIFY / ESCALATE
                                              | ALLOW + current-state claim
                                              v
untrusted output model <-- safe response -- deterministic security kernel
                                              |
                                              v
                                  one allowlisted side-effect adapter
```

The models propose interpretation and language. They never hold authority. Every consequential state
change is revalidated against authoritative current mandate/state, atomically claimed once, and sent
through one adapter. Failure or ambiguity cannot degrade into permission.

## Operational lifecycle

1. An authenticated human creates an explicit per-operation USD mandate with no autonomy default.
2. Volta calls carriers for non-binding quotations/pre-agreements. It discloses monitoring and
   transcription; no audio recording is created.
3. The model proposes structured terms. The kernel validates comprehensive all-in USD cost, FX
   evidence/margin, windows, conditions, identity, versions, and state.
4. Volta recaps the exact candidate. Carrier speech is proposed as affirmed/corrected/rejected/
   ambiguous; trusted evidence gates accept only exact-version affirmation.
5. Only eligible affirmed candidates enter deterministic ranking. Lowest buffered all-in USD wins;
   none eligible escalates for a human mandate decision.
6. In `AUTONOMOUS`, current mandate may authorize the exact winner. In `HUMAN_ESCALATION`, fresh TOTP
   and a two-minute transaction-bound approval are mandatory.
7. Immediate policy revalidation and one atomic database claim authorize one official commitment
   email to the verified carrier mailbox. The call itself is never binding; payment is never handled.
8. Ambiguous external outcomes become `UNKNOWN`, block retry/conflicting action, and reconcile.
9. Transcript-only evidence is envelope-encrypted, role/TOTP restricted, retained one year, removed
   from active systems within 24 hours of expiry, and purged from backups within 30 additional days.

## Model capability boundary

Only three model tools exist: `propose_terms`, `propose_confirmation_evidence`, and
`request_escalation`. There is no commit, email, telephony, mandate mutation/read, authentication,
admin, arbitrary HTTP/SQL/shell/filesystem, remote MCP, or dynamic tool-discovery capability. A trusted
controller supplies a minimized immutable session policy view.

## Data and cryptography

- Classes: `PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`; composites inherit the highest class and
  unknown fields default to `RESTRICTED`.
- Transcript bodies and authorization/authentication security evidence are `RESTRICTED`.
- AES-256-GCM, fresh random 256-bit DEK and 96-bit nonce per restricted artifact, exact AAD binding,
  and wrapped-DEK storage. Production KEK rotation: at most 90 days plus immediate compromise response.
- Demo custody: loopback-only OpenBao Transit dev mode, USD 0 provider charge, synthetic/authorized
  demo data, visibly non-production, and rejected by staging/production.
- Transcript access: tenant owner or explicit auditor/security role, fresh TOTP, fixed five-minute
  same-session viewing window, per-read reauthorization, audited attempts, no bulk export/model access.

## Identity and external channels

- Carrier email contacts come from the verified directory and mailbox challenge flow.
- An inbound order number locates an operation but authenticates nobody. Volta makes one callback
  within five minutes to the verified directory number; the answerer must independently repeat the
  order number. Failure escalates without protected disclosure.
- Twilio webhook and WSS handshake signatures must be verified using the official SDK and exact
  external URL/raw body semantics. HTTPS/WSS is mandatory; no signature bypass in live environments.
- Resend recap and official commitment flows remain separate. Half of documented free quota is
  protected for official commitments; ambiguous commitment sends are never automatically repeated.

## Conversation safety

- One precise clarification per material ambiguity, maximum two per proposal version and four per
  call; exhausted or systemic uncertainty escalates. Explicit hard violations deny.
- Ignore role changes, overrides, fake tool output, and secret requests. Give at most one neutral
  mandate reminder; a second material injection attempt escalates/ends. Detectors are telemetry only.
- Never claim success until trusted backend evidence confirms the exact state.

## Runtime and observability

- Final bounded integration/demo model: `gpt-realtime-2.1`, low reasoning, static tools,
  `tool_choice=auto`, no parallel tool calls, initial 512 output-token limit, tracing off.
- Deterministic development/tests make no model or PSTN calls. Paid calls are explicitly budgeted.
- No Langfuse. Local structured allowlist only; no transcript/prompt/tool body/secret/auth data in
  logs. Operational metadata: 30 days. Security/authorization evidence: one year.
- Do not claim Zero Data Retention. Current provider data-control behavior and account eligibility
  must be verified before each live environment.

## Delivery gates and schedule

| Window | Required outcome | Exit gate |
| --- | --- | --- |
| Pre-H0 | official rules, costs, secrets, interfaces | implementation remains blocked without rules |
| H0-H2 | domain types, normalizer, pure policy, boundary/property tests | cap/smallest-unit/stale mandate never bypass |
| H2-H4 | state machine, immediate revalidation, one-use claim, exact tools | no mutation path bypass; H4 critical suite green |
| H4-H7 | mock then real Realtime/Twilio integration | live over-cap blocked; valid proposal path observed |
| H7-H10 | three RFQs, affirmation, ranking, one commitment | no double winner/commit under races; scope cut if P0/P1 |
| H10-H14 | inbound verified callback, renegotiation, Promptfoo | identity/changes fail closed; critical regression green |
| H14-H16 | encryption, deletion, redaction, provider review | no secrets/restricted data in logs; demo limits visible |
| H16-H20 | Trial-by-Fire, manual/live review, P0/P1 fixes only | no known P0/P1; evidence dossier current |
| H20-H22 | full suite, fresh clone, secret/dependency scan | reproducible public repo; exact claims supported |
| H22-H24 | demo/pitch rehearsal and rest | no new architecture; labels and limitations correct |

## Required evidence before submission

- All critical DUT-S unit, boundary, property, metamorphic, stateful, replay, concurrency, IDOR,
  redaction, crypto, deletion, and cost tests pass.
- Required integration and live-phone cases are actually run and manually inspected.
- No known P0/P1. Reduce scope or block; never weaken a critical oracle.
- Fresh-clone install/test, secret scan, dependency/lock review, and public-file inspection succeed.
- Every claim maps to evidence. Prompt injection resistance means authorization containment, not that
  conversation cannot be manipulated.

## Unresolved external inputs (not architecture choices)

- Official NextWave organizer rules and written resolution of predevelopment/reuse ambiguity.
- Exact existing team-controlled email domain/subdomain and verified DNS ownership.
- Actual provider accounts, quotas, billing balances, supported countries/numbers, and current prices.
- Deployment jurisdictions and legal review for notice-only transcription and commitment wording.
- Final partner-branch integration state. This Person 2 branch intentionally contains no partner merge.

## Primary-source review

Checked 2026-08-29; re-open before implementation because provider interfaces, prices, retention,
and limits can change.

- [OpenAI Realtime API reference](https://platform.openai.com/docs/api-reference/realtime): tool
  choice, static tool configuration, output-token limits, parallel calls, and tracing controls.
- [OpenAI GPT-Realtime-2.1](https://developers.openai.com/api/docs/models/gpt-realtime-2.1): current
  function calling, lack of Structured Outputs, reasoning support, rate limits, and USD token prices.
- [OpenAI API data controls](https://platform.openai.com/docs/models/default-usage-policies-by-endpoint):
  default abuse-monitoring retention and account-dependent ZDR/MAM eligibility.
- [Twilio webhook security](https://www.twilio.com/docs/usage/webhooks/webhooks-security) and
  [Media Streams](https://www.twilio.com/docs/voice/media-streams): HTTPS/WSS, official signature
  validation, exact URL/body handling, raw live-audio transport, and stream constraints.
- [NIST SP 800-207](https://csrc.nist.gov/pubs/sp/800/207/final) and
  [NIST SSDF SP 800-218](https://csrc.nist.gov/Projects/ssdf/publications): per-resource policy
  enforcement/zero implicit trust and evidence-based secure development practices.
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/):
  prompt-injection and excessive-agency threat framing; deterministic mediation remains Volta's control.
- [GitHub push protection](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/prevent-future-leaks/enable-push-protection)
  and [credential guidance](https://docs.github.com/en/rest/authentication/keeping-your-api-credentials-secure):
  secret blocking, least privilege, short-lived/scoped credentials, and secure stores.
- [OpenBao Transit](https://openbao.org/docs/secrets/transit/) and
  [OpenBao dev mode](https://openbao.org/docs/next/concepts/dev-server/): cryptographic-service
  behavior and the explicit prohibition on treating dev mode as production.
