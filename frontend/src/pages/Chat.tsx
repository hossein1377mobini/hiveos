import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { ZeroCreditBanner } from "./Wallet";

// 09-conversation mockups (01/02/03) at mockup fidelity: sessions rail,
// user/assistant bubbles with source cards, composer. Sends via the chat
// session + execution run cycle (US-0909 reply persistence on the server).
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

export default function Chat() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [wallet, setWallet] = useState<WalletMini | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || !activeId || busy) return;
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

  return (
    <div className="mx-auto flex h-full max-w-5xl gap-4" aria-label="گفتگو">
      <aside
        className="hidden w-56 shrink-0 flex-col gap-2 border-e border-neutral-200 pe-3 sm:flex"
        aria-label="فهرست گفتگوها"
      >
        <button
          type="button"
          onClick={newChat}
          className="rounded-control bg-navy-600 px-3 py-2 text-sm font-bold text-white"
        >
          گفتگوی جدید
        </button>
        <ul className="mt-1 space-y-1 overflow-auto">
          {sessions.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => openSession(s.id)}
                aria-current={activeId === s.id ? "true" : undefined}
                className={
                  "w-full rounded-control px-3 py-2 text-start text-sm " +
                  (activeId === s.id
                    ? "bg-navy-50 font-bold text-navy-700"
                    : "text-neutral-600 hover:bg-neutral-50")
                }
              >
                {s.title ?? "گفتگوی بدون عنوان"}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col" aria-label="پیام‌ها">
        <ZeroCreditBanner visible={wallet?.blocked ?? false} />

        <div className="mt-2 min-h-0 flex-1 space-y-3 overflow-auto pe-1">
          {messages.length === 0 && !busy && (
            <p className="mt-6 text-center text-sm text-neutral-500">
              سوال خود را بپرسید؛ پاسخ بر اساس دانش سازمان داده می‌شود.
            </p>
          )}
          {messages.map((m) => (
            <article
              key={m.id}
              className={m.role === "USER" ? "flex flex-row-reverse gap-2" : "flex gap-2"}
              data-testid={"msg-" + m.role.toLowerCase()}
            >
              <span
                className={
                  "mt-1 flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-bold " +
                  (m.role === "USER" ? "bg-navy-50 text-navy-700" : "bg-gold-100 text-gold-700")
                }
              >
                {m.role === "USER" ? "م" : "ه"}
              </span>
              <div className="max-w-[85%] rounded-card border border-neutral-200 bg-neutral-0 p-3 text-sm shadow-card">
                <p className="whitespace-pre-wrap">{m.body.text}</p>
                {m.body.citations && m.body.citations.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1" aria-label="منابع">
                    <span className="text-xs text-neutral-500">منابع:</span>
                    {m.body.citations.map((c: Citation, i: number) => (
                      <span
                        key={i}
                        className="rounded-control bg-neutral-50 px-2 py-1 text-xs text-neutral-700"
                      >
                        {c.title ?? "سند"}
                        {c.locator ? " · " + c.locator : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </article>
          ))}
          {busy && (
            <p className="text-sm text-neutral-500" data-testid="thinking">
              در حال پاسخ‌گویی…
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-red-700" data-testid="chat-error">
              {error}
            </p>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="mt-3 flex items-end gap-2" aria-label="ارسال پیام">
          <textarea
            rows={2}
            placeholder="سوال خود را بپرسید…"
            aria-label="متن پیام"
            className="min-h-12 flex-1 rounded-card border border-neutral-200 p-3 text-sm"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy || wallet?.blocked === true}
          />
          <button
            type="submit"
            disabled={busy || wallet?.blocked === true || input.trim().length === 0}
            className="rounded-card bg-navy-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-40"
            data-testid="send"
          >
            ارسال
          </button>
        </form>
        {wallet?.blocked === true && (
          <p className="mt-1 text-xs text-neutral-500">
            ارسال پیام تا شارژ اعتبار غیرفعال است.
          </p>
        )}
      </section>
    </div>
  );
}
