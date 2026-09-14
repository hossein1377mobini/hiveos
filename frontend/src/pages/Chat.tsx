import { AlertCircle, Copy, FileText, House, Plus, Search, Send } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { LoadingButton } from "../components/ui/button-loading";
import { Input } from "../components/ui/input";
import { ZeroCreditBanner } from "../components/ZeroCreditBanner";
import { faDate, faTime, norm } from "../utils/format";

// 09-conversation mockups (01/02/03) at mockup fidelity: chat-list rail with
// search + relative groups, thread with msg pattern (32px avatar, name+time,
// bubble, cite-cards, copy action), composer with icon send + hint, chat-empty
// with suggestions. Business logic unchanged (chat session + execution run,
// US-0909 reply persistence on the server).
interface SessionItem {
  id: string;
  title: string | null;
  status: string;
  created_at: string;
}

/**
 * The transcript row exactly as GET /chat/sessions/{id}/messages returns it.
 *
 * The property is "content" and it is an OBJECT carrying the text, not a
 * string: hiveos.chat_messages.content is a JSON column (models/chat.py) and
 * _message_payload passes it through untouched, so the wire shape is
 * {"content": {"text": "..."}}. The client read "body.text" instead, which
 * dereferenced undefined and threw "Cannot read properties of undefined
 * (reading 'text')" on the first paint of any conversation.
 *
 * Verified against the running API, not the ORM:
 *   GET /chat/sessions/{id}/messages
 *   {"id":"ac63...","role":"USER","content":{"text":"salam"},"citations":[],...}
 */
interface ChatMessage {
  id: string;
  role: string;
  content: { text?: string } | null;
  citations?: Citation[] | null;
  created_at: string;
}

/** The text of a message, tolerating a null content or a missing text key. */
function messageText(message: ChatMessage): string {
  return message.content?.text ?? "";
}

interface WalletMini {
  balance: number;
  blocked: boolean;
}

interface Citation {
  title?: string;
  locator?: string;
  /** Present when the backend cites a specific stored document. */
  document_id?: string;
}

const SUGGESTS: ReadonlyArray<{ text: string; hint: string }> = [
  { text: "ساختار قیمت‌گذاری محصولات چگونه است؟", hint: "بر پایه اسناد فروش" },
  { text: "خلاصه‌ای از گزارش فروش ۱۴۰۴ بده", hint: "بر پایه اسناد سازمان" },
  { text: "شرایط تخفیف در قراردادها چیست؟", hint: "بر پایه مصوبات کمیته" },
  { text: "فعالیت‌های اصلی شرکت را توضیح بده", hint: "بر پایه توصیف کسب‌وکار" },
];

/** Mockup cl-group buckets: امروز / دیروز / ۷ روز اخیر / قدیمی‌تر. */
function sessionBucket(createdAt: string): string {
  const d = new Date(createdAt);
  if (Number.isNaN(d.getTime())) return "قدیمی‌تر";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const t = d.getTime();
  if (t >= startOfToday) return "امروز";
  if (t >= startOfToday - 86_400_000) return "دیروز";
  if (t >= startOfToday - 7 * 86_400_000) return "۷ روز اخیر";
  return "قدیمی‌تر";
}

const BUCKET_ORDER = ["امروز", "دیروز", "۷ روز اخیر", "قدیمی‌تر"];

export default function Chat() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [wallet, setWallet] = useState<WalletMini | null>(null);
  const [input, setInput] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * The last text that failed to send, so «تلاش مجدد» can resend it.
   *
   * State, not a ref: the retry affordance is rendered from this value, and a
   * ref read during render is invisible to React — the button would not appear
   * until some unrelated state change happened to re-render the tree.
   */
  const [lastSent, setLastSent] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeIdRef = useRef<string | null>(null);

  // The chat list endpoint is paginated: it answers {items, total_count, page,
  // page_size, has_more}, not {sessions}. Reading the wrong key yielded [] every
  // time, so the rail was permanently empty and history unreachable.
  const loadSessions = useCallback(async () => {
    const data = await api<{ items: SessionItem[] }>("GET", "/chat/sessions");
    setSessions(data.items ?? []);
    return data.items ?? [];
  }, []);

  const openSession = useCallback(async (id: string) => {
    activeIdRef.current = id;
    setActiveId(id);
    try {
      // Same paginated envelope as the session list: the transcript is "items".
      const data = await api<{ items: ChatMessage[] }>(
        "GET",
        "/chat/sessions/" + id + "/messages",
      );
      // Two fast rail clicks can land out of order: keep only the newest answer.
      if (activeIdRef.current !== id) return;
      setMessages(data.items ?? []);
      setError(null);
    } catch (e) {
      if (activeIdRef.current !== id) return;
      setError(e instanceof Error ? e.message : "دریافت پیام‌های گفتگو ناموفق بود.");
    }
  }, []);

  // PO request: the first load can fail (server down, expired session); the
  // page keeps the Persian reason and offers «تلاش مجدد» instead of an empty rail.
  const bootstrap = useCallback(async () => {
    try {
      const list = await loadSessions();
      if (list.length > 0) await openSession(list[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "دریافت گفتگوها ناموفق بود.");
    }
    try {
      const w = await api<WalletMini>("GET", "/wallet");
      setWallet({ balance: w.balance, blocked: w.blocked });
    } catch (e) {
      // F: swallowing this left 'blocked' at its old value — the composer and
      // the zero-credit banner could both contradict the real balance.
      setError(e instanceof Error ? e.message : "دریافت وضعیت اعتبار ناموفق بود.");
    }
  }, [loadSessions, openSession]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, busy]);

  async function newChat() {
    try {
      const data = await api<{ id: string }>("POST", "/chat/sessions", {});
      await loadSessions();
      activeIdRef.current = data.id;
      setActiveId(data.id);
      setMessages([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "ساخت گفتگو ناموفق بود.");
    }
  }

  async function send(e?: React.FormEvent, override?: string) {
    e?.preventDefault();
    // The retry button passes the failed text explicitly: reading 'input' here
    // would see the already-cleared state and the retry would silently no-op.
    const text = (override ?? input).trim();
    // A brand-new organization has no sessions, so activeId is null on the
    // first screen. This used to return here with no message and no error,
    // which made the send button look broken. Create the session on demand
    // instead - typing a question should never require a separate click.
    if (!text || busy) return;
    setLastSent(text);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      let sessionId = activeId;
      if (!sessionId) {
        const createdSession = await api<{ id: string }>("POST", "/chat/sessions", {});
        sessionId = createdSession.id;
        activeIdRef.current = sessionId;
        setActiveId(sessionId);
        await loadSessions();
      }
      await api("POST", "/chat/sessions/" + sessionId + "/messages", { text });
      setMessages((m) => [
        ...m,
        { id: "local-" + Date.now(), role: "USER", content: { text }, created_at: "" },
      ]);
      const created = await api<{ id: string }>("POST", "/executions", {
        input: { text },
        chat_session_id: sessionId,
      });
      const done = await api<{ status: string; output: { text: string } | null; error: { message: string } | null }>(
        "POST",
        "/executions/" + created.id + "/run",
      );
      if (done.status !== "COMPLETED") {
        setError(done.error?.message ?? "اجرای پاسخ ناموفق بود.");
      }
      await openSession(sessionId);
      const w = await api<WalletMini>("GET", "/wallet");
      setWallet({ balance: w.balance, blocked: w.blocked });
    } catch (e) {
      setError(e instanceof Error ? e.message : "ارسال پیام ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  const grouped = useMemo(() => {
    const q = norm(filter);
    const visible = sessions.filter((s) => !q || norm(s.title ?? "گفتگوی بدون عنوان").includes(q));
    const groups = new Map<string, SessionItem[]>();
    for (const s of visible) {
      const key = sessionBucket(s.created_at);
      const list = groups.get(key) ?? [];
      list.push(s);
      groups.set(key, list);
    }
    return BUCKET_ORDER.filter((k) => groups.has(k)).map((k) => ({ label: k, items: groups.get(k)! }));
  }, [sessions, filter]);

  const blocked = wallet?.blocked === true;

  return (
    <div className="flex min-h-0 flex-1" aria-label="گفتگو">
      {/* — chat-list (mockup §۲۰) — */}
      <aside
        className="hidden w-[280px] shrink-0 flex-col border-e border-border bg-card md:flex"
        aria-label="فهرست گفتگوها"
      >
        <div className="flex gap-2 border-b border-border p-3.5">
          <LoadingButton size="sm" className="flex-1" onClick={newChat}>
            <Plus aria-hidden />
            گفتگوی جدید
          </LoadingButton>
        </div>
        <div className="border-b border-border px-3.5 py-2.5">
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="جستجو در گفتگوها…"
              aria-label="جستجوی گفتگو"
              className="rounded-[9px] py-2 ps-9 pe-[11px] text-caption"
            />
          </div>
        </div>
        <div className="flex-1 overflow-auto p-2" aria-label="گفتگوها">
          {grouped.length === 0 && (
            <div className="px-4 py-10 text-center">
              <p className="text-caption leading-[1.9] text-muted-foreground">
                هنوز گفتگویی ندارید. با «گفتگوی جدید» اولین سوال خود را از هوش سازمان بپرسید.
              </p>
            </div>
          )}
          {grouped.map((group) => (
            <div key={group.label}>
              <div className="px-2 pb-1 pt-2.5 text-micro font-extrabold tracking-[0.4px] text-muted-foreground">
                {group.label}
              </div>
              {group.items.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => openSession(s.id)}
                  aria-current={activeId === s.id ? "true" : undefined}
                  className={
                    "relative mb-0.5 block w-full cursor-pointer rounded-[10px] p-2.5 pe-16 text-start " +
                    (activeId === s.id ? "bg-accent" : "hover:bg-secondary")
                  }
                >
                  <span
                    className={
                      "block truncate text-caption font-bold " +
                      (activeId === s.id ? "text-primary" : "text-foreground")
                    }
                  >
                    {s.title ?? "گفتگوی بدون عنوان"}
                  </span>
                  <span className="absolute end-2.5 top-2.5 text-micro text-muted-foreground">
                    {s.created_at ? faDate(s.created_at) : ""}
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* — chat-main — */}
      <section className="flex min-w-0 flex-1 flex-col bg-secondary" aria-label="پیام‌ها">
        <div className="px-[8%] pt-4">
          <ZeroCreditBanner visible={blocked} />
        </div>

        {/*
          The answer arrives as one block, not a token stream, so the whole
          transcript is a polite live region: a screen-reader user hears the new
          answer when it lands without being interrupted mid-sentence. The busy
          indicator below carries its own status role so «در حال پاسخ‌گویی…» is
          announced while the request is in flight. [E5]
        */}
        <div
          aria-live="polite"
          aria-busy={busy}
          className="min-h-0 flex-1 space-y-[18px] overflow-y-auto px-[8%] py-[26px]"
        >
          {messages.length === 0 && !busy && (
            <div className="flex h-full flex-col items-center justify-center px-[30px] text-center">
              <span
                aria-hidden
                className="mb-[18px] flex size-16 items-center justify-center rounded-[20px] bg-primary text-primary-foreground shadow-[0_10px_26px_rgba(43,58,115,0.25)]"
              >
                <House className="size-[30px]" />
              </span>
              <h2 className="text-heading font-extrabold text-foreground">هوش سازمان آماده است</h2>
              <p className="mt-2 max-w-[440px] text-caption text-muted-foreground">
                سوال خود را درباره سازمان یا اسناد آن بپرسید. پاسخ‌ها با ارجاع به منابع داده می‌شوند.
              </p>
              <div className="mt-[22px] grid max-w-[640px] grid-cols-1 gap-2.5 sm:grid-cols-2">
                {SUGGESTS.map((s) => (
                  <button
                    key={s.text}
                    type="button"
                    onClick={() => setInput(s.text)}
                    className="cursor-pointer rounded-[13px] border border-border bg-card p-[13px] pe-[15px] text-start text-caption font-semibold text-foreground shadow-card transition-colors hover:border-primary/40 hover:text-primary"
                  >
                    {s.text}
                    <span className="mt-[3px] block text-micro font-normal text-muted-foreground">{s.hint}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => {
            const isUser = m.role === "USER";
            return (
              <article
                key={m.id}
                className="group flex max-w-[820px] gap-3"
                data-testid={"msg-" + m.role.toLowerCase()}
              >
                <span
                  aria-hidden
                  className={
                    "flex size-8 shrink-0 items-center justify-center rounded-[10px] text-micro font-extrabold " +
                    (isUser
                      ? "border border-border bg-secondary text-muted-foreground"
                      : "bg-primary text-primary-foreground")
                  }
                >
                  {isUser ? "م" : <House className="size-[17px]" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2 text-micro font-extrabold text-muted-foreground">
                    {isUser ? "شما" : "هوش سازمان"}
                    {m.created_at && <span className="font-normal">{faTime(m.created_at)}</span>}
                  </div>
                  <div
                    className={
                      "rounded-[14px] border px-4 py-3.5 text-sm leading-[1.9] shadow-[0_1px_2px_rgba(28,28,25,0.04)] " +
                      (isUser ? "border-primary/40 bg-accent" : "border-border bg-card")
                    }
                  >
                    <p className="whitespace-pre-wrap">{messageText(m)}</p>
                    {m.citations && m.citations.length > 0 && (
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-dashed border-border pt-2.5" aria-label="منابع">
                        <span className="text-micro font-bold text-muted-foreground">منابع:</span>
                        {m.citations.map((c: Citation) => (
                          <span
                            // Two citations can point at the same locator in the
                            // same document, so the pair is the identity — the
                            // list index is not.
                            key={(c.document_id ?? "") + ":" + (c.locator ?? c.title ?? "")}
                            className="flex max-w-full cursor-pointer items-start gap-2 rounded-[9px] border border-border bg-secondary px-2.5 py-[7px] text-xs transition-colors hover:bg-accent"
                          >
                            <FileText aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                            <span className="min-w-0">
                              <span className="block truncate font-bold">{c.title ?? "سند"}</span>
                              {c.locator && <span className="block text-micro text-muted-foreground">{c.locator}</span>}
                            </span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {!busy && (
                    <div className="mt-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        type="button"
                        className="inline-flex cursor-pointer items-center gap-[5px] rounded-[7px] border border-transparent px-2 py-[3px] text-micro font-semibold text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                        onClick={() => void navigator.clipboard?.writeText(messageText(m))}
                        aria-label="کپی پیام"
                      >
                        <Copy aria-hidden className="size-[13px] rtl:-scale-x-100" />
                        کپی
                      </button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}

          {busy && (
            <div role="status" aria-live="polite" className="flex gap-3" data-testid="thinking">
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-primary text-primary-foreground"
              >
                <House className="size-[17px]" />
              </span>
              <div className="rounded-[14px] border border-border bg-card px-4 py-3.5 text-sm text-muted-foreground">
                در حال پاسخ‌گویی…
              </div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              data-testid="chat-error"
              className="flex max-w-[820px] items-start gap-2.5 rounded-card border border-error-border bg-error-bg px-4 py-3 text-caption text-error"
            >
              <AlertCircle aria-hidden className="mt-0.5 size-[17px] shrink-0" />
              <div>
                {error}
                {lastSent && !busy ? (
                  <div className="mt-2">
                    <LoadingButton
                      variant="secondary"
                      size="xs"
                      data-testid="chat-retry"
                      onClick={() => void send(undefined, lastSent)}
                    >
                      تلاش مجدد
                    </LoadingButton>
                  </div>
                ) : (
                  // A failed FIRST load (sessions/wallet) has no text to resend:
                  // the way out is reloading the page data.
                  <div className="mt-2">
                    <LoadingButton
                      variant="secondary"
                      size="xs"
                      data-testid="chat-reload"
                      onClick={() => void bootstrap()}
                    >
                      تلاش مجدد
                    </LoadingButton>
                  </div>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} aria-label="ارسال پیام" className="border-t border-border bg-card px-[8%] pb-[18px] pt-3.5">
          <div className="flex items-end gap-2.5 rounded-[16px] border border-border bg-card px-3 py-2.5 transition-shadow focus-within:border-primary focus-within:ring-[3px] focus-within:ring-ring/20">
            <textarea
              rows={1}
              placeholder={blocked ? "برای ادامه، حساب خود را شارژ کنید…" : "سوال خود را بپرسید…"}
              aria-label="متن پیام"
              className="max-h-40 min-h-[44px] flex-1 resize-none border-none bg-transparent px-1 py-1.5 text-sm leading-[1.7] text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-55 border-border bg-card"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              disabled={busy || blocked}
            />
            <button
              type="submit"
              disabled={busy || blocked || input.trim().length === 0}
              className="flex size-10 shrink-0 cursor-pointer items-center justify-center rounded-[12px] transition-colors disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-muted-foreground bg-primary text-primary-foreground hover:bg-primary/90"
              data-testid="send"
              aria-label="ارسال"
            >
              <Send aria-hidden className="size-[18px] rtl:-scale-x-100" />
            </button>
          </div>
          <div className="mt-2 flex items-center gap-2.5 px-1 text-micro text-muted-foreground">
            <span>برای ارسال Enter، برای خط جدید Shift+Enter</span>
          </div>
        </form>
      </section>
    </div>
  );
}