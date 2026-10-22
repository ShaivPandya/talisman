// Imported first so errors thrown while App evaluates are queued for Sentry,
// which loads once the first page has rendered.
import { startFrontendObservability } from "@/lib/observabilityShim"

startFrontendObservability()
