/**
 * The single operation screen.
 *
 * One read-mostly view of one operation: what the human authorized, what the agent
 * heard, what it committed to, and what it kicked upstairs. Read-mostly is why there is
 * no router and no state library — adding either would be capability we can't justify.
 *
 * Sections match the ledger's vocabulary deliberately: a judge should be able to point
 * at a row here and at the event that produced it.
 */

const SECTIONS = [
  { id: 'operation', title: 'Operation', hint: 'container, route, ETA, current phase' },
  { id: 'mandate', title: 'Mandate', hint: 'price cap, window, allowed actions — set by a human, immutable from inside a call' },
  { id: 'quotes', title: 'Quotes', hint: 'every carrier RFQ, side by side, with why the winner won' },
  { id: 'commitments', title: 'Commitments', hint: 'what was agreed, under which mandate, linked to its audio timestamp' },
  { id: 'escalations', title: 'Escalations', hint: 'what the agent refused to decide alone, and what happened next' },
] as const

export default function App() {
  return (
    <main>
      <header>
        <h1>Volta</h1>
        <p>Drayage coordination by phone. Manzanillo → Guadalajara.</p>
      </header>

      {SECTIONS.map(({ id, title, hint }) => (
        <section key={id} aria-labelledby={`${id}-heading`}>
          <h2 id={`${id}-heading`}>{title}</h2>
          <p className="hint">{hint}</p>
          <p className="empty">Not wired yet — scaffold only.</p>
        </section>
      ))}
    </main>
  )
}
