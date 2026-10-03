import type { ReactNode } from "react"

import { SurfaceCard } from "@/components/shared/SurfaceCard"

interface StubPageProps {
  title: string
  subtitle: string
  children: ReactNode
}

export function StubPage({ title, subtitle, children }: StubPageProps) {
  return (
    <div>
      <header className="theme-page-header">
        <div>
          <h1 className="theme-page-title">{title}</h1>
          <p className="theme-page-subtitle">{subtitle}</p>
        </div>
      </header>
      <SurfaceCard className="p-5 body-copy">{children}</SurfaceCard>
    </div>
  )
}
