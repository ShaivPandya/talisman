import { useState } from "react"

/** Keep chart labels aligned with the last resolved data while a new key loads. */
export function useDisplayedQueryParameter<T extends string>(parameter: T, isPlaceholderData: boolean): T {
  const [resolvedParameter, setResolvedParameter] = useState(parameter)

  if (!isPlaceholderData && resolvedParameter !== parameter) {
    setResolvedParameter(parameter)
  }

  return isPlaceholderData ? resolvedParameter : parameter
}
