import type { ReactNode } from "react"

import { cx } from "@/lib/cx"

interface SurfaceCardProps {
  children: ReactNode
  className?: string
  muted?: boolean
}

export function SurfaceCard({ children, className, muted = false }: SurfaceCardProps) {
  return (
    <section className={cx(muted ? "theme-surface-muted" : "theme-surface", className)}>
      {children}
    </section>
  )
}
