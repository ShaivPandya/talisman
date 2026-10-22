import { createElement, memo, useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import { flushSync } from "react-dom"
import { ScreenContextProvider, useScreenContext } from "../../src/contexts/ScreenContext"

export async function measureContext(baseline: boolean) {
  const context = baseline
    ? await import(/* @vite-ignore */ "/tmp/ScreenContext.before.tsx")
    : { ScreenContextProvider, useScreenContext }
  let renders = 0
  let advance!: () => void
  const Consumer = memo(function Consumer() {
    context.useScreenContext()
    useEffect(() => { renders++ })
    return null
  })
  const child = createElement(Consumer)
  function Parent() {
    const [, setCount] = useState(0)
    useEffect(() => { advance = () => setCount(count => count + 1) }, [])
    return createElement(context.ScreenContextProvider, null, child)
  }
  const container = document.createElement("div")
  document.body.append(container)
  const root = createRoot(container)
  flushSync(() => root.render(createElement(Parent)))
  for (let i = 0; i < 10; i++) flushSync(advance)
  flushSync(() => root.unmount())
  container.remove()
  return renders
}
