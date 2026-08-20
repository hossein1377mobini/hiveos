import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import RegisterOrganization from "./RegisterOrganization";
import { fillValidOrg, ORG_NAME, WHAT, PRODUCTS, API_KEY } from "../test/helpers";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      createOrganization: vi.fn(),
      createOwner: vi.fn(),
      sendOtp: vi.fn(),
      verifyOtp: vi.fn(),
      initializeWorkspace: vi.fn(),
      initializeBrain: vi.fn(),
      configureIngestion: vi.fn(),
      getIngestionStatus: vi.fn(),
      listDocuments: vi.fn(),
      getOnboardingStatus: vi.fn(),
      completeOnboarding: vi.fn(),
    },
  };
});

const createOrg = () => vi.mocked(api.createOrganization);

function renderForm() {
  const onDone = vi.fn();
  render(<RegisterOrganization onDone={onDone} />);
  return onDone;
}

describe("RegisterOrganization", () => {
  beforeEach(() => {
    createOrg().mockReset();
  });

  const submit = () => screen.getByRole("button", { name: "ساخت سازمان" });

  it("shows an error for an empty displayName", async () => {
    renderForm();
    await userEvent.click(submit());
    expect(await screen.findByText("نام سازمان باید حداقل ۳ نویسه باشد.")).toBeInTheDocument();
    expect(createOrg()).not.toHaveBeenCalled();
  });

  it("shows an error for a displayName shorter than 3 characters", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByPlaceholderText(/شرکت/), "اب");
    await user.click(submit());
    expect(await screen.findByText("نام سازمان باید حداقل ۳ نویسه باشد.")).toBeInTheDocument();
  });

  it("shows an error for a short whatYouDo / productsServices description", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByPlaceholderText(/شرکت/), "آریا");
    await user.selectOptions(screen.getAllByRole("combobox")[0], "فناوری اطلاعات");
    await user.selectOptions(screen.getAllByRole("combobox")[1], "10_to_49");
    const [what] = screen.getAllByPlaceholderText(/توضیح دهید/);
    await user.type(what, "کوتاه");
    await user.click(submit());
    expect(await screen.findByText("توصیف سازمان باید حداقل ۱۰ نویسه باشد.")).toBeInTheDocument();
    expect(createOrg()).not.toHaveBeenCalled();
  });

  it("requires an API key when a real provider is selected", async () => {
    const user = userEvent.setup();
    renderForm();
    await fillValidOrg(user);
    // clear the api key (provider is already a real provider: DeepSeek default)
    const apiKeyInput = screen.getByPlaceholderText(/^sk/);
    await user.clear(apiKeyInput);
    await user.click(submit());
    expect(await screen.findByText("کلید هوش مصنوعی را وارد کنید.")).toBeInTheDocument();
    expect(createOrg()).not.toHaveBeenCalled();
  });

  it("on valid submit calls api.createOrganization with the correct payload and invokes onDone", async () => {
    const user = userEvent.setup();
    const onDone = renderForm();
    const org = {
      id: "org-1",
      name: ORG_NAME,
      status: "pending",
      tenantId: "t1",
      workspaceId: "w1",
      createdAt: "2026-08-19T00:00:00Z",
    };
    createOrg().mockResolvedValue(org);

    await fillValidOrg(user);
    await user.click(submit());

    await waitFor(() => expect(createOrg()).toHaveBeenCalledTimes(1));
    expect(createOrg()).toHaveBeenCalledWith(
      expect.objectContaining({
        displayName: ORG_NAME,
        industry: "فناوری اطلاعات",
        companySize: "10_to_49",
        businessDescription: { whatYouDo: WHAT, productsServices: PRODUCTS },
        aiModel: { provider: "DeepSeek", apiKey: API_KEY },
      }),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(org));
  });
});
