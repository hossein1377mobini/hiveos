import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithRouter } from "../test/render";
import Chat from "./Chat";

function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split("?")[0];
    const method = (init?.method ?? "GET").toUpperCase();
    const key = method + " " + url.replace("/api/v1", "");
    const value = routes[key];
    if (value === undefined) throw new Error("unexpected call: " + key);
    const failure = value as { status?: number | string; code?: string; message?: string };
    const body = failure.code
      ? { success: false, error: { code: failure.code, message: failure.message ?? "" } }
      : { success: true, data: value, message: null };
    // Only a numeric status is an HTTP status. Payloads carry their own
    // "status" field (an execution's COMPLETED, for example) and reading that
    // as a response code made the runner throw instead of returning a body.
    const httpStatus = typeof failure.status === "number" ? failure.status : 200;
    return new Response(JSON.stringify(body), {
      status: httpStatus,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  // The page remembers the open conversation per tab. jsdom shares one
  // sessionStorage across the tests in this file, so a value left by an earlier
  // test would be read back by the next one's bootstrap and make an assertion
  // about "nothing was remembered" pass or fail for the wrong reason.
  sessionStorage.clear();
});

describe("Chat page (RG-14)", () => {
  it("reports a failed credit check instead of keeping a stale banner", async () => {
    mockApi({
      "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
      "GET /wallet": { status: 500, code: "SERVER_ERROR", message: "boom" },
    });
    renderWithRouter(<Chat />);
    // PO request: the panel shows an explanatory Persian sentence for the
    // failure - never the server's English "boom", never a stale banner.
    const box = await screen.findByTestId("chat-error");
    expect(box).toHaveTextContent("خطای غیرمنتظره در سرور رخ داد");
    expect(box).not.toHaveTextContent("boom");
    // ...and a first-load failure still offers a way out.
    expect(screen.getByTestId("chat-reload")).toBeInTheDocument();
  });

  it("renders messages and disabled composer when wallet is blocked", async () => {
    mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [
          // The real server contract, copied from a live GET: "content" is an
          // object holding the text, not a string. The fixtures used to mirror
          // the client's wrong "body" shape, so the suite passed while the page
          // crashed on live data.
          { id: "m1", role: "USER", content: { text: "سلام" }, citations: [], created_at: "" },
          {
            id: "m2",
            role: "ASSISTANT",
            content: { text: "پاسخ با منبع" },
            citations: [{ title: "دستورالعمل.pdf", locator: "صفحه ۳" }],
            created_at: "",
          },
        ],
      },
      "GET /wallet": { balance: 0, blocked: true },
    });
    renderWithRouter(<Chat />);
    expect(await screen.findByText("سلام")).toBeInTheDocument();
    expect(await screen.findByText("پاسخ با منبع")).toBeInTheDocument();
    expect(screen.getByTestId("zero-credit-banner")).toBeInTheDocument();
    expect(screen.getByLabelText("متن پیام")).toBeDisabled();
    // Provenance is still reachable: the collapsed disclosure is there, and the
    // chip list behind it is what "منابع:" used to be permanently open.
    const toggle = screen.getByTestId("chat-cites-toggle");
    expect(toggle).toHaveTextContent("۱ منبع");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("دستورالعمل.pdf")).toBeInTheDocument();
    expect(screen.getByText("صفحه ۳")).toBeInTheDocument();
  });

  it("renders inline [n] markers as chips that open the matching citation", async () => {
    // The backend prompt now asks the model to cite passage numbers inline as
    // [1], [2]. Each marker becomes a superscript button; clicking it must open
    // the answer's disclosure and mark the citation it points at - and a marker
    // beyond the citation list must not throw.
    mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [
          {
            id: "m2",
            role: "ASSISTANT",
            content: { text: "نرخ رشد ۱۲٪ بود [2] و حاشیه سود کاهش یافت [9]." },
            citations: [
              { title: "گزارش فروش.pdf", locator: "صفحه ۱۲" },
              { title: "صورت‌های مالی.pdf", locator: "صفحه ۴" },
            ],
            created_at: "",
          },
        ],
      },
      "GET /wallet": { balance: 500, blocked: false },
    });
    renderWithRouter(<Chat />);

    // The literal text survives the tokenizer, markers and all.
    expect(await screen.findByText(/نرخ رشد/)).toBeInTheDocument();

    const second = screen.getByLabelText("نمایش منبع ۲: صورت‌های مالی.pdf");
    const outOfRange = screen.getByLabelText("نمایش منبع ۹");
    const toggle = screen.getByTestId("chat-cites-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(second);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // The panel is named by the toggle, and chip 2 is the one highlighted.
    expect(toggle).toHaveAttribute("aria-controls", screen.getByTestId("chat-cites-panel").id);
    expect(screen.getByTestId("chat-cite-m2-2").className).toContain("ring-2");
    expect(screen.getByTestId("chat-cite-m2-1").className).not.toContain("ring-2");

    // Out of range: nothing to highlight, and no crash.
    fireEvent.click(outOfRange);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("collapses an expanded citation list back to its summary line", async () => {
    mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [
          {
            id: "m2",
            role: "ASSISTANT",
            content: { text: "پاسخ با سه منبع" },
            citations: [
              { title: "الف.pdf" },
              { title: "ب.pdf" },
              { title: "پ.pdf" },
            ],
            created_at: "",
          },
        ],
      },
      "GET /wallet": { balance: 500, blocked: false },
    });
    renderWithRouter(<Chat />);

    const toggle = await screen.findByTestId("chat-cites-toggle");
    expect(toggle).toHaveTextContent("۳ منبع");
    fireEvent.click(toggle);
    expect(screen.getByText("الف.pdf")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("الف.pdf")).not.toBeInTheDocument();
  });

  it("sends the first message for a brand-new organization", async () => {
    // A new organization has no sessions, so activeId is null on the first
    // screen. send() used to return at that point with no message and no
    // error, which made the send button look broken - the PO's report.
    const fetchMock = mockApi({
      "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
      "GET /wallet": { balance: 500, blocked: false },
      "POST /chat/sessions": { id: "new-session" },
      "POST /chat/sessions/new-session/messages": { id: "m1" },
      "POST /executions": { id: "e1" },
      "POST /executions/e1/run": {
        status: "COMPLETED",
        output: { text: "پاسخ سرور" },
        error: null,
      },
      "GET /chat/sessions/new-session/messages": {
        items: [
          { id: "m1", role: "USER", content: { text: "سوال من" }, citations: [], created_at: "" },
          { id: "m2", role: "ASSISTANT", content: { text: "پاسخ سرور" }, citations: [], created_at: "" },
        ],
      },
    });
    renderWithRouter(<Chat />);

    const composer = await screen.findByLabelText("متن پیام");
    fireEvent.change(composer, { target: { value: "سوال من" } });
    // Enter is the path the PO uses; a jsdom click on a submit button does not
    // dispatch the form's submit event.
    fireEvent.keyDown(composer, { key: "Enter" });

    // The session is created on demand and the reply is rendered.
    expect(await screen.findByText("پاسخ سرور")).toBeInTheDocument();
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.endsWith("/chat/sessions"))).toBe(true);
    expect(calls.some((u) => u.includes("/executions/e1/run"))).toBe(true);
  });

  it("never leaves the composer silently dead when there is no session", async () => {
    // Whatever else changes, submitting with text must produce a network call:
    // a no-op submit is indistinguishable from a broken button.
    const fetchMock = mockApi({
      "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
      "GET /wallet": { balance: 500, blocked: false },
      "POST /chat/sessions": { status: 500, code: "SERVER_ERROR", message: "boom" },
    });
    renderWithRouter(<Chat />);
    const composer = await screen.findByLabelText("متن پیام");
    fireEvent.change(composer, { target: { value: "سلام" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    const box = await screen.findByTestId("chat-error");
    expect(box).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("renders a transcript shaped exactly like the API's response", async () => {
    // Regression: the component read "m.body.text" while the server sends a
    // flat "content", so opening any conversation with history threw
    // "Cannot read properties of undefined (reading 'text')" and the whole
    // chat view blanked. The fixtures in this file shared the component's
    // mistake, so nothing caught it. These payloads are copied from
    // chat/service.py:_message_payload, nulls included.
    mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [
          { id: "m1", role: "USER", content: { text: "سؤال قدیمی" }, citations: [], created_at: "" },
          {
            id: "m2",
            role: "ASSISTANT",
            content: { text: "پاسخ قدیمی" },
            // A real turn with no retrieved sources stores null, not [].
            citations: null,
            tokens: 12,
            sequence: 2,
            created_at: "",
          },
        ],
      },
      "GET /wallet": { balance: 500, blocked: false },
    });
    renderWithRouter(<Chat />);

    expect(await screen.findByText("سؤال قدیمی")).toBeInTheDocument();
    expect(await screen.findByText("پاسخ قدیمی")).toBeInTheDocument();
    // The disclosure is derived from citations, so a null list paints nothing:
    // no summary line, no panel, and nothing for the markers to point at.
    expect(screen.queryByTestId("chat-cites-toggle")).not.toBeInTheDocument();
    expect(screen.queryByText(/منبع/)).not.toBeInTheDocument();
  });

  it("survives a message whose content or text is missing", async () => {
    // The column is a JSON blob, so neither the object nor its "text" key is
    // guaranteed: a SYSTEM/TOOL row or an older row can carry {}. Reading
    // straight through would crash the transcript on data, not on a bug in
    // this component.
    mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [
          { id: "m1", role: "SYSTEM", content: null, citations: null, created_at: "" },
          { id: "m2", role: "ASSISTANT", content: {}, citations: null, created_at: "" },
          { id: "m3", role: "USER", content: { text: "پیام سالم" }, citations: [], created_at: "" },
        ],
      },
      "GET /wallet": { balance: 500, blocked: false },
    });
    renderWithRouter(<Chat />);

    // The good row still renders; the two degraded rows render empty.
    expect(await screen.findByText("پیام سالم")).toBeInTheDocument();
  });

  it("deletes a session only after confirmation, and clears the remembered view", async () => {
    // PO request: the API has always exposed DELETE /chat/sessions/{id} and the
    // UI had no way to reach it. Nothing may leave the rail before the server
    // has answered.
    // The remembered view points at the session that is about to be deleted, so
    // the test can prove the page forgets it.
    sessionStorage.setItem(
      "hiveos.chat.view",
      JSON.stringify({ sessionId: "s2", scrollTop: 0 }),
    );
    const fetchMock = mockApi({
      "GET /chat/sessions": {
        items: [
          { id: "s1", title: "گفتگوی اول", status: "ACTIVE", created_at: "" },
          { id: "s2", title: "گفتگوی دوم", status: "ACTIVE", created_at: "" },
        ],
        total_count: 2,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [{ id: "m1", role: "USER", content: { text: "پیام گفتگوی اول" }, citations: [], created_at: "" }],
      },
      "GET /chat/sessions/s2/messages": {
        items: [{ id: "m2", role: "USER", content: { text: "پیام گفتگوی دوم" }, citations: [], created_at: "" }],
      },
      "GET /wallet": { balance: 500, blocked: false },
      "DELETE /chat/sessions/s2": { id: "s2" },
    });
    renderWithRouter(<Chat />);

    // The remembered conversation is reopened, so s2 is the active one.
    expect(await screen.findByText("پیام گفتگوی دوم")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("حذف گفتگوی «گفتگوی دوم»"));
    // The gate is the product's own ConfirmDialog, not window.confirm.
    expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByTestId("confirm-submit"));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(true);
    });
    await waitFor(() => {
      expect(screen.queryByText("گفتگوی دوم")).not.toBeInTheDocument();
    });
    // The deleted one was the open one: the first remaining session is opened
    // instead, and the remembered view no longer names the deleted session, so a
    // refresh cannot try to reopen it.
    expect(await screen.findByText("پیام گفتگوی اول")).toBeInTheDocument();
    const remembered = JSON.parse(sessionStorage.getItem("hiveos.chat.view") ?? "{}");
    expect(remembered.sessionId).not.toBe("s2");
    // jsdom reports clientHeight 0, and the scroll listener that republishes the
    // open id deliberately ignores a collapsed pane, so the new id is written on
    // the next scroll rather than here. The id that matters is the cleared one.
  });

  it("keeps a session in the rail when the delete request fails", async () => {
    const fetchMock = mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: "گفتگوی اول", status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": { items: [] },
      "GET /wallet": { balance: 500, blocked: false },
      "DELETE /chat/sessions/s1": { status: 500, code: "SERVER_ERROR", message: "boom" },
    });
    renderWithRouter(<Chat />);

    fireEvent.click(await screen.findByLabelText("حذف گفتگوی «گفتگوی اول»"));
    fireEvent.click(screen.getByTestId("confirm-submit"));

    const box = await screen.findByTestId("chat-error");
    expect(box).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(true);
    // A failed delete must not remove the row it failed to delete.
    expect(screen.getAllByText("گفتگوی اول").length).toBeGreaterThan(0);
  });

  /**
   * PO report: answers arrived wearing their markdown - "پاسخ‌های چت الان با #
   * نمایش می‌ده" - and the ask was a cleaned-up format rather than the raw
   * punctuation. Everything below is about the answer being real elements.
   */
  describe("markdown answers", () => {
    /** The assistant bubble, which is where an answer is rendered. */
    const answer = () => document.querySelector('[data-testid="msg-assistant"]') as HTMLElement;

    function renderAnswer(text: string) {
      mockApi({
        "GET /chat/sessions": {
          items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
          total_count: 1,
          page: 1,
          page_size: 20,
          has_more: false,
        },
        "GET /chat/sessions/s1/messages": {
          items: [
            { id: "m1", role: "ASSISTANT", content: { text }, citations: [], created_at: "" },
          ],
        },
        "GET /wallet": { balance: 500, blocked: false },
      });
      return renderWithRouter(<Chat />);
    }

    it("renders headings, emphasis and lists without their markers", async () => {
      renderAnswer(
        "# گزارش فروش\n\n## خلاصه\n\n**رشد** ۱۲٪ و *حاشیه* کاهش یافت.\n\n" +
          "- مورد اول\n- مورد دوم\n\n1. یک\n2. دو\n\n> نقل قول",
      );
      // A reply is a section of a page that owns its own h1, so the levels
      // start at h3 - anything shallower would outrank the page's real title.
      const h3 = await screen.findByRole("heading", { level: 3, name: "گزارش فروش" });
      expect(h3).toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 4, name: "خلاصه" })).toBeInTheDocument();
      // The marker itself is gone, not merely hidden: the heading text is the
      // title alone.
      expect(h3.textContent).toBe("گزارش فروش");
      expect(screen.getByText("رشد").tagName).toBe("STRONG");
      expect(screen.getByText("حاشیه").tagName).toBe("EM");
      expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        "مورد اول",
        "مورد دوم",
        "یک",
        "دو",
      ]);
      expect(screen.getByText("نقل قول").closest("blockquote")).not.toBeNull();
      // Nothing was left behind as punctuation.
      expect(answer().textContent).not.toContain("#");
      expect(answer().textContent).not.toContain("**");
    });

    it("renders code LTR and still wires [n] markers inside formatting", async () => {
      renderAnswer(
        "**پاسخ [1]**\n\n```bash\nnpm run build -- --mode production\n```\n\n" +
          "نام فایل `hiveos.config.ts` است.",
      );
      const block = await screen.findByText("npm run build -- --mode production");
      // A code block is LTR by nature; its direction must not follow the prose.
      expect(block.closest("pre")?.getAttribute("dir")).toBe("ltr");
      const inline = screen.getByText("hiveos.config.ts");
      expect(inline.tagName).toBe("CODE");
      expect(inline.getAttribute("dir")).toBe("ltr");
      // The marker that sat inside the bold run is still an interactive chip.
      const chip = screen.getByLabelText("نمایش منبع ۱");
      expect(chip).toHaveAttribute("data-citation-marker", "1");
      // ...and it is genuinely inside the bold run, not beside it.
      const bold = answer().querySelector("strong");
      expect(bold).not.toBeNull();
      expect(bold?.textContent).toContain("پاسخ");
    });

    it("shows malformed markdown as the plain text it was", async () => {
      // Not one of these is valid markdown: a half-written bold run, an
      // unclosed code span, a heading with no space, a marker with no digit,
      // and a lone asterisk. All of it must survive as text - a parser that
      // swallows a run it could not finish loses the answer.
      const raw = "**نهایی و `کد و #هشتگ و [بی‌شماره] پایان";
      renderAnswer(raw);
      expect(await screen.findByText(/نهایی/)).toBeInTheDocument();
      // The bubble, not the whole row: the author byline ("هوش سازمان") sits
      // beside it and is not part of the answer.
      const bubble = answer().querySelector("div.rounded-card") as HTMLElement;
      // Every character the model wrote is still on screen, markers included.
      expect(bubble.textContent).toBe(raw);
      // Nothing was promoted to an element it is not.
      expect(bubble.querySelector("strong")).toBeNull();
      expect(bubble.querySelector("em")).toBeNull();
      expect(bubble.querySelector("code")).toBeNull();
      expect(bubble.querySelector("h3")).toBeNull();
    });

    it("keeps a marker that points past the citation list from breaking the answer", async () => {
      mockApi({
        "GET /chat/sessions": {
          items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
          total_count: 1,
          page: 1,
          page_size: 20,
          has_more: false,
        },
        "GET /chat/sessions/s1/messages": {
          items: [
            {
              id: "m1",
              role: "ASSISTANT",
              content: { text: "**نتیجه** [7]" },
              citations: [{ title: "الف.pdf" }],
              created_at: "",
            },
          ],
        },
        "GET /wallet": { balance: 500, blocked: false },
      });
      renderWithRouter(<Chat />);
      const chip = await screen.findByLabelText("نمایش منبع ۷");
      fireEvent.click(chip);
      // The panel opens with nothing to highlight rather than throwing.
      expect(await screen.findByTestId("chat-cites-panel")).toBeInTheDocument();
    });
  });

  /**
   * PO request: a conversation the user opened but never wrote in must not
   * exist. The client stops creating it up front; the server side of the same
   * rule is the list endpoint's own filter.
   */
  describe("empty sessions", () => {
    it("does not create a session when a new chat is opened", async () => {
      const fetchMock = mockApi({
        "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
        "GET /wallet": { balance: 500, blocked: false },
      });
      renderWithRouter(<Chat />);
      // Wait for the bootstrap to settle, so the assertion below cannot pass
      // merely because nothing has run yet.
      fireEvent.click(await screen.findByRole("button", { name: /گفتگوی جدید/ }));

      expect(await screen.findByLabelText("متن پیام")).toBeInTheDocument();
      const created = fetchMock.mock.calls.filter(
        (c) => c[1]?.method === "POST" && String(c[0]).endsWith("/chat/sessions"),
      );
      expect(created).toEqual([]);
      // Nor is a draft remembered: with no id there is nothing to remember, and
      // writing one would discard the conversation the user is returning to.
      expect(sessionStorage.getItem("hiveos.chat.view")).toBeNull();
    });

    it("creates the session on the first sent message, and only then", async () => {
      const fetchMock = mockApi({
        "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
        "GET /wallet": { balance: 500, blocked: false },
        "POST /chat/sessions": { id: "new-session" },
        "POST /chat/sessions/new-session/messages": { id: "m1" },
        "POST /executions": { id: "e1" },
        "POST /executions/e1/run": {
          status: "COMPLETED",
          output: { text: "پاسخ سرور" },
          error: null,
        },
        "GET /chat/sessions/new-session/messages": {
          items: [
            { id: "m1", role: "USER", content: { text: "سوال من" }, citations: [], created_at: "" },
            { id: "m2", role: "ASSISTANT", content: { text: "پاسخ سرور" }, citations: [], created_at: "" },
          ],
        },
      });
      renderWithRouter(<Chat />);
      fireEvent.click(await screen.findByRole("button", { name: /گفتگوی جدید/ }));
      const composer = await screen.findByLabelText("متن پیام");
      fireEvent.change(composer, { target: { value: "سوال من" } });
      fireEvent.keyDown(composer, { key: "Enter" });

      expect(await screen.findByText("پاسخ سرور")).toBeInTheDocument();
      const created = fetchMock.mock.calls.filter(
        (c) => c[1]?.method === "POST" && String(c[0]).endsWith("/chat/sessions"),
      );
      expect(created).toHaveLength(1);
      // The conversation now exists, so this visit may be returned to.
      expect(JSON.parse(sessionStorage.getItem("hiveos.chat.view") ?? "{}").sessionId).toBe(
        "new-session",
      );
    });

    it("never renders a server session that holds no messages", async () => {
      const fetchMock = mockApi({
        "GET /chat/sessions": {
          items: [
            { id: "s1", title: "خالی", status: "ACTIVE", created_at: "", message_count: 0 },
            { id: "s2", title: "گفتگوی دوم", status: "ACTIVE", created_at: "", message_count: 2 },
          ],
          total_count: 2,
          page: 1,
          page_size: 20,
          has_more: false,
        },
        "GET /chat/sessions/s2/messages": {
          items: [
            { id: "m1", role: "USER", content: { text: "پیام دوم" }, citations: [], created_at: "" },
          ],
        },
        "GET /wallet": { balance: 500, blocked: false },
      });
      renderWithRouter(<Chat />);

      // The title shows in the rail and again in the mobile header, so this is
      // a presence check rather than a single-node lookup.
      expect((await screen.findAllByText("گفتگوی دوم")).length).toBeGreaterThan(0);
      expect(screen.queryByText("خالی")).not.toBeInTheDocument();
      // It is not merely hidden: its transcript is never fetched either.
      expect(
        fetchMock.mock.calls.some((c) => String(c[0]).includes("/chat/sessions/s1/messages")),
      ).toBe(false);
    });

    it("keeps a conversation whose message count the server does not report", async () => {
      // message_count is an addition to the list payload. An older server
      // answers without it, and "unknown" must not be read as "empty" - the
      // whole history would disappear behind a version skew.
      mockApi({
        "GET /chat/sessions": {
          items: [{ id: "s1", title: "گفتگوی قدیمی", status: "ACTIVE", created_at: "" }],
          total_count: 1,
          page: 1,
          page_size: 20,
          has_more: false,
        },
        "GET /chat/sessions/s1/messages": {
          items: [
            { id: "m1", role: "USER", content: { text: "پیام قدیمی" }, citations: [], created_at: "" },
          ],
        },
        "GET /wallet": { balance: 500, blocked: false },
      });
      renderWithRouter(<Chat />);
      expect((await screen.findAllByText("گفتگوی قدیمی")).length).toBeGreaterThan(0);
    });
  });
});