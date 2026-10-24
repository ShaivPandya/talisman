interface AgentSuggestionsProps {
  suggestions: string[]
  onSelect: (question: string) => void
}

/** Questions to ask next, under the latest answer. */
export function AgentSuggestions({ suggestions, onSelect }: AgentSuggestionsProps) {
  if (!suggestions.length) return null
  return (
    <div className="mt-2 flex max-w-[min(92%,48rem)] flex-wrap gap-2" role="group" aria-label="Suggested follow-up questions">
      {suggestions.map(question => (
        <button
          key={question}
          type="button"
          onClick={() => onSelect(question)}
          className="rounded-full border border-app bg-card px-3 py-1.5 text-left text-xs text-muted shadow-sm transition-colors hover:border-[hsl(var(--accent))] hover:text-app"
        >
          {question}
        </button>
      ))}
    </div>
  )
}
