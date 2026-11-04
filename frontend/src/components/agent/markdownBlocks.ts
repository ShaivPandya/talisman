interface Fence {
  marker: string
  length: number
}

const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/
const LIST_ITEM = /^ {0,3}(?:[-+*]|\d{1,9}[.)])(?:[ \t]|$)/

function openingFence(line: string): Fence | null {
  const match = FENCE_OPEN.exec(line)
  if (!match) return null
  const [, run, info] = match
  // A backtick fence's info string can't contain backticks.
  if (run[0] === "`" && info.includes("`")) return null
  return { marker: run[0], length: run.length }
}

function closesFence(line: string, fence: Fence): boolean {
  const match = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(line)
  return Boolean(match && match[1][0] === fence.marker && match[1].length >= fence.length)
}

/**
 * Whether a line after a blank line still belongs to the block before it:
 * indented lines (list item paragraphs, indented code) and the next item of
 * a loose list. Keeping such lines together is always safe; splitting them
 * could render one list or code block as two.
 */
function continuesBlock(line: string, previous: string): boolean {
  if (/^[ \t]/.test(line)) return true
  return LIST_ITEM.test(line) && (LIST_ITEM.test(previous) || /^[ \t]/.test(previous))
}

/**
 * Splits Markdown into top-level blocks that each render as they would in the
 * whole document, so a streaming answer can render its finished blocks once
 * and re-parse only the growing last block.
 *
 * It splits only at blank lines outside fenced code. A block ends once the
 * next one starts, so every block but the last keeps its text as more arrives.
 * Rarer constructs that reach across blocks, such as reference-style links
 * and footnotes, may show unresolved until the answer renders whole.
 */
export function splitMarkdownBlocks(markdown: string): string[] {
  const lines = markdown.split("\n")
  const blocks: string[] = []
  let start = 0
  let fence: Fence | null = null
  let previous = ""
  let hasContent = false
  let afterBlank = false

  lines.forEach((line, index) => {
    if (fence) {
      if (closesFence(line, fence)) fence = null
      previous = line
      return
    }
    if (!line.trim()) {
      afterBlank = hasContent
      return
    }
    if (afterBlank && !continuesBlock(line, previous)) {
      blocks.push(lines.slice(start, index).join("\n"))
      start = index
    }
    afterBlank = false
    hasContent = true
    fence = openingFence(line)
    previous = line
  })
  blocks.push(lines.slice(start).join("\n"))
  return blocks
}
