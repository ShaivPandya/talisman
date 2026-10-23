/** Copy text to the clipboard. Returns false when the browser refuses, so callers don't claim a copy. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Fall back for pages without clipboard permission.
  }
  const field = document.createElement("textarea")
  field.value = text
  field.setAttribute("readonly", "")
  field.style.position = "fixed"
  field.style.opacity = "0"
  document.body.appendChild(field)
  try {
    field.select()
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    field.remove()
  }
}
