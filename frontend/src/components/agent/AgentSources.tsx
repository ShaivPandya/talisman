import { useState } from "react"
import { ExternalLink } from "lucide-react"
import { isPrivateSourceUrl } from "@/lib/sourceLinks"

const COLLAPSED_COUNT = 6

interface SourceLink {
  url: string
  title: string
  host: string
}

/** Public http(s) links and the exact authenticated upload route become source chips. */
function sourceLinks(sources: Record<string, unknown>[] | undefined): SourceLink[] {
  const seen = new Set<string>()
  const links: SourceLink[] = []
  for (const source of sources ?? []) {
    const raw = source?.url
    if (typeof raw !== "string") continue
    if (isPrivateSourceUrl(raw)) {
      if (!seen.has(raw)) {
        seen.add(raw)
        links.push({ url: raw, title: typeof source.title === "string" ? source.title : "Uploaded file", host: "Private upload" })
      }
      continue
    }
    let parsed: URL
    try {
      parsed = new URL(raw)
    } catch {
      continue
    }
    if ((parsed.protocol !== "https:" && parsed.protocol !== "http:") || seen.has(parsed.href)) continue
    seen.add(parsed.href)
    const host = parsed.hostname.replace(/^www\./, "")
    const title = typeof source.title === "string" && source.title.trim() ? source.title.trim() : host
    links.push({ url: parsed.href, title, host })
  }
  return links
}

export function AgentSources({ sources }: { sources: Record<string, unknown>[] | undefined }) {
  const [expanded, setExpanded] = useState(false)
  const links = sourceLinks(sources)
  if (!links.length) return null
  const shown = expanded ? links : links.slice(0, COLLAPSED_COUNT)
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="Sources">
      {[false, true].map(privateGroup => {
        const group = shown.filter(link => isPrivateSourceUrl(link.url) === privateGroup)
        if (!group.length) return null
        const label = privateGroup ? "Private uploads" : "Public web sources"
        return <div key={label} aria-label={label} className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-subtle">{label}</span>
          {group.map(link => (
            <a
              key={link.url}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              title={link.title === link.host ? link.url : `${link.title}\n${link.url}`}
              className="inline-flex max-w-[16rem] items-center gap-1 rounded-md border border-app bg-muted-surface px-2 py-0.5 text-xs text-muted hover:text-app"
            >
              <ExternalLink size={10} className="shrink-0" aria-hidden="true" />
              <span className="truncate">{link.title}</span>
              {link.title !== link.host && <span className="shrink-0 opacity-60">{link.host}</span>}
            </a>
          ))}
        </div>
      })}
      {links.length > COLLAPSED_COUNT && (
        <button
          type="button"
          className="text-xs text-subtle hover:text-app"
          onClick={() => setExpanded(value => !value)}
        >
          {expanded ? "Show fewer" : `+${links.length - COLLAPSED_COUNT} more`}
        </button>
      )}
    </div>
  )
}
