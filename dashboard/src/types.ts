export type Attention = 'needs_attention' | 'working' | 'executing'
export type RfqPhase = 'ready' | 'open' | 'awarding' | 'closed'

export interface OperationSummary {
  id: string
  reference: string
  client_name: string
  container_number: string
  route: string
  stage: string
  attention: Attention
  days_remaining: number | null
  next_action: string
  source_freshness: string
  source_is_demo: boolean
}

export interface SourceSignal {
  label: string
  source: string
  status: string
  occurred_at: string
  is_demo: boolean
}

export interface TimelineEvent {
  label: string
  status: 'complete' | 'current' | 'pending'
  source: string
  occurred_at: string | null
  is_current: boolean
  is_demo: boolean
}

export interface ReadinessCheck {
  label: string
  status: string
  detail: string
  is_ready: boolean
  source: string
}

export interface MandateSummary {
  version: number
  cap_amount_minor: number
  currency: string
  pickup_window: string
  status: string
  authorized_actions: string[]
}

export interface CarrierCandidate {
  id: string
  name: string
  reliability_percent: number
  is_vetted: boolean
  rationale: string
}

export interface OfferComparison {
  id: string
  carrier_id: string
  carrier_name: string
  freight_amount_minor: number
  expected_total_amount_minor: number
  currency: string
  pickup_window: string
  reliability_percent: number
  status: string
  rationale: string
  is_recommended: boolean
  evidence_call_id: string | null
}

export interface RfqSummary {
  id: string
  phase: RfqPhase
  carrier_ids: string[]
  offers: OfferComparison[]
}

export interface CommitmentSummary {
  state: string
  carrier_name: string | null
  recap_status: string | null
  evidence_available: boolean
}

export interface Assignment {
  carrier_name: string
  driver_name: string
  driver_phone: string
  vehicle_plate: string
  carta_porte_status: string
  evidence_call_id: string | null
}

export interface ConnectedAgent {
  name: string
  role: string
  relationship: string
  status: string
  is_demo: boolean
}

export interface OperationWorkspace {
  id: string
  reference: string
  client_name: string
  container_number: string
  bill_of_lading: string
  cargo_description: string
  weight_kg: number
  route: string
  ocean_carrier: string
  last_free_day: string | null
  days_remaining: number | null
  stage: string
  attention: Attention
  next_action: string
  signals: SourceSignal[]
  timeline: TimelineEvent[]
  readiness: ReadinessCheck[]
  mandate: MandateSummary
  carrier_candidates: CarrierCandidate[]
  rfq: RfqSummary
  commitment: CommitmentSummary
  assignment: Assignment | null
  connected_agents: ConnectedAgent[]
  escalations: string[]
  is_demo: boolean
}

export interface CallSummary {
  id: string
  operation_id: string
  carrier_name: string
  direction: string
  status: string
  started_at: string
  duration_seconds: number
  summary: string
  has_evidence: boolean
  is_demo: boolean
}

export interface TranscriptLine {
  offset_ms: number
  speaker: string
  text: string
  is_relevant: boolean
}

export interface PolicyDecisionSummary {
  verdict: string
  reason_code: string
  decided_at: string
}

export interface CallEvidence {
  call: CallSummary
  call_brief: string[]
  transcript: TranscriptLine[]
  policy_decisions: PolicyDecisionSummary[]
  recap_status: string
  evidence: {
    recording_id: string
    audio_offset_ms: number
    transcript_event_id: string
    audio_url: string | null
  } | null
  is_demo: boolean
}

export interface CommandResult {
  operation_id: string
  rfq_id: string
  outcome: string
  message: string
  phase: RfqPhase
  is_demo: boolean
}

export interface BotConfiguration {
  agent_name: string
  agent_role: string
  primary_language: string
  fallback_language: string
  recap_channel: string
}

export interface OperationConfiguration {
  operation_id: string
  bot: BotConfiguration
  mandate: {
    mandate_id: string
    version: number
    owner_id: string
    operation_id: string
    max_all_in_usd: string
    pickup_not_before: string
    pickup_not_after: string
    allowed_equipment: string[]
    commitment_mode: 'autonomous' | 'human_escalation'
    fx_margin_bps: number | null
  }
  fx_snapshots: Array<{
    snapshot_id: string
    quote_currency: string
    usd_per_unit: string
    observed_at: string
    source: string
  }>
  trusted_session: {
    trusted_carrier_name: string
    trusted_carrier_id: string
    trusted_contact_id: string
  }
  is_demo: boolean
}
