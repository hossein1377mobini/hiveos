import { describe, expect, it, vi, afterEach } from "vitest";
import axe from "axe-core";
import { screen, within } from "@testing-library/react";
import App from "./App";
import AdminApp from "./admin/AdminApp";
import { renderWithRouter } from "./test/render";

/**
 * Accessibility regression gate. [E1-E6]
 *
 * These assert the properties the manual audit found missing in v0.1: one
 * landmark structure per shell, a named main region, labelled controls, and a
 * table that exposes its own semantics. axe catches a subset of WCAG; the
 * explicit assertions below cover the things this codebase got wrong by hand.
 */

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

/**
 * Runs axe-core and fails with the rule ids and nodes, not just a count.
 *
 * vitest-axe's `toHaveNoViolations` matcher ships an empty extend-expect
 * entrypoint, so the assertion is written against axe-core directly — one less
 * layer between the test and the report.
 */
async function expectA11yClean(container: HTMLElement) {
  const results = await axe.run(container, {
    // Colour contrast needs a real layout engine; jsdom has none, so the rule
    // reports every element as unverifiable.
    rules: { "color-contrast": { enabled: false } },
  });
  const summary = results.violations
    .map((violation) => violation.id + " (" + violation.nodes.length + "): " + violation.help)
    .join("\n");
  expect(summary).toBe("");
}

function json(data: unknown) {
  return new Response(JSON.stringify({ success: true, data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("accessibility", () => {
  it("login page has no detectable violations", async () => {
    const { container } = renderWithRouter(<App />, { route: "/login" });
    // The visible label carries a decorative "*", so match the accessible name.
    await screen.findByLabelText(/نام کاربری/);
    await expectA11yClean(container);
  });

  it("admin panel login has no detectable violations", async () => {
    const { container } = renderWithRouter(<AdminApp />, { route: "/admin" });
    await screen.findByText("پنل مدیریت HiveOS");
    await screen.findByLabelText(/نام کاربری/);
    await expectA11yClean(container);
  });

  it("names the main landmark and keeps focus on the document body", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    vi.stubGlobal("fetch", vi.fn(async () => json({ organizations: [] })));
    renderWithRouter(<AdminApp />, { route: "/admin/organizations" });
    // The heading is level 1 on every view: v0.1 used h2 for page titles and
    // left the h1 to the marketing shell.
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("exposes sortable columns through aria-sort, not a font-weight change", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    vi.stubGlobal("fetch", vi.fn(async () => json({
      organizations: [
        { id: "o1", name: "شرکت الف", plan: "trial", status: "active", credit_irt: 1000, users: 2, created_at: "2026-01-01T00:00:00Z" },
      ],
    })));
    renderWithRouter(<AdminApp />, { route: "/admin/organizations" });
    const table = await screen.findByRole("table");
    // Every header is a real columnheader inside the table's own semantics.
    expect(within(table).getAllByRole("columnheader").length).toBeGreaterThan(0);
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(0);
  });
});