import { AlertCircle, Copy, FileText, House, Plus, Search, Send } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { ZeroCreditBanner } from "./Wallet";
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

interface ChatMessage {
  id: string;
  role: string;
  body: { text?: string; citations?: Array<{ title?: string; locator?: string }> };
  created_at: string;
}

interface WalletMini {
  balance: number;
  blocked: boolean;
}

interface Citation {
  title?: string;
  locator?: string;
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
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastSentRef = useRef<string>("");

  const loadSessions = useCallback(async () => {
    const data = await api<{ sessions: SessionItem[] }>("GET", "/chat/sessions");
    setSessions(data.sessions ?? []);
    return data.sessions ?? [];
  }, []);

  const openSession = useCallback(async (id: string) => {
    setActiveId(id);
    const data = await api<{ messages: ChatMessage[] }>(
      "GET",
      "/chat/sessions/" + id + "/messages",
    );
    setMessages(data.messages ?? []);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const list = await loadSessions();
        if (list.length > 0) await openSession(list[0].id);
      } catch {
        setError("دریافت گفتگوها ناموفق بود.");
      }
      try {
        const w = await api<WalletMini>("GET", "/wallet");
        setWallet({ balance: w.balance, blocked: w.blocked });
      } catch {
        /* wallet view shows the error itself */
      }
    })();
  }, [loadSessions, openSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, busy]);

  async function newChat() {
    try {
      const data = await api<{ id: string }>("POST", "/chat/sessions", {});
      await loadSessions();
      setActiveId(data.id);
      setMessages([]);
    } catch {
      setError("ساخت گفتگو ناموفق بود.");
    }
  }

  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || !activeId || busy) return;
    lastSentRef.current = text;
    setInput("");
    setBusy(true);
    setError(null);
    try {
      await api("POST", "/chat/sessions/" + activeId + "/messages", { text });
      setMessages((m) => [
        ...m,
        { id: "local-" + Date.now(), role: "USER", body: { text }, created_at: "" },
      ]);
      const created = await api<{ id: string }>("POST", "/executions", {
        input: { text },
        chat_session_id: activeId,
      });
      const done = await api<{ status: string; output: { text: string } | null; error: { message: string } | null }>(
        "POST",
        "/executions/" + created.id + "/run",
      );
      if (done.status !== "COMPLETED") {
        setError(done.error?.message ?? "اجرای پاسخ ناموفق بود.");
      }
      await openSession(activeId);
      const w = await api<WalletMini>("GET", "/wallet");
      setWallet({ balance: w.balance, blocked: w.blocked });
    } catch {
      setError("ارسال پیام ناموفق بود.");
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
        className="hidden w-[280px] shrink-0 flex-col border-e border-neutral-200 bg-neutral-0 md:flex"
        aria-label="فهرست گفتگوها"
      >
        <div className="flex gap-2 border-b border-neutral-200 p-3.5">
          <Button size="sm" className="flex-1" onClick={newChat}>
            <Plus aria-hidden />
            گفتگوی جدید
          </Button>
        </div>
        <div className="border-b border-neutral-200 px-3.5 py-2.5">
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="جستجو در گفتگوها…"
              aria-label="جستجوی گفتگو"
              className="rounded-[9px] py-2 ps-9 pe-[11px] text-[13px]"
            />
          </div>
        </div>
        <div className="flex-1 overflow-auto p-2" aria-label="گفتگوها">
          {grouped.length === 0 && (
            <div className="px-4 py-10 text-center">
              <p className="text-[13px] leading-[1.9] text-neutral-600">
                هنوز گفتگویی ندارید. با «گفتگوی جدید» اولین سوال خود را از هوش سازمان بپرسید.
              </p>
            </div>
          )}
          {grouped.map((group) => (
            <div key={group.label}>
              <div className="px-2 pb-1 pt-2.5 text-[10.5px] font-extrabold tracking-[0.4px] text-neutral-400">
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
                    (activeId === s.id ? "bg-navy-50" : "hover:bg-neutral-50")
                  }
                >
                  <span
                    className={
                      "block truncate text-[13px] font-bold " +
                      (activeId === s.id ? "text-navy-600" : "text-neutral-900")
                    }
                  >
                    {s.title ?? "گفتگوی بدون عنوان"}
                  </span>
                  <span className="absolute end-2.5 top-2.5 text-[10px] text-neutral-400">
                    {s.created_at ? faDate(s.created_at) : ""}
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* — chat-main — */}
      <section className="flex min-w-0 flex-1 flex-col bg-neutral-50" aria-label="پیام‌ها">
        <div className="px-[8%] pt-4">
          <ZeroCreditBanner visible={blocked} />
        </div>

        <div className="min-h-0 flex-1 space-y-[18px] overflow-y-auto px-[8%] py-[26px]">
          {messages.length === 0 && !busy && (
            <div className="flex h-full flex-col items-center justify-center px-[30px] text-center">
              <span
                aria-hidden
                className="mb-[18px] flex size-16 items-center justify-center rounded-[20px] bg-navy-600 text-white shadow-[0_10px_26px_rgba(43,58,115,0.25)]"
              >
                <House className="size-[30px]" />
              </span>
              <h2 className="text-[19px] font-extrabold text-neutral-900">هوش سازمان آماده است</h2>
              <p className="mt-2 max-w-[440px] text-[13.5px] text-neutral-600">
                سوال خود را درباره سازمان یا اسناد آن بپرسید. پاسخ‌ها با ارجاع به منابع داده می‌شوند.
              </p>
              <div className="mt-[22px] grid max-w-[640px] grid-cols-1 gap-2.5 sm:grid-cols-2">
                {SUGGESTS.map((s) => (
                  <button
                    key={s.text}
                    type="button"
                    onClick={() => setInput(s.text)}
                    className="cursor-pointer rounded-[13px] border border-neutral-200 bg-neutral-0 p-[13px] pe-[15px] text-start text-[13px] font-semibold text-neutral-900 shadow-card transition-colors hover:bg-navy-50 hover:text-navy-600"
                  >
                    {s.text}
                    <span className="mt-[3px] block text-[11px] font-normal text-neutral-400">{s.hint}</span>
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
                    "flex size-8 shrink-0 items-center justify-center rounded-[10px] text-[11px] font-extrabold " +
                    (isUser
                      ? "border border-neutral-200 bg-neutral-50 text-neutral-600"
                      : "bg-navy-600 text-white")
                  }
                >
                  {isUser ? "م" : <House className="size-[17px]" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2 text-[11.5px] font-extrabold text-neutral-400">
                    {isUser ? "شما" : "هوش سازمان"}
                    {m.created_at && <span className="font-normal">{faTime(m.created_at)}</span>}
                  </div>
                  <div
                    className={
                      "rounded-[14px] border px-4 py-3.5 text-sm leading-[1.9] shadow-[0_1px_2px_rgba(28,28,25,0.04)] " +
                      (isUser ? "border-navy-200 bg-navy-50" : "border-neutral-200 bg-neutral-0")
                    }
                  >
                    <p className="whitespace-pre-wrap">{m.body.text}</p>
                    {m.body.citations && m.body.citations.length > 0 && (
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-dashed border-neutral-200 pt-2.5" aria-label="منابع">
                        <span className="text-[11px] font-bold text-neutral-400">منابع:</span>
                        {m.body.citations.map((c: Citation, i: number) => (
                          <span
                            key={i}
                            className="flex max-w-full cursor-pointer items-start gap-2 rounded-[9px] border border-neutral-200 bg-neutral-50 px-2.5 py-[7px] text-xs transition-colors hover:bg-navy-50"
                          >
                            <FileText aria-hidden className="mt-0.5 size-3.5 shrink-0 text-neutral-400" />
                            <span className="min-w-0">
                              <span className="block truncate font-bold">{c.title ?? "سند"}</span>
                              {c.locator && <span className="block text-[11px] text-neutral-400">{c.locator}</span>}
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
                        className="inline-flex cursor-pointer items-center gap-[5px] rounded-[7px] border border-transparent px-2 py-[3px] text-[11.5px] font-semibold text-neutral-400 transition-colors hover:border-neutral-200 hover:bg-neutral-50 hover:text-neutral-600"
                        onClick={() => void navigator.clipboard?.writeText(m.body.text ?? "")}
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
            <div className="flex gap-3" data-testid="thinking">
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-navy-600 text-white"
              >
                <House className="size-[17px]" />
              </span>
              <div className="rounded-[14px] border border-neutral-200 bg-neutral-0 px-4 py-3.5 text-sm text-neutral-600">
                در حال پاسخ‌گویی…
              </div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              data-testid="chat-error"
              className="flex max-w-[820px] items-start gap-2.5 rounded-[14px] border border-error bg-error-bg px-4 py-3 text-[13px] text-error"
            >
              <AlertCircle aria-hidden className="mt-0.5 size-[17px] shrink-0" />
              <div>
                {error}
                {lastSentRef.current && !busy && (
                  <div className="mt-2">
                    <Button variant="secondary" size="xs" onClick={() => { setInput(lastSentRef.current); void send(); }}>
                      تلاش مجدد
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} aria-label="ارسال پیام" className="border-t border-neutral-200 bg-neutral-0 px-[8%] pb-[18px] pt-3.5">
          <div className="flex items-end gap-2.5 rounded-[16px] border border-neutral-200 bg-neutral-0 px-3 py-2.5 transition-shadow focus-within:border-navy-600 focus-within:ring-[3px] focus-within:ring-navy-50">
            <textarea
              rows={1}
              placeholder={blocked ? "برای ادامه، حساب خود را شارژ کنید…" : "سوال خود را بپرسید…"}
              aria-label="متن پیام"
              className="max-h-40 min-h-[44px] flex-1 resize-none border-none bg-transparent px-1 py-1.5 text-sm leading-[1.7] text-neutral-900 outline-none placeholder:text-neutral-400 disabled:opacity-55"
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
              className="flex size-10 shrink-0 cursor-pointer items-center justify-center rounded-[12px] bg-navy-600 text-white transition-colors hover:bg-navy-800 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
              data-testid="send"
              aria-label="ارسال"
            >
              <Send aria-hidden className="size-[18px] rtl:-scale-x-100" />
            </button>
          </div>
          <div className="mt-2 flex items-center gap-2.5 px-1 text-[11px] text-neutral-400">
            <span>برای ارسال Enter، برای خط جدید Shift+Enter</span>
          </div>
        </form>
      </section>
    </div>
  );
}
