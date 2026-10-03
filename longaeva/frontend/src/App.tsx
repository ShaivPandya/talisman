import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/layout/AppShell"
import { EvaluationPage } from "@/pages/EvaluationPage"
import { NotFoundPage } from "@/pages/NotFoundPage"
import { ReplayPage } from "@/pages/ReplayPage"
import { RunDetailPage } from "@/pages/RunDetailPage"
import { RunsPage } from "@/pages/RunsPage"
import { ScenariosPage } from "@/pages/ScenariosPage"
import { StatePage } from "@/pages/StatePage"
import { ValuationPage } from "@/pages/ValuationPage"

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/state" element={<StatePage />} />
          <Route path="/scenarios" element={<ScenariosPage />} />
          <Route path="/valuation" element={<ValuationPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/replay" element={<ReplayPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
