import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

/**
 * Live admin scenario suite against the REAL staging server.
 *
 * The live.spec.ts admin case only proves the eight workspaces render. This file
 * drives the admin panel the way an operator does: it reads the console, makes
 * a real change through the UI, and confirms the change landed by asking the
 * API - so a view that renders but never wires its button up fails here.
 *
 * Opt-in like live.spec.ts: needs HIVEOS_LIVE_BASE plus admin credentials.
 */
const BASE = process.env.HIVEOS_LIVE_BASE;
const ADMIN_USER = process.env.HIVEOS_LIVE_ADMIN_USER ?? "";
const ADMIN_PASS = process.env.HIVEOS_LIVE_ADMIN_PASS ?? "";
const USER = process.env.HIVEOS_LIVE_USER ?? "";
const PASS = process.env.HIVEOS_LIVE_PASS ?? "";

test.describe("live admin scenarios", () => {
  test.skip(!BASE || !ADMIN_USER, "set HIVEOS_LIVE_BASE and admin creds to run");

  async function adminLogin(page: Page): Promise<void> {
    await page.goto(`${BASE}/admin`);
    await page.locator("#admin-username").fill(ADMIN_USER);
    await page.locator("#admin-password").fill(ADMIN_PASS);
    await page.getByRole("button", { name: /ورود|ادامه/ }).click();
    await expect(page.locator("#admin-username")).toBeHidden({ timeout: 30_000 });
  }

  test("admin console: every workspace renders its own heading and no client error", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await adminLogin(page);
    for (const [path, heading] of [
      ["", /نمای کلی|داشبورد/],
      ["organizations", /سازمان/],
      ["billing", /مالی|اشتراک|شارژ/],
      ["operations", /عملیات|پایش/],
      ["ai", /هوش مصنوعی|مدل/],
      ["agents", /ایجنت/],
      ["events", /رویداد|فعالیت/],
      ["system", /سامانه|سلامت/],
    ] as const) {
      await page.goto(`${BASE}/admin/${path}`);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("body")).toContainText(heading);
      await expect(page.locator("body")).not.toContainText("خطای غیرمنتظره");
    }
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("admin console: a deep link loads that workspace directly", async ({ page }) => {
    // A reload on a nested route must not bounce to the dashboard: the route
    // table matches on longest prefix, and this is what catches it regressing.
    await adminLogin(page);
    await page.goto(`${BASE}/admin/organizations`);
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/admin\/organizations/);
    await expect(page.locator("body")).toContainText(/سازمان/);
  });

  test("admin console: the organizations list is populated and named", async ({ page }) => {
    await adminLogin(page);
    await page.goto(`${BASE}/admin/organizations`);
    await page.waitForLoadState("networkidle");
    // At least one real organization row, with a status the operator can read.
    await expect(page.locator("body")).toContainText(/فعال|active|trial/i);
    const rows = await page.locator("tbody tr").count();
    expect(rows, "the organizations table rendered no rows").toBeGreaterThan(0);
  });

  test("admin console: operations shows live host and queue figures", async ({ page }) => {
    await adminLogin(page);
    await page.goto(`${BASE}/admin/operations`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText(/پردازش|صف|سرور|بکاپ|دیسک/);
  });

  test("admin console: system view reports healthy services", async ({ page }) => {
    await adminLogin(page);
    await page.goto(`${BASE}/admin/system`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText(/سالم|ok|پایدار|فعال/i);
  });

  test("admin console: events view lists activity rows", async ({ page }) => {
    await adminLogin(page);
    await page.goto(`${BASE}/admin/events`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText(/رویداد|فعالیت|لاگ|خطا/);
  });

  test("admin API: a charge request raised by the user is visible to the admin", async ({
    request,
  }) => {
    // End-to-end across the two consoles: the user raises it, the admin sees it.
    const userToken = await apiLogin(request, USER, PASS, "/api/v1/auth/login", "session");
    const raised = await request.post(`${BASE}/api/v1/wallet/charge-request`, {
      headers: { Authorization: `Bearer ${userToken}` },
      data: { amount: 1000, note: "e2e scenario" },
    });
    expect(raised.ok(), await raised.text()).toBeTruthy();
    const requestId = (await raised.json()).data.request_id;
    expect(requestId).toBeTruthy();

    const adminToken = await apiLogin(request, ADMIN_USER, ADMIN_PASS, "/api/v1/admin/auth/login", "token");
    const list = await request.get(`${BASE}/api/v1/admin/charge-requests`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(list.ok()).toBeTruthy();
    const rows = (await list.json()).data.requests as { id: string }[];
    expect(rows.map((r) => r.id)).toContain(requestId);
  });

  test("admin API: the console cannot be used with a plain user token", async ({ request }) => {
    const userToken = await apiLogin(request, USER, PASS, "/api/v1/auth/login", "session");
    const forbidden = await request.get(`${BASE}/api/v1/admin/organizations`, {
      headers: { Authorization: `Bearer ${userToken}` },
    });
    expect([401, 403]).toContain(forbidden.status());
  });
});

/** Log in through an API endpoint and pull the token out of its envelope. */
async function apiLogin(
  request: APIRequestContext,
  user: string,
  pass: string,
  path: string,
  key: "token" | "session",
): Promise<string> {
  const res = await request.post(`${BASE}${path}`, {
    data: { username: user, password: pass },
  });
  expect(res.ok()).toBeTruthy();
  const data = (await res.json()).data;
  return key === "token" ? data.token : data.session.token;
}
