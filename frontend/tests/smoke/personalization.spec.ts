import type { Page } from "@playwright/test"

import { authenticate, expect, test } from "./fixtures"
import { dismissFloatingAlerts } from "./operatingWorkflow"

function primaryNav(page: Page) {
  return page.getByRole("navigation", { name: "Primary navigation" })
}

async function openPersonalization(page: Page) {
  await authenticate(page)
  await page.goto("/settings/personalization")
  await expect(page.getByRole("heading", { name: "Personalization", exact: true })).toBeVisible()
  await dismissFloatingAlerts(page)
}

test("persists the accent color across reloads", async ({ page }) => {
  await openPersonalization(page)
  const html = page.locator("html")

  await page.getByRole("radio", { name: "Teal" }).click()
  await expect(html).toHaveAttribute("data-accent", "teal")

  await page.reload()
  await expect(html).toHaveAttribute("data-accent", "teal")
  await expect(page.getByRole("radio", { name: "Teal" })).toHaveAttribute("aria-checked", "true")
  const accent = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--accent").trim(),
  )
  expect(accent).toBe("178 82% 31%")

  await page.getByRole("radio", { name: "Blue" }).click()
  await expect(html).not.toHaveAttribute("data-accent")
})

test("legacy blue utility classes follow the accent color", async ({ page }) => {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("talisman-accent", "teal")
      window.localStorage.setItem("market-dashboard-theme", "light")
    } catch {
      // Storage is unavailable on about:blank.
    }
  })
  // OS dark mode turns on Tailwind dark: variants; the accent remaps must still win.
  await page.emulateMedia({ colorScheme: "dark" })
  await openPersonalization(page)

  const colors = await page.evaluate(() => {
    const host = document.createElement("div")
    host.innerHTML = `
      <span data-probe="accent" style="color: hsl(var(--accent))"></span>
      <span data-probe="accent-foreground" style="color: hsl(var(--accent-foreground))"></span>
      <span data-probe="link" style="color: hsl(var(--link))"></span>
      <span data-probe="border" style="color: hsl(var(--border))"></span>
      <span data-probe="focus-ring" style="color: hsl(var(--focus-ring))"></span>
      <span data-test="dot" class="bg-blue-500"></span>
      <span data-test="tab" class="border-b-2 border-blue-500 text-blue-600 dark:text-blue-400"></span>
      <span data-test="note" class="border border-blue-200 bg-blue-50 text-blue-900 dark:bg-blue-950 dark:text-blue-200"></span>
      <span data-test="link" class="text-blue-400"></span>
      <button data-test="primary" class="theme-button-primary"></button>
      <input data-test="checkbox" type="checkbox" class="accent-blue-600" />
      <div data-test="spinner" class="border-2 border-[hsl(var(--accent))] border-t-transparent"></div>
      <textarea data-test="editor" class="border border-app focus:ring-1 focus:ring-blue-500"></textarea>
    `
    document.body.append(host)
    const style = (selector: string) => getComputedStyle(host.querySelector(selector)!)
    const probe = (name: string) => style(`[data-probe="${name}"]`).color
    const editor = host.querySelector<HTMLTextAreaElement>('[data-test="editor"]')!
    const restingEditorBorder = style('[data-test="editor"]').borderTopColor
    editor.focus()
    const focusedEditorBorder = style('[data-test="editor"]').borderTopColor

    return {
      accent: probe("accent"),
      accentForeground: probe("accent-foreground"),
      link: probe("link"),
      border: probe("border"),
      focusRing: probe("focus-ring"),
      dot: style('[data-test="dot"]').backgroundColor,
      tabBorder: style('[data-test="tab"]').borderBottomColor,
      tabText: style('[data-test="tab"]').color,
      noteText: style('[data-test="note"]').color,
      linkText: style('[data-test="link"]').color,
      primaryBackground: style('[data-test="primary"]').backgroundColor,
      primaryText: style('[data-test="primary"]').color,
      checkbox: style('[data-test="checkbox"]').accentColor,
      spinnerSide: style('[data-test="spinner"]').borderLeftColor,
      spinnerTop: style('[data-test="spinner"]').borderTopColor,
      restingEditorBorder,
      focusedEditorBorder,
    }
  })

  expect(colors.accent).toBe("rgb(14, 144, 140)")
  expect(colors.dot).toBe(colors.accent)
  expect(colors.tabBorder).toBe(colors.accent)
  expect(colors.tabText).toBe(colors.link)
  expect(colors.noteText).toBe(colors.link)
  expect(colors.linkText).toBe(colors.link)
  expect(colors.primaryBackground).toBe(colors.accent)
  expect(colors.primaryText).toBe(colors.accentForeground)
  expect(colors.checkbox).toBe(colors.accent)
  expect(colors.spinnerSide).toBe(colors.accent)
  expect(colors.spinnerTop).toBe("rgba(0, 0, 0, 0)")
  expect(colors.restingEditorBorder).toBe(colors.border)
  expect(colors.focusedEditorBorder).toBe(colors.focusRing)
})

test("hides a sidebar page and still opens it from page search", async ({ page }) => {
  await openPersonalization(page)
  const nav = primaryNav(page)

  await expect(nav.getByRole("link", { name: "Liquidity" })).toBeVisible()
  await page.getByRole("switch", { name: "Liquidity" }).click()
  await expect(nav.getByRole("link", { name: "Liquidity" })).toHaveCount(0)

  await page.reload()
  await expect(page.getByRole("switch", { name: "Liquidity" })).toHaveAttribute("aria-checked", "false")
  await expect(nav.getByRole("link", { name: "Liquidity" })).toHaveCount(0)

  await nav.getByRole("button", { name: "Search pages" }).click()
  await page.getByPlaceholder("Search pages").fill("Liquidity")
  const option = page.getByRole("option", { name: /Liquidity/ })
  await expect(option).toContainText("Hidden")
  await option.click()

  await expect(page).toHaveURL(/\/liquidity$/)
  await expect(page.getByRole("heading", { name: "Liquidity Dashboard" })).toBeVisible()
})

test("keeps Personalization in the sidebar when settings pages are hidden", async ({ page }) => {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        "talisman-hidden-pages",
        JSON.stringify(["/settings/personalization", "/settings/ai", "/settings/policy-matrix"]),
      )
    } catch {
      // Storage is unavailable on about:blank.
    }
  })
  await openPersonalization(page)
  const nav = primaryNav(page)

  await expect(nav.getByRole("link", { name: "AI Settings" })).toHaveCount(0)
  await expect(nav.getByRole("link", { name: "Policy Matrix" })).toHaveCount(0)
  await expect(nav.getByText("Settings", { exact: true })).toBeVisible()
  await expect(nav.getByRole("link", { name: "Personalization" })).toBeVisible()

  const lockedSwitch = page.getByRole("switch", { name: /^Personalization/ })
  await expect(lockedSwitch).toBeDisabled()
  await expect(lockedSwitch).toHaveAttribute("aria-checked", "true")

  await page.getByRole("button", { name: "Show all" }).click()
  await expect(nav.getByRole("link", { name: "AI Settings" })).toBeVisible()
  await expect(nav.getByRole("link", { name: "Policy Matrix" })).toBeVisible()
})

test("collapses the desktop sidebar to a remembered icon rail", async ({ page }) => {
  await authenticate(page)
  await page.goto("/")
  await dismissFloatingAlerts(page)
  const nav = primaryNav(page)

  await nav.getByRole("button", { name: "Collapse sidebar" }).click()
  await expect(nav).toHaveAttribute("data-collapsed", "true")
  await expect(nav.getByText("Core", { exact: true })).toHaveCount(0)
  await expect.poll(async () => (await nav.boundingBox())?.width ?? 0).toBeLessThan(80)

  const workspaceLink = nav.getByRole("link", { name: "Workspace" })
  await expect(workspaceLink).toHaveText("")
  await workspaceLink.hover()
  await expect(page.getByRole("tooltip")).toHaveText("Workspace")
  await workspaceLink.click()
  await expect(page).toHaveURL(/\/workspace$/)
  await expect(page.getByRole("heading", { name: "Action queue" })).toBeVisible()

  await page.reload()
  await expect(nav).toHaveAttribute("data-collapsed", "true")

  await nav.getByRole("button", { name: "Expand sidebar" }).click()
  await expect(nav).not.toHaveAttribute("data-collapsed")
  await expect(nav.getByText("Core", { exact: true })).toBeVisible()
  await expect(nav.getByRole("link", { name: "Workspace" })).toHaveText("Workspace")
})

test.describe("phone drawer", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  })

  test("keeps the full labeled list when the desktop sidebar is collapsed", async ({ page }) => {
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("talisman-sidebar-collapsed", "true")
      } catch {
        // Storage is unavailable on about:blank.
      }
    })
    await authenticate(page)
    await page.goto("/")
    await dismissFloatingAlerts(page)

    await page.getByRole("button", { name: "Open navigation" }).click()
    const nav = primaryNav(page)
    await expect(nav.getByText("Core", { exact: true })).toBeVisible()
    await expect(nav.getByRole("link", { name: "Workspace" })).toHaveText("Workspace")
    await expect(nav.getByRole("button", { name: "Collapse sidebar" })).toHaveCount(0)
  })
})
