export const STAN_OPEN_EVENT = "talisman:stan-open"

export interface StanOpenDetail {
  command: string
  durable?: boolean
  /** "draft" starts a new chat with the text in the composer instead of sending it. */
  mode?: "send" | "draft"
}

export function openStanWithCommand(command: string, options?: { durable?: boolean }) {
  window.dispatchEvent(
    new CustomEvent<StanOpenDetail>(STAN_OPEN_EVENT, {
      detail: { command, durable: options?.durable ?? true },
    }),
  )
}

export function openStanWithDraft(text: string) {
  window.dispatchEvent(
    new CustomEvent<StanOpenDetail>(STAN_OPEN_EVENT, {
      detail: { command: text, mode: "draft" },
    }),
  )
}
