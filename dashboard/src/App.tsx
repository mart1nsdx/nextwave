import { useCallback, useEffect, useMemo, useState } from 'react'
import { controlTowerApi } from './api'
import type {
  CallEvidence,
  CallSummary,
  CommandResult,
  OfferComparison,
  OperationConfiguration,
  OperationSummary,
  OperationWorkspace,
} from './types'

type Route =
  | { page: 'operations' }
  | { page: 'operation'; operationId: string }
  | { page: 'configuration'; operationId: string }
  | { page: 'calls'; selectedCallId: string | null }

function parseRoute(): Route {
  const segments = window.location.pathname.split('/').filter(Boolean)
  if (segments[0] === 'operations' && segments[1] && segments[2] === 'configuration') {
    return { page: 'configuration', operationId: segments[1] }
  }
  if (segments[0] === 'operations' && segments[1]) {
    return { page: 'operation', operationId: segments[1] }
  }
  if (segments[0] === 'calls') {
    return { page: 'calls', selectedCallId: new URLSearchParams(window.location.search).get('call') }
  }
  return { page: 'operations' }
}

function useRoute(): [Route, (path: string) => void] {
  const [route, setRoute] = useState<Route>(parseRoute)

  useEffect(() => {
    const onPopState = () => setRoute(parseRoute())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = useCallback((path: string) => {
    window.history.pushState({}, '', path)
    setRoute(parseRoute())
  }, [])

  return [route, navigate]
}

function formatMoney(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(amountMinor / 100)
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-US', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(new Date(value))
}

function formatOffset(offsetMs: number): string {
  const minutes = Math.floor(offsetMs / 60_000)
  const seconds = Math.floor((offsetMs % 60_000) / 1_000)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function newIdempotencyKey(): string {
  return window.crypto?.randomUUID?.() ?? `dashboard-${Date.now()}`
}

function App() {
  const [route, navigate] = useRoute()
  const [operations, setOperations] = useState<OperationSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const loadOperations = useCallback(async () => {
    setIsLoading(true)
    try {
      setOperations(await controlTowerApi.listOperations())
      setError(null)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Dashboard API is unavailable.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => void loadOperations())
    return () => window.cancelAnimationFrame(frame)
  }, [loadOperations])

  const content = () => {
    if (route.page === 'operation') {
      return (
        <OperationDetail
          operationId={route.operationId}
          onBack={() => navigate('/operations')}
          onOpenCalls={() => navigate('/calls')}
          onOpenConfiguration={() => navigate(`/operations/${route.operationId}/configuration`)}
          onStateChanged={() => void loadOperations()}
        />
      )
    }
    if (route.page === 'calls') {
      return (
        <CallsPage
          selectedCallId={route.selectedCallId}
          onOpenOperation={(operationId) => navigate(`/operations/${operationId}`)}
          onSelectCall={(callId) => navigate(`/calls?call=${callId}`)}
        />
      )
    }
    if (route.page === 'configuration') {
      return <ConfigurationPage operationId={route.operationId} onBack={() => navigate(`/operations/${route.operationId}`)} />
    }
    return (
      <OperationsPage
        operations={operations}
        error={error}
        isLoading={isLoading}
        onOpenOperation={(operationId) => navigate(`/operations/${operationId}`)}
        onRetry={() => void loadOperations()}
      />
    )
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <a
          className="brand"
          href="/operations"
          onClick={(event) => {
            event.preventDefault()
            navigate('/operations')
          }}
        >
          <span className="brand-mark" aria-hidden="true">V</span>
          <span>volta</span>
        </a>
        <p className="eyebrow sidebar-eyebrow">A Nauta logistics agent</p>
        <nav className="navigation">
          <NavItem
            active={route.page === 'operations' || route.page === 'operation'}
            label="Operations"
            onClick={() => navigate('/operations')}
          />
          <NavItem active={route.page === 'calls'} label="Calls" onClick={() => navigate('/calls')} />
          <NavItem
            active={route.page === 'configuration'}
            label="Configuration"
            onClick={() => navigate(`/operations/${operations[0]?.id ?? 'op-mzo-0001'}/configuration`)}
          />
        </nav>
        <div className="sidebar-footer">
          <span className="source-dot" aria-hidden="true" />
          <span>Database-backed workspace</span>
          <small>Signals and actions come from server projections.</small>
        </div>
      </aside>

      <section className="content-shell">
        <header className="topbar">
          <p className="topbar-copy">Phone-first drayage coordination</p>
          <span className="source-label">Server database · carrier calls remain policy-controlled</span>
        </header>
        <main>{content()}</main>
      </section>
    </div>
  )
}

function NavItem({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button className={`nav-item${active ? ' nav-item-active' : ''}`} type="button" onClick={onClick}>
      <span className="nav-indicator" aria-hidden="true" />
      {label}
    </button>
  )
}

function OperationsPage({
  operations,
  error,
  isLoading,
  onOpenOperation,
  onRetry,
}: {
  operations: OperationSummary[]
  error: string | null
  isLoading: boolean
  onOpenOperation: (operationId: string) => void
  onRetry: () => void
}) {
  const groups = useMemo(
    () => [
      { key: 'needs_attention', title: 'Needs attention', detail: 'Free time or a decision is at risk.' },
      { key: 'working', title: 'Volta is working', detail: 'Carrier outreach or award review is in progress.' },
      { key: 'executing', title: 'In execution', detail: 'A verified operation has an assigned resource.' },
    ],
    [],
  )

  return (
    <div className="page page-operations">
      <section className="page-heading">
        <p className="eyebrow">Control tower</p>
        <h1>Move before the <em>clock</em> does.</h1>
        <p>Prioritized operations for the drayage leg, from port readiness through verified execution.</p>
      </section>

      {isLoading && <LoadingState label="Loading operations" />}
      {error && (
        <section className="error-state" role="alert">
          <p className="eyebrow">Dashboard API unavailable</p>
          <h2>The control tower could not load its database projection.</h2>
          <p>{error}</p>
          <button className="secondary-button" type="button" onClick={onRetry}>Retry connection</button>
        </section>
      )}

      {!isLoading && !error && groups.map((group) => {
        const groupOperations = operations.filter((operation) => operation.attention === group.key)
        return (
          <section className="queue-section" key={group.key} aria-labelledby={`${group.key}-heading`}>
            <div className="queue-heading">
              <div>
                <p className="eyebrow">{group.title}</p>
                <h2 id={`${group.key}-heading`}>{group.detail}</h2>
              </div>
              <span className="count">{groupOperations.length}</span>
            </div>
            <div className="operation-list">
              {groupOperations.map((operation) => (
                <button
                  className="operation-row"
                  type="button"
                  key={operation.id}
                  onClick={() => onOpenOperation(operation.id)}
                >
                  <div className="operation-route">
                    <span className="reference">{operation.reference}</span>
                    <strong>{operation.route}</strong>
                    <span>{operation.container_number} · {operation.client_name}</span>
                  </div>
                  <div className="operation-stage">
                    <StatusBadge value={operation.stage} />
                    <span>{operation.next_action}</span>
                  </div>
                  <div className={`operation-clock${operation.days_remaining !== null && operation.days_remaining <= 3 ? ' operation-clock-urgent' : ''}`}>
                    <span className="eyebrow">Free time</span>
                    <strong>{operation.days_remaining === null ? '—' : `${operation.days_remaining} days`}</strong>
                    <small>{operation.source_freshness}</small>
                  </div>
                  <span className="row-arrow" aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function OperationDetail({
  operationId,
  onBack,
  onOpenCalls,
  onOpenConfiguration,
  onStateChanged,
}: {
  operationId: string
  onBack: () => void
  onOpenCalls: () => void
  onOpenConfiguration: () => void
  onStateChanged: () => void
}) {
  const [workspace, setWorkspace] = useState<OperationWorkspace | null>(null)
  const [calls, setCalls] = useState<CallSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [showActivation, setShowActivation] = useState(false)
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const loadWorkspace = useCallback(async () => {
    setIsLoading(true)
    try {
      const [nextWorkspace, nextCalls] = await Promise.all([
        controlTowerApi.getWorkspace(operationId),
        controlTowerApi.getCalls(operationId),
      ])
      setWorkspace(nextWorkspace)
      setCalls(nextCalls)
      setError(null)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Operation data is unavailable.')
    } finally {
      setIsLoading(false)
    }
  }, [operationId])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => void loadWorkspace())
    return () => window.cancelAnimationFrame(frame)
  }, [loadWorkspace])

  useEffect(() => {
    if (workspace?.rfq.phase !== 'open') return undefined
    const poll = window.setInterval(() => void loadWorkspace(), 5_000)
    return () => window.clearInterval(poll)
  }, [loadWorkspace, workspace?.rfq.phase])

  const activate = async () => {
    if (!workspace) return
    setIsSubmitting(true)
    try {
      const result = await controlTowerApi.activateRfq(
        workspace.id,
        workspace.rfq.id,
        workspace.carrier_candidates.filter((carrier) => carrier.is_vetted).map((carrier) => carrier.id),
        newIdempotencyKey(),
      )
      setCommandResult(result)
      setShowActivation(false)
      await loadWorkspace()
      onStateChanged()
    } catch (commandError) {
      setCommandResult({
        operation_id: workspace.id,
        rfq_id: workspace.rfq.id,
        outcome: 'error',
        message: commandError instanceof Error ? commandError.message : 'Activation failed.',
        phase: workspace.rfq.phase,
        is_demo: false,
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  const requestAward = async (offer: OfferComparison) => {
    if (!workspace) return
    setIsSubmitting(true)
    try {
      const result = await controlTowerApi.requestAward(
        workspace.id,
        workspace.rfq.id,
        offer.id,
        newIdempotencyKey(),
      )
      setCommandResult(result)
      await loadWorkspace()
      onStateChanged()
    } catch (commandError) {
      setCommandResult({
        operation_id: workspace.id,
        rfq_id: workspace.rfq.id,
        outcome: 'error',
        message: commandError instanceof Error ? commandError.message : 'Award request failed.',
        phase: workspace.rfq.phase,
        is_demo: false,
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading) return <div className="page"><LoadingState label="Loading operation workspace" /></div>
  if (error || !workspace) {
    return (
      <div className="page">
        <section className="error-state">
          <h1>Operation unavailable</h1>
          <p>{error ?? 'No workspace was returned.'}</p>
          <button className="secondary-button" type="button" onClick={onBack}>Back to operations</button>
        </section>
      </div>
    )
  }

  const canActivate = workspace.rfq.phase === 'ready'
  const canAward = workspace.rfq.phase === 'open'

  return (
    <div className="page page-detail">
      <button className="back-button" type="button" onClick={onBack}>← Operations</button>
      <section className="operation-hero">
        <div>
          <p className="eyebrow">{workspace.reference} · {workspace.container_number}</p>
          <h1>{workspace.route}</h1>
          <p>{workspace.cargo_description} · {workspace.weight_kg.toLocaleString('en-US')} kg · Ocean carrier: {workspace.ocean_carrier}</p>
        </div>
        <div className="hero-state">
          <StatusBadge value={workspace.stage} />
          <span className={workspace.days_remaining !== null && workspace.days_remaining <= 3 ? 'countdown urgent' : 'countdown'}>
            {workspace.days_remaining === null ? 'Execution active' : `${workspace.days_remaining} days of free time`}
          </span>
          {workspace.last_free_day && <small>Last free day: {workspace.last_free_day}</small>}
        </div>
      </section>

      {commandResult && <CommandNotice result={commandResult} onDismiss={() => setCommandResult(null)} />}

      <div className="detail-grid">
        <section className="detail-main">
          <section className="surface timeline-surface" aria-labelledby="timeline-heading">
            <div className="section-heading">
              <div><p className="eyebrow">Operation timeline</p><h2 id="timeline-heading">Where this container is now.</h2></div>
              <span className="source-label">Source-labelled</span>
            </div>
            <ol className="timeline">
              {workspace.timeline.map((event) => (
                <li className={`timeline-event timeline-${event.status}`} key={event.label}>
                  <span className="timeline-marker" aria-hidden="true" />
                  <div><strong>{event.label}</strong><small>{event.source}{event.occurred_at ? ` · ${formatDate(event.occurred_at)}` : ''}</small></div>
                </li>
              ))}
            </ol>
          </section>

          <section className="surface" aria-labelledby="offers-heading">
            <div className="section-heading">
              <div><p className="eyebrow">Carrier market</p><h2 id="offers-heading">Compare the cost of speed.</h2></div>
              <StatusBadge value={`RFQ ${workspace.rfq.phase}`} />
            </div>
            {workspace.rfq.offers.length === 0 ? (
              <div className="empty-market"><strong>No quotes yet.</strong><p>Volta is ready to contact the selected vetted carriers after operator confirmation.</p></div>
            ) : (
              <div className="offer-list">
                {workspace.rfq.offers.map((offer) => (
                  <article className={`offer-card${offer.is_recommended ? ' offer-recommended' : ''}`} key={offer.id}>
                    <div className="offer-heading"><div><p className="eyebrow">{offer.status.replace('_', ' ')}</p><h3>{offer.carrier_name}</h3></div>{offer.is_recommended && <span className="recommendation">Recommended</span>}</div>
                    <div className="offer-metrics"><div><span>Freight</span><strong>{formatMoney(offer.freight_amount_minor, offer.currency)}</strong></div><div><span>Expected total</span><strong>{formatMoney(offer.expected_total_amount_minor, offer.currency)}</strong></div><div><span>Reliability</span><strong>{offer.reliability_percent}%</strong></div></div>
                    <p>{offer.rationale}</p>
                    <div className="offer-footer"><span>{offer.pickup_window}</span>{offer.evidence_call_id && <button className="text-button" type="button" onClick={onOpenCalls}>View call evidence →</button>}</div>
                    {canAward && offer.status === 'eligible' && <button className="secondary-button offer-action" type="button" disabled={isSubmitting} onClick={() => void requestAward(offer)}>Request award review</button>}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="surface call-section" aria-labelledby="calls-heading">
            <div className="section-heading"><div><p className="eyebrow">Call evidence</p><h2 id="calls-heading">What was said, kept verifiable.</h2></div><button className="text-button" type="button" onClick={onOpenCalls}>Open calls →</button></div>
            {calls.length === 0 ? <p className="empty-copy">No calls are attached to this operation yet.</p> : <div className="compact-calls">{calls.map((call) => <CallRow key={call.id} call={call} onClick={onOpenCalls} />)}</div>}
          </section>
        </section>

        <aside className="detail-rail">
          <section className="action-panel" aria-labelledby="action-heading">
            <p className="eyebrow">Next action</p><h2 id="action-heading">{workspace.next_action}</h2>
            <ul className="readiness-list">{workspace.readiness.map((check) => <li key={check.label}><span className={check.is_ready ? 'check check-ready' : 'check'}>{check.is_ready ? '✓' : '!'}</span><div><strong>{check.label} · {check.status}</strong><small>{check.detail}</small></div></li>)}</ul>
            <div className="mandate-card"><span className="eyebrow">Active mandate · v{workspace.mandate.version}</span><strong>Up to {formatMoney(workspace.mandate.cap_amount_minor, workspace.mandate.currency)}</strong><span>{workspace.mandate.pickup_window}</span></div>
            {canActivate && <button className="primary-button" type="button" onClick={() => setShowActivation(true)}>Start RFQ</button>}
            {!canActivate && <p className="action-note">{workspace.rfq.phase === 'awarding' ? 'One award request is under review. No booking is confirmed.' : 'This action is controlled by the current RFQ state.'}</p>}
            <button className="configuration-link" type="button" onClick={onOpenConfiguration}>Review immutable configuration →</button>
          </section>

          <section className="surface intelligence-rail" aria-labelledby="intelligence-heading">
            <p className="eyebrow">Connected intelligence</p><h2 id="intelligence-heading">Volta in the Nauta ecosystem.</h2>
            {workspace.connected_agents.map((agent) => <article className="agent-link" key={agent.name}><span className="agent-marker" aria-hidden="true" /><div><strong>{agent.name}</strong><small>{agent.role}</small><p>{agent.relationship}</p><span className="agent-status">{agent.status}</span></div></article>)}
          </section>

          <ExecutionPanel workspace={workspace} />
        </aside>
      </div>

      {showActivation && <ActivationDialog workspace={workspace} isSubmitting={isSubmitting} onCancel={() => setShowActivation(false)} onConfirm={() => void activate()} />}
    </div>
  )
}

function ExecutionPanel({ workspace }: { workspace: OperationWorkspace }) {
  const { assignment, commitment } = workspace
  const state = commitment.state.replace('_', ' ')

  return (
    <section className="surface assignment-card" aria-labelledby="execution-heading">
      <p className="eyebrow">Execution and commitment</p>
      <h2 id="execution-heading">{assignment?.carrier_name ?? commitment.carrier_name ?? 'No carrier assigned'}</h2>
      <StatusBadge value={state} />
      <p className="commitment-copy">{commitmentDescription(commitment.state)}</p>
      {assignment ? (
        <dl>
          <div><dt>Driver</dt><dd>{assignment.driver_name}</dd></div>
          <div><dt>Contact</dt><dd>{assignment.driver_phone}</dd></div>
          <div><dt>Vehicle</dt><dd>{assignment.vehicle_plate}</dd></div>
          <div><dt>Carta Porte</dt><dd>{assignment.carta_porte_status}</dd></div>
        </dl>
      ) : (
        <p className="assignment-pending">Truck, driver, and Carta Porte are recorded only after a verified commitment.</p>
      )}
      {commitment.recap_status && <small className="recap-status">Recap: {commitment.recap_status}</small>}
    </section>
  )
}

function commitmentDescription(state: string): string {
  const descriptions: Record<string, string> = {
    none: 'No commitment exists. Quotes and RFQ activity do not create a booking.',
    verbal: 'Verbal terms were heard. This is not booked.',
    recap_sent: 'The written recap was sent. This is not yet a verified commitment.',
    recap_failed: 'The recap failed. This is not committed and requires follow-up.',
    committed: 'The full verification chain completed. Assignment details may now be recorded.',
    resourced: 'A verified commitment has a contracted carrier and assigned transport resource.',
    documented: 'The verified assignment is documented, including the required transport paperwork.',
    executed: 'The verified movement has completed.',
  }
  return descriptions[state] ?? 'Commitment state is unavailable.'
}

function ConfigurationPage({ operationId, onBack }: { operationId: string; onBack: () => void }) {
  const [configuration, setConfiguration] = useState<OperationConfiguration | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void controlTowerApi.getConfiguration(operationId)
      .then((nextConfiguration) => {
        setConfiguration(nextConfiguration)
        setError(null)
      })
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Configuration is unavailable.'))
  }, [operationId])

  if (error) return <div className="page"><section className="error-state"><h1>Configuration unavailable</h1><p>{error}</p><button className="secondary-button" type="button" onClick={onBack}>Back to operation</button></section></div>
  if (!configuration) return <div className="page"><LoadingState label="Loading configuration" /></div>

  const { mandate, bot, fx_snapshots: fxSnapshots, trusted_session: trustedSession } = configuration
  return (
    <div className="page page-configuration">
      <button className="back-button" type="button" onClick={onBack}>← Operation</button>
      <section className="page-heading">
        <p className="eyebrow">Configuration</p>
        <h1>Human-owned <em>authority.</em></h1>
        <p>Bot preferences are visible here. The mandate is immutable: every policy change requires a new authenticated version, never an in-place edit.</p>
      </section>
      <div className="configuration-grid">
        <section className="surface configuration-section">
          <div className="section-heading"><div><p className="eyebrow">Bot profile</p><h2>{bot.agent_name}</h2></div><span className="source-label">Source-backed profile</span></div>
          <dl className="configuration-list"><div><dt>Role</dt><dd>{bot.agent_role}</dd></div><div><dt>Primary language</dt><dd>{bot.primary_language}</dd></div><div><dt>Fallback language</dt><dd>{bot.fallback_language}</dd></div><div><dt>Recap channel</dt><dd>{bot.recap_channel}</dd></div></dl>
          <p className="configuration-note">These settings shape how Volta presents itself. They do not widen the mandate or change policy.</p>
        </section>
        <section className="surface configuration-section mandate-section">
          <div className="section-heading"><div><p className="eyebrow">Immutable mandate</p><h2>{mandate.mandate_id}</h2></div><StatusBadge value={`v${mandate.version} active`} /></div>
          <dl className="configuration-list"><div><dt>Owner</dt><dd>{mandate.owner_id}</dd></div><div><dt>Operation</dt><dd>{mandate.operation_id}</dd></div><div><dt>Maximum all-in cost</dt><dd>{formatMoney(Number(mandate.max_all_in_usd) * 100, 'USD')}</dd></div><div><dt>Pickup window</dt><dd>{formatDate(mandate.pickup_not_before)} — {formatDate(mandate.pickup_not_after)}</dd></div><div><dt>Allowed equipment</dt><dd>{mandate.allowed_equipment.join(', ')}</dd></div><div><dt>Commitment mode</dt><dd>{mandate.commitment_mode.replace('_', ' ')}</dd></div><div><dt>FX margin</dt><dd>{mandate.fx_margin_bps === null ? 'No non-USD authorization' : `${mandate.fx_margin_bps / 100}%`}</dd></div></dl>
          <div className="immutable-notice"><strong>Locked by design.</strong><span>Caller speech, model output, recaps, and tools cannot change this mandate.</span></div>
        </section>
        <section className="surface configuration-section">
          <p className="eyebrow">Approved FX evidence</p><h2>Snapshots</h2>
          {fxSnapshots.map((snapshot) => <article className="snapshot" key={snapshot.snapshot_id}><strong>{snapshot.quote_currency} → USD</strong><span>{snapshot.usd_per_unit} USD per unit</span><small>{snapshot.snapshot_id} · {formatDate(snapshot.observed_at)} · {snapshot.source}</small></article>)}
          <p className="configuration-note">Policy rejects a future snapshot, a snapshot older than two hours, or a non-USD quote without an explicit mandate margin.</p>
        </section>
        <section className="surface configuration-section">
          <p className="eyebrow">Trusted session identity</p><h2>Directory-bound carrier</h2>
          <dl className="configuration-list"><div><dt>Carrier</dt><dd>{trustedSession.trusted_carrier_name}</dd></div><div><dt>Carrier ID</dt><dd>{trustedSession.trusted_carrier_id}</dd></div><div><dt>Verified contact</dt><dd>{trustedSession.trusted_contact_id}</dd></div></dl>
          <p className="configuration-note">These values must come from the carrier directory or an authenticated session, never from a caller claim.</p>
        </section>
      </div>
    </div>
  )
}

function CallsPage({ selectedCallId, onOpenOperation, onSelectCall }: { selectedCallId: string | null; onOpenOperation: (operationId: string) => void; onSelectCall: (callId: string) => void }) {
  const [calls, setCalls] = useState<CallSummary[]>([])
  const [evidence, setEvidence] = useState<CallEvidence | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      void controlTowerApi.listCalls().then((items) => {
        setCalls(items)
        setError(null)
      }).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Calls are unavailable.'))
    })
    return () => window.cancelAnimationFrame(frame)
  }, [])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (selectedCallId) {
        void controlTowerApi.getEvidence(selectedCallId).then(setEvidence).catch(() => setEvidence(null))
      } else {
        setEvidence(null)
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [selectedCallId])

  return <div className="page page-calls"><section className="page-heading"><p className="eyebrow">Call ledger</p><h1>Calls become <em>evidence.</em></h1><p>Every conversation is linked to the operation, an immutable timestamp, and the policy decision that followed.</p></section>{error ? <section className="error-state"><p>{error}</p></section> : <div className="calls-layout"><section className="surface calls-list"><div className="section-heading"><div><p className="eyebrow">All calls</p><h2>Carrier conversations</h2></div><span className="count">{calls.length}</span></div>{calls.map((call) => <CallRow key={call.id} call={call} onClick={() => onSelectCall(call.id)} selected={call.id === selectedCallId} />)}</section><section className="evidence-panel">{evidence ? <EvidenceDetail evidence={evidence} onOpenOperation={() => onOpenOperation(evidence.call.operation_id)} /> : <div className="empty-evidence"><span className="evidence-mark" aria-hidden="true">↗</span><h2>Select a call.</h2><p>Its brief, transcript, policy result, and evidence pointer will appear here.</p></div>}</section></div>}</div>
}

function CallRow({ call, onClick, selected = false }: { call: CallSummary; onClick: () => void; selected?: boolean }) {
  return <button className={`call-row${selected ? ' call-selected' : ''}`} type="button" onClick={onClick}><div><span className="reference">{call.direction}</span><strong>{call.carrier_name}</strong><small>{call.summary}</small></div><div className="call-meta"><StatusBadge value={call.status} /><span>{Math.ceil(call.duration_seconds / 60)} min · {formatDate(call.started_at)}</span></div></button>
}

function EvidenceDetail({ evidence, onOpenOperation }: { evidence: CallEvidence; onOpenOperation: () => void }) {
  return <div className="evidence-detail"><div className="section-heading"><div><p className="eyebrow">Evidence record</p><h2>{evidence.call.carrier_name}</h2></div><StatusBadge value={evidence.call.status} /></div><button className="text-button" type="button" onClick={onOpenOperation}>Open linked operation →</button><section><p className="eyebrow">Call brief</p><ul className="brief-list">{evidence.call_brief.map((item) => <li key={item}>{item}</li>)}</ul></section><section><p className="eyebrow">Transcript</p><div className="transcript">{evidence.transcript.map((line) => <div className={`transcript-line${line.is_relevant ? ' transcript-relevant' : ''}`} key={`${line.offset_ms}-${line.text}`}><time>{formatOffset(line.offset_ms)}</time><div><strong>{line.speaker}</strong><p>{line.text}</p></div></div>)}</div></section><section className="policy-record"><p className="eyebrow">Policy decisions</p>{evidence.policy_decisions.map((decision) => <div key={decision.reason_code}><StatusBadge value={decision.verdict} /><strong>{decision.reason_code}</strong><small>{formatDate(decision.decided_at)}</small></div>)}</section><section className="evidence-pointer"><p className="eyebrow">Evidence pointer</p>{evidence.evidence ? <p>{evidence.evidence.recording_id} · {formatOffset(evidence.evidence.audio_offset_ms)} · {evidence.evidence.audio_url ? <a href={evidence.evidence.audio_url} target="_blank" rel="noreferrer">Open audio evidence ↗</a> : 'Audio link unavailable'}</p> : <p>No evidence offset is available; this cannot be verified.</p>}</section></div>
}

function ActivationDialog({ workspace, isSubmitting, onCancel, onConfirm }: { workspace: OperationWorkspace; isSubmitting: boolean; onCancel: () => void; onConfirm: () => void }) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="activation-title"><p className="eyebrow">Operator confirmation</p><h2 id="activation-title">Start RFQ for {workspace.reference}?</h2><p>Volta will use the active mandate and the following vetted carriers. This records activation only; carrier outreach remains controlled by the market workflow.</p><ul>{workspace.carrier_candidates.filter((carrier) => carrier.is_vetted).map((carrier) => <li key={carrier.id}><span className="check check-ready">✓</span>{carrier.name} · {carrier.reliability_percent}% reliability</li>)}</ul><div className="dialog-mandate">Mandate cap: <strong>{formatMoney(workspace.mandate.cap_amount_minor, workspace.mandate.currency)}</strong> · {workspace.mandate.pickup_window}</div><div className="dialog-actions"><button className="secondary-button" type="button" disabled={isSubmitting} onClick={onCancel}>Cancel</button><button className="primary-button" type="button" disabled={isSubmitting} onClick={onConfirm}>{isSubmitting ? 'Recording activation…' : 'Confirm and start RFQ'}</button></div></section></div>
}

function CommandNotice({ result, onDismiss }: { result: CommandResult; onDismiss: () => void }) {
  return <section className={`command-notice command-${result.outcome}`} role="status"><span>{result.outcome === 'denied' || result.outcome === 'error' ? '!' : '✓'}</span><p>{result.message}</p><button type="button" onClick={onDismiss} aria-label="Dismiss message">×</button></section>
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-${value.toLowerCase().replaceAll(' ', '-').replaceAll('_', '-')}`}>{value}</span>
}

function LoadingState({ label }: { label: string }) {
  return <div className="loading-state"><span className="loading-mark" aria-hidden="true" /><p>{label}…</p></div>
}

export default App
