import { Link } from "react-router-dom"
import { DEMO_LINKS, TOUR_STEPS } from "@/lib/tour"
import { useTour } from "@/lib/tourContext"

const CONCEPTS = [
  ["Information cutoff", "Evidence must have been published by the origin’s cutoff. Later reconciliation documents are shown separately and cannot become eligible inputs."],
  ["Reviewed observations", "Original extractions stay visible alongside effective values and versioned review decisions. Supported rules update parameters; other statements supply context."],
  ["Calibration and overrides", "Calibration anchors the baseline. Manual changes need a rationale and are saved in a child assumption set with retained evidence links."],
  ["Paired simulations", "Baseline and variant share the origin, horizon, seed, and draws. Difference intervals come from paired paths, not subtracted marginal quantiles."],
  ["Conditional attribution", "Contributions explain a change within this model and its intervention order. Inspect support flags, sensitivity, and residuals."],
  ["Replay", "Pinned inputs, hashes, and runtime fingerprints support reproduction. Exact matches and numerical equivalence are reported separately."],
] as const

export function GuidePage() {
  const { launch } = useTour()
  return (
    <div className="guide-page">
      <header className="theme-page-header guide-header">
        <div>
          <h1 className="theme-page-title">How to use</h1>
          <p className="theme-page-subtitle">Longaeva connects published evidence to explicit assumptions, simulated business outcomes, and valuation. Start with a completed Visa example, then test your own view.</p>
        </div>
        <span className="guide-duration">5–7 minute walkthrough</span>
      </header>

      <section className="guide-example" aria-labelledby="guide-example-title">
        <div className="guide-example-description">
          <div className="guide-example-heading">
            <h2 id="guide-example-title">Visa · July 23, 2024</h2>
            <span className="theme-badge theme-badge-neutral">Saved example</span>
          </div>
          <p className="body-copy">A −10% cross-border mix shift, with total payments volume held constant. Both runs are complete and ready to inspect.</p>
        </div>
        <div className="guide-example-actions">
          <button className="theme-button-base theme-button-primary" onClick={launch}>Start product tour <span aria-hidden="true">→</span></button>
          <Link className="text-link" to={DEMO_LINKS.comparison}>Open saved example →</Link>
          <Link className="text-link" to={DEMO_LINKS.scenario}>Build a scenario →</Link>
        </div>
        <p className="guide-example-note">The tour follows the real app pages. Exit whenever you like; resume or restart later. No provider credentials or new simulations are needed.</p>
      </section>

      <p className="guide-flow">Inspect evidence <span aria-hidden="true">→</span> Change assumptions <span aria-hidden="true">→</span> Compare outcomes <span aria-hidden="true">→</span> Assess valuation <span aria-hidden="true">→</span> Evaluate and reproduce</p>

      <div className="guide-columns">
        <section aria-labelledby="guide-workflow-title">
          <div className="guide-section-heading">
            <h2 id="guide-workflow-title">Walkthrough</h2>
            <span className="caption">Open any step directly</span>
          </div>
          <ol className="guide-steps">
            {TOUR_STEPS.map((step, index) => <li key={step.id} className="guide-step">
              <span className="guide-step-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <h3><Link to={step.to}>{step.title}<span className="guide-step-arrow" aria-hidden="true">↗</span></Link></h3>
                <p className="body-copy">{step.explanation}</p>
                <p className="guide-inspect"><strong>Inspect</strong> {step.inspect}</p>
                {step.optional && <p className="caption guide-step-note">{step.optional}</p>}
              </div>
            </li>)}
          </ol>
        </section>

        <aside className="guide-reference" aria-label="Guide reference">
          <section aria-labelledby="guide-concepts-title">
            <div className="guide-section-heading"><h2 id="guide-concepts-title">Reading the model</h2></div>
            <dl className="guide-concepts">
              {CONCEPTS.map(([title, copy]) => <div key={title}><dt>{title}</dt><dd>{copy}</dd></div>)}
            </dl>
          </section>
          <section className="guide-methods" aria-labelledby="guide-methods-title">
            <h2 id="guide-methods-title">Methods & limitations</h2>
            <p className="body-copy">Read historical scores with matched baselines, sample counts, and the failure case. The prospective Q4 FY2026 registration remains unscored. Valuation uses a quarterly buyback-average reference price; action costs are illustrative.</p>
            <ul className="guide-document-links">
              <li><Link to={DEMO_LINKS.methodology}>Evaluation methodology <span aria-hidden="true">↗</span></Link></li>
              <li><Link to={DEMO_LINKS.model}>Model specification <span aria-hidden="true">↗</span></Link></li>
              <li><Link to={DEMO_LINKS.failure}>Failure case <span aria-hidden="true">↗</span></Link></li>
              <li><Link to={DEMO_LINKS.limitations}>Limitations <span aria-hidden="true">↗</span></Link></li>
              <li><Link to="/runs">Browse saved runs <span aria-hidden="true">↗</span></Link></li>
            </ul>
          </section>
          <details className="guide-troubleshooting">
            <summary>Setup and troubleshooting</summary>
            <p className="body-copy mt-3">With Docker Desktop running, use <code>make up</code> from the Longaeva package directory. Without Docker, install Python 3.12+ and Node.js 20.19+, then use <code>make up-local</code> on macOS or Linux, or <code>.\scripts\up-local.ps1</code> on Windows. Either command starts the app and imports the offline demo. Open the web app on port 3000.</p>
            <p className="body-copy mt-3">If a saved example is missing, <code>make seed</code> repeats the validated import and preserves later review decisions and user scenarios. Investigate any conflicting or corrupt record reported by startup.</p>
            <p className="body-copy mt-3">Use the page’s Retry control or the tour’s Retry step for loading errors. You can skip unavailable content and exit throughout. After a failed or ambiguous scenario submission, check Runs before retrying.</p>
          </details>
        </aside>
      </div>
    </div>
  )
}
