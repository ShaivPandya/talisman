import { StubPage } from "./StubPage"

export function ReplayPage() {
  return (
    <StubPage
      title="Replay"
      subtitle="Re-run a saved record and compare output hashes."
    >
      <p>
        Replay from this page is not wired yet. From the package root, with no LLM provider
        configured:
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg bg-card-muted p-3 mono-text text-sm">
        make replay RUN=&lt;run-uuid&gt;
      </pre>
    </StubPage>
  )
}
