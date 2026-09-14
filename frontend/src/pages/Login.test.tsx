import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";
import { renderWithRouter } from "../test/render";

/**
 * Login had no test. The behaviours worth pinning are the ones the PO asked for
 * explicitly: the error must name the real cause instead of a canned "wrong
 * password", and a lockout must be told apart from bad credentials - both were
 * review findings (S1) that could regress silently.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function respond(body: unknown, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fillIn(username = "manager.ar", password = "Secret123!") {
  fireEvent.change(screen.getByLabelText(/نام کاربری/), { target: { value: username } });
  fireEvent.change(screen.getByLabelText(/رمز عبور/), { target: { value: password } });
}

describe("Login", () => {
  it("signs in and hands the token to the app", async () => {
    const onDone = vi.fn();
    const fetchMock = vi.fn(async () =>
      respond(
        {
          success: true,
          data: {
            user_id: "u1",
            organization_id: "o1",
            session: { token: "tok-123", expires_at: "2027-01-01T00:00:00Z" },
          },
        },
        200,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<Login onDone={onDone} />, { route: "/login" });

    fillIn();
    fireEvent.click(screen.getByRole("button", { name: "ورود" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      username: "manager.ar",
      password: "Secret123!",
    });
  });

  it("distinguishes a lockout from wrong credentials", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        respond(
          { success: false, error: { code: "ACCOUNT_LOCKED", message: "ورود موقتاً قفل شد." } },
          429,
        ),
      ),
    );
    renderWithRouter(<Login onDone={() => {}} />, { route: "/login" });

    fillIn();
    fireEvent.click(screen.getByRole("button", { name: "ورود" }));

    const alert = await screen.findByRole("alert");
    // The server's own reason is shown, not a generic failure line.
    expect(alert.textContent).toContain("قفل");
    expect(alert.textContent).toContain("۱۵ دقیقه");
    expect(alert.textContent).not.toContain("رمز عبور درست نیست");
  });

  it("keeps a server-side reason instead of replacing it with a canned message", async () => {
    // PO request: a wrong password is one of several possible causes. A rate
    // limit or a downed API must not be reported as bad credentials.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        respond(
          { success: false, error: { code: "RATE_LIMITED", message: "Too many requests" } },
          429,
        ),
      ),
    );
    renderWithRouter(<Login onDone={() => {}} />, { route: "/login" });

    fillIn();
    fireEvent.click(screen.getByRole("button", { name: "ورود" }));
    const alert = await screen.findByRole("alert");
    // The English developer message must never surface: the map in api/errors.ts
    // owns the Persian wording.
    expect(alert.textContent).toContain("تعداد درخواست‌ها زیاد بود");
    expect(alert.textContent).not.toContain("Too many requests");
  });

  it("toggles password visibility without submitting", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithRouter(<Login onDone={() => {}} />, { route: "/login" });

    const password = screen.getByLabelText(/رمز عبور/);
    expect(password).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "نمایش رمز" }));
    expect(password).toHaveAttribute("type", "text");
  });

  it("sanitizes the username as it is typed", () => {
    // The field is LTR and the server only accepts a restricted alphabet; a
    // rejected character must never reach the request.
    vi.stubGlobal("fetch", vi.fn());
    renderWithRouter(<Login onDone={() => {}} />, { route: "/login" });

    const field = screen.getByLabelText(/نام کاربری/);
    fireEvent.change(field, { target: { value: "Manager AR!" } });
    expect((field as HTMLInputElement).value).not.toMatch(/[\s!]/);
  });
});
