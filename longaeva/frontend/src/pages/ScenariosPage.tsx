import { StubPage } from "./StubPage"

export function ScenariosPage() {
  return (
    <StubPage
      title="Scenarios"
      subtitle="Parameter controls, paired runs, fan charts and attribution."
    >
      <p>
        Scenario definition and run submission will live here. Until then, submit a run from
        the package root with:
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg bg-card-muted p-3 mono-text text-sm">
        make submit-run ARGS=&apos;--origin 2024-07-23 --n-paths 64 --inline&apos;
      </pre>
    </StubPage>
  )
}
