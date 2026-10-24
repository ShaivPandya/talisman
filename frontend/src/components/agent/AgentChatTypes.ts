export type AgentPanel = "chat" | "history" | "preferences" | "memory"

export type AgentViewMode = "compact" | "console"

export interface QuickPromptGroup {
  title: string
  prompts: string[]
}
