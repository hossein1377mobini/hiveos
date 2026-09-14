import { expect, test, type Page } from "@playwright/test";

/**
 * End-to-end coverage for the flows that only exist once the real app runs.
 * [F3]
 *
 * Everything here is deliberately something a jsdom test cannot prove:
 *  - the router resolving a URL and the guard redirecting,
 *  - the RTL shell laying out with a real containing block,
 *  - a form POSTing and then navigating,
 *  - the document's own security posture (lang/dir/colour-scheme).
 */

const READY = {
  organization_status: "active",
  expired: false,
  workspace_ready: true,
  brain_ready: true,
  knowledge_source: { id: "s1", path: "C:/docs", status: "active" },
  subscription: { plan: "pro", expires_at: "2027-01-01T00:00:00Z", expired: false },
  identity: {
    user_name: "manager.ar",
    organization_name: "شرکت داده‌پرداز آریا",
    plan_label: "pro",
  },
};

/** Stubs the API at the network layer so no backend is needed. */
async function stubApi(
  page: Page,
  routes: Record<string, unknown>,
  options: { status?: number } = {},
): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const key = route.request().method() + " " + url.pathname.replace("/api/v1", "");
    const value = routes[key];
    const body =
      value === undefined
        ? { success: false, error: { code: "UNEXPECTED", message: "no stub for " + key } }
        : { success: true, data: value, message: null };
    await route.fulfill({
      status: value === undefined ? 500 : (options.status ?? 200),
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test.describe("document shell", () => {
  test("declares Persian RTL and light-only colour scheme", async ({ page }) => {
    // These are what makes the whole product render correctly, and they are set
    // in index.html - the one file no component test ever reads.
    await page.goto("/login");
    const html = page.locator("html");
    await expect(html).toHaveAttribute("lang", "fa");
    await expect(html).toHaveAttribute("dir", "rtl");

    const scheme = await page
      .locator('meta[name="color-scheme"]')
      .getAttribute("content");
    expect(scheme).toBe("light");

    // A theme toggle must not exist: the PO removed dark mode deliberately.
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  });

  test("serves the self-hosted font, not a CDN", async ({ page }) => {
    // G1/G2: an air-gapped install cannot reach a CDN, so a CDN reference here
    // would render the product in Tahoma forever without any visible error.
    const external: string[] = [];
    page.on("request", (request) => {
      const host = new URL(request.url()).host;
      if (host && host !== "localhost:4173") external.push(request.url());
    });

    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    const cdn = external.filter((u) => /cdn|jsdelivr|fonts\.googleapis/.test(u));
    expect(cdn, "no third-party font/CDN request may occur").toEqual([]);
  });
});

test.describe("session guard", () => {
  test("redirects an anonymous visitor to login", async ({ page }) => {
    await stubApi(page, {});
    await page.goto("/wallet");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("ورود به HiveOS")).toBeVisible();
  });

  test("keeps a signed-in visitor on the requested route", async ({ page }) => {
    await stubApi(page, {
      "GET /auth/onboarding-status": READY,
      "GET /chat/sessions": { sessions: [] },
      "GET /wallet": { balance: 1000, pending: 0 },
      "GET /usage": { usage: [] },
    });
    await page.addInitScript(() => localStorage.setItem("hiveos.session", "e2e-token"));

    await page.goto("/wallet");
    await expect(page).toHaveURL(/\/wallet$/);
    // The shell header names the real account (H1) rather than a hardcoded role.
    await expect(page.getByText("manager.ar")).toBeVisible();
  });

  test("an expired session lands back on login instead of an empty page", async ({
    page,
  }) => {
    // The API client clears the token and redirects on 401; without this the
    // user would sit on a shell that renders nothing and never explains why.
    await page.addInitScript(() => localStorage.setItem("hiveos.session", "stale"));
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          success: false,
          error: { code: "SESSION_EXPIRED", message: "expired" },
        }),
      }),
    );

    await page.goto("/chat");
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe("login", () => {
  test("submits and lands in the app", async ({ page }) => {
    await stubApi(page, {
      "POST /auth/login": {
        session: { token: "fresh-token", expires_at: "2027-01-01T00:00:00Z" },
      },
      "GET /auth/onboarding-status": READY,
      "GET /chat/sessions": { sessions: [] },
    });

    await page.goto("/login");
    await page.getByLabel("نام کاربری").fill("manager.ar");
    await page.getByLabel("رمز عبور").fill("Str0ng!Pass");
    await page.getByRole("button", { name: "ورود" }).click();

    // Login lands on the bootstrap route, not directly on a screen: the server
    // decides where the organisation actually is in the flow.
    await expect(page).toHaveURL(/\/(\?|$)/);
    await expect(page.getByText("manager.ar")).toBeVisible();
  });

  test("shows the server's own reason, not a guessed one", async ({ page }) => {
    // D-finding: the banner used to be a hardcoded "wrong password", so a rate
    // limit or an outage was reported as bad credentials.
    await page.route("**/api/v1/auth/login", (route) =>
      route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({
          success: false,
          error: {
            code: "RATE_LIMITED",
            message: "Too many attempts. Try again later.",
          },
        }),
      }),
    );

    await page.goto("/login");
    await page.getByLabel("نام کاربری").fill("manager.ar");
    await page.getByLabel("رمز عبور").fill("wrong");
    await page.getByRole("button", { name: "ورود" }).click();

    // The Persian message registered for RATE_LIMITED, not the password wording.
    await expect(page.getByText("تعداد درخواست‌ها زیاد بود")).toBeVisible();
    await expect(page.getByText("نام کاربری یا رمز عبور درست نیست")).toHaveCount(0);
  });
});

test.describe("admin panel", () => {
  test("is reachable on its own URL and shows its own login", async ({ page }) => {
    await stubApi(page, {});
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "پنل مدیریت HiveOS" })).toBeVisible();
  });
});

test.describe("accessibility", () => {
  test("login page has exactly one main landmark and labelled fields", async ({
    page,
  }) => {
    await page.goto("/login");
    await expect(page.getByRole("main")).toHaveCount(1);
    // axe caught this class of bug in jsdom too, but only a browser proves the
    // label is actually associated after layout and Radix portals run.
    await expect(page.getByLabel("نام کاربری")).toBeEditable();
    await expect(page.getByLabel("رمز عبور")).toBeEditable();
  });
});
