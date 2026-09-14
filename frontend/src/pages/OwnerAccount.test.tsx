import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import OwnerAccount from "./OwnerAccount";
import { renderWithRouter } from "../test/render";

/**
 * The owner account is the most constrained form in the product: username
 * availability, Iranian mobile normalization, and a password policy. Each rule
 * is checked here because a false "free" or a wrongly normalized number blocks
 * the signup with no way forward.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fillOwner(
  overrides: { mobile?: string; password?: string; confirm?: string; email?: string } = {},
) {
  fireEvent.change(screen.getByLabelText(/نام کاربری/), { target: { value: "manager.ar" } });
  fireEvent.change(screen.getByLabelText(/شماره موبایل/), {
    target: { value: overrides.mobile ?? "9123456789" },
  });
  if (overrides.email !== undefined) {
    fireEvent.change(screen.getByLabelText(/ایمیل/), { target: { value: overrides.email } });
  }
  fireEvent.change(screen.getByLabelText(/^رمز عبور/), {
    target: { value: overrides.password ?? "Secret123!" },
  });
  fireEvent.change(screen.getByLabelText(/تکرار رمز عبور/), {
    target: { value: overrides.confirm ?? overrides.password ?? "Secret123!" },
  });
}

describe("OwnerAccount", () => {
  it("submits a normalized Iranian mobile and the bootstrap token", async () => {
    const onDone = vi.fn();
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
      if (String(_url).includes("username-available"))
        return respond({ success: true, data: { available: true } });
      return respond({ success: true, data: { session: { token: "boot-token" } } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(
      <OwnerAccount organizationId="org-1" onDone={onDone} onBack={() => {}} />,
      { route: "/owner" },
    );

    fillOwner();
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("boot-token"));
    const owner = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/owner"));
    const [, init] = owner as unknown as [string, RequestInit];
    // The API stores 09xxxxxxxxx; the field shows the national part with +98.
    expect(JSON.parse(String(init.body))).toMatchObject({
      organization_id: "org-1",
      username: "manager.ar",
      mobile: "09123456789",
      password: "Secret123!",
      confirm_password: "Secret123!",
    });
  });

  it("normalizes Persian digits in the mobile field", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
      if (String(_url).includes("username-available"))
        return respond({ success: true, data: { available: true } });
      return respond({ success: true, data: { session: { token: "t" } } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fillOwner({ mobile: "۰۹۱۲۳۴۵۶۷۸۹" });
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/owner"))).toBe(true),
    );
    const owner = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/owner"));
    const [, init] = owner as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body)).mobile).toBe("09123456789");
  });

  it("sends the optional email, and omits it when left empty", async () => {
    // The API accepted and unique-checked an owner email all along but the form
    // never sent one, so a duplicate could only be reported as server surprise.
    // [H3]
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
      if (String(_url).includes("username-available"))
        return respond({ success: true, data: { available: true } });
      return respond({ success: true, data: { session: { token: "t" } } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fillOwner({ email: "Manager@Example.COM" });
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/owner"))).toBe(true),
    );
    const owner = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/owner"));
    const [, init] = owner as unknown as [string, RequestInit];
    // Sent as typed; the server lowercases and validates it.
    expect(JSON.parse(String(init.body)).email).toBe("Manager@Example.COM");
  });

  it("sends null, not an empty string, when the email is left blank", async () => {
    // "" would fail the server's email validator; the field is optional and the
    // API expects absent-or-null.
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
      if (String(_url).includes("username-available"))
        return respond({ success: true, data: { available: true } });
      return respond({ success: true, data: { session: { token: "t" } } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fillOwner();
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/owner"))).toBe(true),
    );
    const owner = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/owner"));
    const [, init] = owner as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body)).email).toBeNull();
  });

  it("refuses a malformed email before it reaches the server", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      respond({ success: true, data: { available: true } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fillOwner({ email: "not-an-email" });
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));

    expect(await screen.findByText(/ایمیل معتبر نیست/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/owner"))).toBe(false);
  });

  it("refuses to submit when the two passwords differ", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      respond({ success: true, data: { available: true } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fillOwner({ password: "Secret123!", confirm: "Secret124!" });
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));

    // The mismatch is stated and nothing is sent.
    expect(await screen.findByText(/یکسان نیست/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/owner"))).toBe(false);
  });

  it("refuses a malformed mobile number", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond({ success: true, data: { available: true } })));
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fillOwner({ mobile: "12345" });
    fireEvent.click(screen.getByRole("button", { name: /ایجاد حساب/ }));
    expect(await screen.findByText(/شماره موبایل معتبر نیست/)).toBeInTheDocument();
  });

  it("shows a live password checklist", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fireEvent.change(screen.getByLabelText(/^رمز عبور/), { target: { value: "abc" } });
    // All four rules are listed with their own state, so the user can see which
    // one is still missing rather than guessing.
    expect(screen.getByText("حداقل ۸ کاراکتر")).toBeInTheDocument();
    expect(screen.getByText("یک حرف بزرگ")).toBeInTheDocument();
    expect(screen.getByText("یک عدد")).toBeInTheDocument();
    expect(screen.getByText("یک نماد")).toBeInTheDocument();
  });

  it("warns when the username is taken, and clears the warning when it is free", async () => {
    let available = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => respond({ success: true, data: { available } })),
    );
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fireEvent.change(screen.getByLabelText(/نام کاربری/), { target: { value: "taken.name" } });
    expect(await screen.findByText("این نام کاربری آزاد نیست.")).toBeInTheDocument();

    available = true;
    fireEvent.change(screen.getByLabelText(/نام کاربری/), { target: { value: "free.name" } });
    expect(await screen.findByText("این نام کاربری آزاد است.")).toBeInTheDocument();
  });

  it("ignores a stale availability answer for an older prefix", async () => {
    // A slow reply for an earlier name used to land on the current one and
    // report a free name as taken.
    const resolvers: Array<(value: Response) => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (url: string) =>
          new Promise<Response>((resolve) => {
            if (String(url).includes("free.name")) {
              resolve(respond({ success: true, data: { available: true } }));
            } else {
              resolvers.push(resolve);
            }
          }),
      ),
    );
    renderWithRouter(<OwnerAccount organizationId="org-1" onDone={() => {}} />, { route: "/owner" });

    fireEvent.change(screen.getByLabelText(/نام کاربری/), { target: { value: "taken.name" } });
    fireEvent.change(screen.getByLabelText(/نام کاربری/), { target: { value: "free.name" } });
    expect(await screen.findByText("این نام کاربری آزاد است.")).toBeInTheDocument();

    // The old request finally answers "not available" — it must be ignored.
    resolvers.forEach((resolve) => resolve(respond({ success: true, data: { available: false } })));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("این نام کاربری آزاد نیست.")).not.toBeInTheDocument();
  });
});
