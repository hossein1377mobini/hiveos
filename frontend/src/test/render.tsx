import { render, type RenderOptions } from "@testing-library/react"
import type { ReactElement } from "react"
import { MemoryRouter } from "react-router-dom"

/**
 * Router-aware render.
 *
 * The app moved from a useState screen switch to react-router (v0.5, defect
 * A4/D1), so every component under the shell now needs router context. Tests
 * route through this helper instead of each importing MemoryRouter, which keeps
 * the initial-entry override in one place.
 */
export function renderWithRouter(
  ui: ReactElement,
  { route = "/", ...options }: RenderOptions & { route?: string } = {},
) {
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>, options)
}

export * from "@testing-library/react"
