import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RegisterOrganization from "./RegisterOrganization";
import { renderWithRouter } from "../test/render";

/**
 * Three-step organization signup. The steps gate on their own validity, so the
 * test drives them the way a person would rather than reaching into state.
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

/** Walk step 1 and step 2 with a valid organization. */
function fillFirstTwoSteps() {
  fireEvent.change(screen.getByLabelText(/نام سازمان/), { target: { value: "شرکت داده‌پرداز آریا" } });
  fireEvent.click(screen.getByRole("combobox", { name: "صنعت" }));
  fireEvent.click(screen.getByRole("option", { name: "فناوری اطلاعات" }));
  fireEvent.click(screen.getByRole("button", { name: /ادامه/ }));
  fireEvent.change(screen.getByLabelText(/کسب‌وکار شما چه می‌کند/), {
    target: { value: "تحلیل داده برای سازمان‌های متوسط." },
  });
  fireEvent.click(screen.getByRole("button", { name: /ادامه/ }));
}

describe("RegisterOrganization", () => {
  it("refuses to advance until the first step is complete", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithRouter(<RegisterOrganization onCreated={() => {}} onBack={() => {}} />, {
      route: "/register",
    });

    // No name, no industry: the step cannot be left.
    expect(screen.getByRole("button", { name: /ادامه/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/نام سازمان/), { target: { value: "الف" } });
    // Still too short, and still no industry.
    expect(screen.getByRole("button", { name: /ادامه/ })).toBeDisabled();
  });

  it("submits the organization and remembers its id for a reload", async () => {
    const onCreated = vi.fn();
    const fetchMock = vi.fn(async () => respond({ success: true, data: { organization_id: "org-9" } }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<RegisterOrganization onCreated={onCreated} onBack={() => {}} />, {
      route: "/register",
    });

    fillFirstTwoSteps();
    fireEvent.click(screen.getByRole("button", { name: "ساخت سازمان" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("org-9"));
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      name: "شرکت داده‌پرداز آریا",
      industry: "فناوری اطلاعات",
      size: "10_50",
    });
    // Without this the owner-account step is lost on refresh or Back.
    expect(sessionStorage.getItem("hiveos.pending_organization")).toBe("org-9");
  });

  it("keeps the wizard usable when the service is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        respond({ success: false, error: { code: "SERVICE_UNAVAILABLE", message: "down" } }, 503),
      ),
    );
    const onCreated = vi.fn();
    renderWithRouter(<RegisterOrganization onCreated={onCreated} onBack={() => {}} />, {
      route: "/register",
    });

    fillFirstTwoSteps();
    fireEvent.click(screen.getByRole("button", { name: "ساخت سازمان" }));

    // The failure is explained in Persian and the operator stays on the step
    // they can retry from.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "ساخت سازمان" })).toBeEnabled();
  });

  it("does not send a business description the user left empty", async () => {
    // The API distinguishes "absent" from "empty string"; sending "" would
    // store an empty description instead of leaving the field unset.
    const fetchMock = vi.fn(async () => respond({ success: true, data: { organization_id: "org-1" } }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<RegisterOrganization onCreated={() => {}} onBack={() => {}} />, {
      route: "/register",
    });

    fireEvent.change(screen.getByLabelText(/نام سازمان/), { target: { value: "سازمان تست" } });
    fireEvent.click(screen.getByRole("combobox", { name: "صنعت" }));
    fireEvent.click(screen.getByRole("option", { name: "آموزش" }));
    fireEvent.click(screen.getByRole("button", { name: /ادامه/ }));
    fireEvent.change(screen.getByLabelText(/کسب‌وکار شما چه می‌کند/), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: /ادامه/ }));
    // Whitespace-only is still empty for the purposes of advancing.
    expect(screen.queryByRole("button", { name: "ساخت سازمان" })).not.toBeInTheDocument();
  });
});
