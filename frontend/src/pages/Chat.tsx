import {
  AlertCircle,
  ArrowRight,
  ChevronDown,
  Copy,
  FileText,
  History,
  House,
  Plus,
  Search,
  Send,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Button } from "../components/ui/button";
import { LoadingButton } from "../components/ui/button-loading";
import { ConfirmDialog } from "../components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import { Input } from "../components/ui/input";
import { ZeroCreditBanner } from "../components/ZeroCreditBanner";
import { faDate, faNum, faTime, norm } from "../utils/format";

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
  /**
   * How many messages the server says this conversation holds.
   *
   * Optional on purpose: the list endpoint gained the field at the same time as
   * this page learned to hide empty conversations, and an older server that
   * omits it must not make the rail look empty. Absent means "unknown", and an
   * unknown row is kept.
   */
  message_count?: number;
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

/**
 * Whether this page is running inside the HiveOS desktop client.
 *
 * The Windows client is an Electron shell (desktop/src/main.js) that installs
 * its own right-click menu, because Electron gives a window NO default context
 * menu - unlike a browser, where right-click on selected text offers Copy for
 * free. The two menus must not both claim the gesture, so the in-app one stands
 * down when the shell owns it.
 *
 * Detected from the preload's exposed bridge rather than a user agent: the
 * bridge is only present when the preload actually ran, which is exactly the
 * condition being tested.
 */
const isElectron =
  typeof window !== "undefined" && "hiveosDesktop" in (window as object);

/**
 * The citation marker the backend now asks the model to write inline, e.g. "[2]".
 *
 * Matched without the /g flag on purpose: a shared global regex keeps lastIndex
 * between callers, and rendering the same message twice would then skip markers.
 */
const CITATION_MARKER = /\[(\d+)\]/;

/**
 * One inline token of a line: code, bold, italic, a "[n]" marker, or anything
 * else - which stays literal text.
 *
 * Written as a split() capturing group so the literal runs survive between the
 * matches. The alternatives are ordered longest-marker-first: "**" must win over
 * "*", or "**bold**" would parse as an italic "*" pair around a bold "*".
 *
 * The character classes exclude newlines and their own delimiter, so a lone "*"
 * or a half-written "**bold" never matches and is handed to the renderer as the
 * literal text it is. Nothing here can consume a backtick that opens no span.
 */
const INLINE_TOKEN = /(\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[\d+\])/g;

/**
 * What every inline renderer needs: the message, so a marker can name the source
 * it points at, and the handler that opens that answer's source panel.
 */
interface AnswerContext {
  message: ChatMessage;
  onReveal: (marker: number) => void;
}

/**
 * The "[n]" chip. dir=ltr keeps the bracket pair from being reordered by the
 * surrounding Persian text, and the aria-label names the source it points at.
 * A marker past the end of the citation list still renders: it is only ever an
 * array index, so there is nothing to dereference and nothing to throw.
 */
function CitationChip({ marker, ctx }: { marker: number; ctx: AnswerContext }) {
  const citations = ctx.message.citations ?? [];
  return (
    <sup dir="ltr">
      <button
        type="button"
        data-citation-marker={marker}
        onClick={(event) => {
          event.stopPropagation();
          ctx.onReveal(marker);
        }}
        aria-label={
          "نمایش منبع " + faNum(marker) +
          (citations[marker - 1]?.title ? ": " + citations[marker - 1].title : "")
        }
        // text-micro is the smallest step on the ladder. A raw text-[10px]
        // was off-scale: it bypassed the type scale, so a change to
        // --text-micro would silently not reach this chip.
        className="mono mx-0.5 cursor-pointer rounded-xs border border-accent-200 bg-accent px-1 text-micro font-bold text-accent-foreground transition-colors hover:border-primary hover:bg-primary hover:text-primary-foreground"
      >
        {faNum(marker)}
      </button>
    </sup>
  );
}

/** Render one inline token, or null when it is plain text the caller keeps. */
function inlineNode(token: string, key: number, ctx: AnswerContext): React.ReactNode {
  const marker = CITATION_MARKER.exec(token);
  // The token regex only ever produces "[12]" whole, and the exec is compared
  // against the full token so a "[12]" that is part of a longer run is text.
  if (marker && marker[0] === token) {
    return <CitationChip key={key} marker={Number(marker[1])} ctx={ctx} />;
  }
  const wrapped = (open: string) =>
    token.startsWith(open) && token.endsWith(open) && token.length > open.length * 2;
  if (wrapped("**") || wrapped("__")) {
    return (
      <strong key={key} className="font-bold">
        {renderInline(token.slice(2, -2), ctx)}
      </strong>
    );
  }
  if (wrapped("*") || wrapped("_")) {
    return (
      <em key={key} className="italic">
        {renderInline(token.slice(1, -1), ctx)}
      </em>
    );
  }
  if (wrapped("`")) {
    return (
      // LTR even inside RTL prose, or the punctuation of a Latin identifier or
      // a path is reordered to the wrong end of the span.
      <code
        key={key}
        dir="ltr"
        className="mono mx-0.5 rounded-xs border border-border bg-neutral-25 px-1 text-micro text-foreground"
      >
        {token.slice(1, -1)}
      </code>
    );
  }
  return null;
}

/**
 * Render one line's inline syntax. A token that matched nothing is pushed as the
 * string itself, so no character the model wrote is ever dropped.
 */
function renderInline(text: string, ctx: AnswerContext): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  text.split(INLINE_TOKEN).forEach((token, index) => {
    if (!token) return;
    out.push(inlineNode(token, index, ctx) ?? token);
  });
  return out;
}

/** A line of inline syntax, as a node the block renderers can drop anywhere. */
function InlineText({ text, ctx }: { text: string; ctx: AnswerContext }) {
  return <>{renderInline(text, ctx)}</>;
}
type MarkdownBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "quote"; lines: string[] }
  | { kind: "code"; code: string }
  | { kind: "rule" };

/** A fence opener: three or more backticks or tildes at the start of a line. */
const FENCE = /^\s{0,3}(```|~~~)/;
/** An ATX heading. Setext underlines are not supported: in Persian prose a
 *  line of dashes under a line of text is a separator, not a heading. */
const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/;
/** A bullet item. The space after the marker is required, so "**bold**" at the
 *  start of a line is bold text and never a bullet. */
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
/** An ordered item: digits then "." or ")". */
const ORDERED = /^\s{0,3}\d{1,9}[.)]\s+(.*)$/;
/** A blockquote line. */
const QUOTE = /^\s{0,3}>\s?(.*)$/;
/** A thematic break: three or more of the same marker and nothing else. */
const RULE = /^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/;

/**
 * Turn an answer into blocks. Never throws and never drops a character: a line
 * that matches no construct becomes a paragraph line, so malformed markdown
 * renders as the text the model actually wrote rather than disappearing.
 *
 * Fenced code is read first and consumes its body verbatim, because inside a
 * fence the other markers are characters rather than syntax. An unclosed fence
 * runs to the end of the answer - the alternative is showing the backticks of a
 * reply that was cut off mid-block.
 */
function parseMarkdown(source: string): MarkdownBlock[] {
  const lines = source.split("\n");
  const blocks: MarkdownBlock[] = [];
  /**
   * The block a following line may still extend: a list taking another item, a
   * quote taking another line, a paragraph taking another line. Assigned in the
   * loop rather than from a helper, so TypeScript can narrow it - an assignment
   * inside a closure is invisible to control-flow analysis and every "open.kind"
   * below would be reported as "never".
   */
  let open: MarkdownBlock | null = null;
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      // A blank line ends whatever was open: that is what separates two
      // paragraphs, and what stops a list from swallowing the line after it.
      open = null;
      i += 1;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1];
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(marker)) {
        body.push(lines[i]);
        i += 1;
      }
      // The closing fence is consumed when present; an unclosed fence simply
      // runs to the end of the answer.
      if (i < lines.length) i += 1;
      const code: MarkdownBlock = { kind: "code", code: body.join("\n") };
      blocks.push(code);
      open = code;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      const node: MarkdownBlock = {
        kind: "heading",
        level: heading[1].length,
        text: heading[2].trim(),
      };
      blocks.push(node);
      open = node;
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      const node: MarkdownBlock = { kind: "rule" };
      blocks.push(node);
      open = node;
      i += 1;
      continue;
    }
    const bullet = BULLET.exec(line);
    const ordered = bullet ? null : ORDERED.exec(line);
    if (bullet || ordered) {
      const item = (bullet ? bullet[1] : ordered![1]).trim();
      const isOrdered = ordered !== null;
      if (open && open.kind === "list" && open.ordered === isOrdered) {
        open.items.push(item);
      } else {
        const node: MarkdownBlock = { kind: "list", ordered: isOrdered, items: [item] };
        blocks.push(node);
        open = node;
      }
      i += 1;
      continue;
    }
    const quote = QUOTE.exec(line);
    if (quote) {
      if (open && open.kind === "quote") open.lines.push(quote[1]);
      else {
        const node: MarkdownBlock = { kind: "quote", lines: [quote[1]] };
        blocks.push(node);
        open = node;
      }
      i += 1;
      continue;
    }
    // Paragraph text keeps its original spacing; the block renderer applies
    // whitespace-pre-wrap, so indentation and runs of spaces survive.
    if (open && open.kind === "paragraph") open.lines.push(line);
    else {
      const node: MarkdownBlock = { kind: "paragraph", lines: [line] };
      blocks.push(node);
      open = node;
    }
    i += 1;
  }
  return blocks;
}

/**
 * An answer's own heading, at h3 or deeper.
 *
 * A reply is one section of a page that already owns its h1, so "#" maps to h3
 * and "#".."######" map onto h3..h6. Rendering them as h1/h2 would place the
 * transcript above the page's real sections in the document outline.
 */
const HEADING_TAG: Readonly<Record<number, "h3" | "h4" | "h5" | "h6">> = {
  1: "h3",
  2: "h4",
  3: "h5",
  4: "h6",
  5: "h6",
  6: "h6",
};

function MarkdownBlockView({ block, ctx }: { block: MarkdownBlock; ctx: AnswerContext }) {
  switch (block.kind) {
    case "heading": {
      const Tag = HEADING_TAG[block.level] ?? "h6";
      return (
        <Tag
          className={
            "mt-4 mb-1.5 font-bold text-foreground first:mt-0 " +
            (block.level <= 2 ? "text-subheading" : "text-caption")
          }
        >
          <InlineText text={block.text} ctx={ctx} />
        </Tag>
      );
    }
    case "paragraph":
      return (
        <p className="whitespace-pre-wrap">
          <InlineText text={block.lines.join("\n")} ctx={ctx} />
        </p>
      );
    case "list": {
      const items = block.items.map((item, index) => (
        <li key={index}>
          <InlineText text={item} ctx={ctx} />
        </li>
      ));
      return block.ordered ? (
        <ol className="mb-2 flex list-decimal flex-col gap-1 ps-5">{items}</ol>
      ) : (
        <ul className="mb-2 flex list-disc flex-col gap-1 ps-5">{items}</ul>
      );
    }
    case "quote":
      return (
        <blockquote className="my-2 whitespace-pre-wrap border-s-2 border-border ps-3 text-muted-foreground">
          <InlineText text={block.lines.join("\n")} ctx={ctx} />
        </blockquote>
      );
    case "code":
      return (
        // pre + dir=ltr + overflow-x: a code block is LTR by nature and a long
        // line must scroll rather than wrap into the RTL flow.
        <pre
          dir="ltr"
          className="mono my-2 overflow-x-auto rounded-control border border-border bg-neutral-25 p-3 text-caption text-foreground"
        >
          <code>{block.code}</code>
        </pre>
      );
    case "rule":
      return <hr className="my-3 border-border" />;
  }
}

/**
 * An answer, rendered as clean elements instead of the markdown the model wrote.
 *
 * No dependency and no dangerouslySetInnerHTML: the source is parsed into a
 * small block/inline tree here and each node becomes a real React element, so
 * there is no HTML string that could ever be injected.
 */
function AnswerBody({
  message,
  onReveal,
}: {
  message: ChatMessage;
  onReveal: (marker: number) => void;
}) {
  const ctx: AnswerContext = { message, onReveal };
  return (
    <>
      {parseMarkdown(messageText(message)).map((block, index) => (
        <MarkdownBlockView key={index} block={block} ctx={ctx} />
      ))}
    </>
  );
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

/**
 * Where the transcript was scrolled to, and which conversation was open.
 *
 * The transcript lives in an overflow-y-auto pane inside a route, so leaving
 * /chat unmounts it and React destroys both pieces of state. The PO asked to
 * come back to where they left off instead of re-scrolling by hand. sessionStorage
 * is the right scope: it is per-tab, survives a route change and a refresh, and
 * is discarded when the tab closes, so a new visit starts clean.
 */
const CHAT_STATE_KEY = "hiveos.chat.view";

function loadChatView(): { sessionId: string | null; scrollTop: number } {
  try {
    const raw = sessionStorage.getItem(CHAT_STATE_KEY);
    if (!raw) return { sessionId: null, scrollTop: 0 };
    const parsed = JSON.parse(raw) as { sessionId?: unknown; scrollTop?: unknown };
    return {
      sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : null,
      scrollTop: typeof parsed.scrollTop === "number" && parsed.scrollTop >= 0 ? parsed.scrollTop : 0,
    };
  } catch {
    // A corrupt or unavailable sessionStorage must never block the chat itself.
    return { sessionId: null, scrollTop: 0 };
  }
}

function saveChatView(sessionId: string | null, scrollTop: number): void {
  try {
    sessionStorage.setItem(CHAT_STATE_KEY, JSON.stringify({ sessionId, scrollTop }));
  } catch {
    /* storage full or blocked: the page still works, it just forgets. */
  }
}

/**
 * The citation disclosure under a bubble, collapsed to its summary line.
 *
 * A permanent "منابع:" chip row under every answer was noise the PO did not want
 * on screen; the sources stay one click away, the summary states how many there
 * are, and the panel is named by the control that opens it.
 *
 * Declared at module scope rather than inside Chat() on purpose: a component
 * created inside another component is a NEW type on every render, so React
 * unmounts and remounts the whole subtree whenever the page re-renders - the
 * click that toggled the panel landed on a node that no longer existed by the
 * time the assertion (or the user) looked at it.
 *
 * The bubble's click handler stands down inside data-citations-block, because
 * the disclosure owns its own clicks.
 */
function CitationList({
  message,
  expanded,
  flashMarker,
  onToggle,
}: {
  message: ChatMessage;
  expanded: boolean;
  flashMarker: string | null;
  onToggle: () => void;
}) {
  const citations = message.citations ?? [];
  const panelId = "chat-cites-" + message.id;
  return (
    <div
      className="mt-2.5 border-t border-dashed border-border pt-2.5"
      data-citations-block={panelId}
    >
      <button
        type="button"
        data-testid="chat-cites-toggle"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={onToggle}
        className="inline-flex cursor-pointer items-center gap-1.5 rounded-xs px-1 py-0.5 text-micro font-bold text-muted-foreground transition-colors hover:text-foreground"
      >
        <FileText aria-hidden className="size-3.5" />
        {faNum(citations.length)} منبع
        <ChevronDown
          aria-hidden
          className={"size-3.5 transition-transform " + (expanded ? "rotate-180" : "")}
        />
      </button>
      {expanded && (
        <div id={panelId} data-testid="chat-cites-panel" className="mt-2 flex flex-wrap gap-1.5">
          {citations.map((c: Citation, index: number) => {
            // Two citations can point at the same locator in the same
            // document, so the pair is the identity - the list index is not.
            const key = (c.document_id ?? "") + ":" + (c.locator ?? c.title ?? "");
            const flashed = flashMarker === message.id + ":" + (index + 1);
            return (
              <span
                key={key}
                id={"chat-cite-" + message.id + "-" + (index + 1)}
                data-testid={"chat-cite-" + message.id + "-" + (index + 1)}
                className={
                  "flex max-w-full items-start gap-2 rounded-control border bg-secondary px-2.5 py-[7px] text-caption transition-colors " +
                  (flashed ? "border-primary ring-2 ring-ring/40" : "border-border")
                }
              >
                <FileText aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="block truncate font-bold">{c.title ?? "سند"}</span>
                  {c.locator && (
                    <span className="block text-micro text-muted-foreground">{c.locator}</span>
                  )}
                </span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
   * ref read during render is invisible to React - the button would not appear
   * until some unrelated state change happened to re-render the tree.
   */
  const [lastSent, setLastSent] = useState("");
  /** The transcript pane; owns the scroll position this page restores. */
  const transcriptRef = useRef<HTMLDivElement>(null);
  /** Guards the restore so a later send still scrolls to the newest message. */
  const restoredRef = useRef(false);
  /**
   * Whether the transcript should follow new content.
   *
   * Only a message this tab just sent (or a brand-new conversation) may move
   * the scroll position. Driving it off [messages] alone meant the smooth
   * scrollIntoView re-fired on every remount and dragged the pane to the end,
   * cancelling the restored offset a moment after it was applied - the user
   * was thrown to the bottom anyway.
   */
  const followRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeIdRef = useRef<string | null>(null);
  /** Below md the history rail is a dialog, not a column. */
  const [railOpen, setRailOpen] = useState(false);
  /** Set when a different conversation is opened, to reset its scroll to top. */
  const [openingSession, setOpeningSession] = useState(false);
  /**
   * Which citation disclosures are expanded, keyed by message id.
   *
   * Per message, not one global flag: every answer carries its own sources and
   * opening one must not unfold the rest of the transcript.
   */
  const [openCitations, setOpenCitations] = useState<Record<string, boolean>>({});
  /** "messageId:index" of the citation an inline marker just jumped to. */
  const [flashCitation, setFlashCitation] = useState<string | null>(null);
  const flashTimerRef = useRef<number | null>(null);
  /** The session waiting for the delete confirmation to be accepted. */
  const [pendingDelete, setPendingDelete] = useState<SessionItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  /**
   * The custom message context menu, anchored where the pointer was.
   *
   * One object rather than an "open" flag plus coordinates: the menu is open
   * exactly when there is a message and a position to anchor it at, so the two
   * can never disagree and leave a stray menu on screen.
   */
  const [menu, setMenu] = useState<{ message: ChatMessage; x: number; y: number } | null>(null);
  const navigate = useNavigate();

  // The chat list endpoint is paginated: it answers {items, total_count, page,
  // page_size, has_more}, not {sessions}. Reading the wrong key yielded [] every
  // time, so the rail was permanently empty and history unreachable.
  const loadSessions = useCallback(async () => {
    const data = await api<{ items: SessionItem[] }>("GET", "/chat/sessions");
    // PO request 2026-09: a conversation with nothing in it must never be
    // shown. The server purges and filters them, but one can still arrive from
    // an older build or another client, and an empty row in the rail opens onto
    // a blank pane with no way to tell it apart from a broken one. An absent
    // message_count is "unknown", not zero, so it is never hidden on a guess.
    // Filtered here rather than in the rail because bootstrap picks the
    // conversation to reopen from this same list.
    const items = (data.items ?? []).filter(
      (s) => s.message_count === undefined || s.message_count > 0,
    );
    setSessions(items);
    return items;
  }, []);

  /**
   * Load a conversation's transcript.
   *
   * resetScroll separates the two callers. A click in the rail means "show me
   * this conversation from the top"; the bootstrap path is a restore, and must
   * keep the offset that was remembered for the conversation being returned to.
   * Without the distinction the mount restore and the reset raced, and the
   * remembered offset was always wiped back to zero.
   */
  const openSession = useCallback(async (id: string, resetScroll = false) => {
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
      // Only a deliberate selection resets the pane; a bootstrap restore does not.
      if (resetScroll) setOpeningSession(true);
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
      // Reopen the conversation that was open when the user last left /chat,
      // not simply the newest one. The id is validated against the server's own
      // list first, so a session deleted in another tab cannot 404 here.
      const remembered = loadChatView().sessionId;
      const target = list.find((s) => s.id === remembered) ?? list[0];
      if (target) await openSession(target.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "دریافت گفتگوها ناموفق بود.");
    }
    try {
      const w = await api<WalletMini>("GET", "/wallet");
      setWallet({ balance: w.balance, blocked: w.blocked });
    } catch (e) {
      // F: swallowing this left 'blocked' at its old value - the composer and
      // the zero-credit banner could both contradict the real balance.
      setError(e instanceof Error ? e.message : "دریافت وضعیت اعتبار ناموفق بود.");
    }
  }, [loadSessions, openSession]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  /**
   * Scroll policy for the transcript.
   *
   * The first paint after a remount restores the remembered offset instead of
   * jumping to the bottom; every later change still follows the newest message.
   * A saved offset beyond the current content (messages added elsewhere, or a
   * shorter conversation) is clamped by the browser, so the pane lands at its
   * own end rather than overflowing.
   */
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    if (!restoredRef.current) {
      // Nothing to restore into until the transcript has actually arrived;
      // scrolling here would also be pointless on an empty pane.
      if (messages.length === 0) return;
      restoredRef.current = true;
      const { scrollTop } = loadChatView();
      if (scrollTop > 0) {
        // Instant, not smooth: an animated scroll through a long transcript
        // reads as a glitch when the user expected to already be there.
        el.scrollTop = scrollTop;
        return;
      }
    }
    // Following is opt-in, so returning to the page never yanks the view down.
    if (!followRef.current) return;
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, busy]);

  // Selecting another conversation scrolls that transcript to its beginning.
  // Declared before the persistence effect so the offset is republished only
  // after the pane has actually moved.
  useEffect(() => {
    if (!openingSession) return;
    restoredRef.current = true;
    followRef.current = false;
    if (transcriptRef.current) transcriptRef.current.scrollTop = 0;
    setOpeningSession(false);
  }, [openingSession]);

  /** Remember the open conversation and the transcript offset for the next visit. */
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    const remember = () => {
      // Ignore the final scroll event the browser fires while the route is
      // being torn down. As the pane collapses its scrollTop is clamped to 0,
      // and that event used to overwrite the offset the user had actually
      // scrolled to - so returning to /chat always landed at the bottom.
      // A detached or zero-height pane can only report that clamped value.
      if (!el.isConnected || el.clientHeight === 0) return;
      saveChatView(activeIdRef.current, el.scrollTop);
    };
    // scroll fires continuously; the listener only keeps the latest offset and
    // does not re-render anything.
    el.addEventListener("scroll", remember, { passive: true });
    return () => {
      el.removeEventListener("scroll", remember);
    };
  }, []);

  /**
   * Start a conversation - in the page, not on the server.
   *
   * PO request: pressing «گفتگوی جدید» and then typing nothing must leave no
   * conversation behind. A session row is therefore only created by send(), on
   * the first message, and this function only clears the transcript and points
   * activeId at nothing. The rail needs no placeholder row for it: the page
   * already shows the empty-state suggestions whenever no message is on screen.
   */
  function newChat() {
    activeIdRef.current = null;
    setActiveId(null);
    setMessages([]);
    setMenu(null);
    setError(null);
    // A new conversation starts at the top of an empty pane, and must not
    // inherit the previous conversation's remembered offset. It is not
    // remembered itself either: it has no id yet, and writing a null here would
    // discard the conversation the user is still coming back to.
    restoredRef.current = true;
    followRef.current = true;
    if (transcriptRef.current) transcriptRef.current.scrollTop = 0;
  }

  /**
   * Run the delete only after the operator confirmed it in ConfirmDialog.
   *
   * Nothing is removed from the list until the server has answered: a failed
   * request must leave the rail exactly as it was, with the reason in the
   * existing error panel.
   */
  async function deleteSession(session: SessionItem) {
    setDeleting(true);
    try {
      await api("DELETE", "/chat/sessions/" + session.id);
      const remaining = sessions.filter((s) => s.id !== session.id);
      setSessions(remaining);
      setPendingDelete(null);
      setError(null);
      if (activeIdRef.current === session.id) {
        // The transcript on screen belongs to a row that no longer exists.
        activeIdRef.current = null;
        setActiveId(null);
        setMessages([]);
        // Forget the remembered conversation too, or a refresh would try to
        // reopen the id that was just deleted.
        saveChatView(null, 0);
        const next = remaining[0];
        if (next) await openSession(next.id, true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "حذف گفتگو ناموفق بود.");
    } finally {
      setDeleting(false);
    }
  }

  /**
   * Put the caret back where the context menu was opened.
   *
   * The menu is portalled to the body and restores focus somewhere inside
   * itself when it closes; without this the keyboard user would land back in a
   * position that has already been dismissed.
   */
  function closeMenu(messageId: string) {
    setMenu(null);
    const bubble = document.getElementById("chat-msg-" + messageId);
    // jsdom does not implement focus() on every element; the guard keeps the
    // browser behaviour and never throws in a test render.
    if (bubble && typeof bubble.focus === "function") bubble.focus();
  }

  // Clear the highlight a moment after an inline marker jumped to a citation,
  // so the ring reads as "this one" rather than as a permanent state.
  useEffect(() => {
    if (!flashCitation) return;
    const timer = window.setTimeout(() => setFlashCitation(null), 2400);
    return () => window.clearTimeout(timer);
  }, [flashCitation]);

  // A timer left behind by unmount would fire setState on a dead component.
  useEffect(() => {
    return () => {
      if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
    };
  }, []);

  /**
   * An inline "[n]" marker: open the answer's source disclosure and mark the
   * matching chip.
   *
   * "n" is whatever the model wrote. It is used only as an array index and
   * never dereferenced here, so a marker beyond the citation list simply opens
   * the panel with nothing to highlight instead of throwing.
   */
  function revealCitation(message: ChatMessage, n: number) {
    setOpenCitations((current) => ({ ...current, [message.id]: true }));
    setFlashCitation(message.id + ":" + n);
    // The panel is painted by the state above, so the chip does not exist yet
    // on this tick; scroll to it on the next frame.
    window.setTimeout(() => {
      document.getElementById("chat-cite-" + message.id + "-" + n)?.scrollIntoView?.({
        behavior: "smooth",
        block: "nearest",
      });
    }, 0);
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
    // This send is the one case that should move the transcript.
    followRef.current = true;
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
        // From here the conversation is real and may be returned to.
        saveChatView(sessionId, 0);
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
  /**
   * The conversation rail.
   *
   * Rendered twice on purpose: as the sticky column at md and up, and inside a
   * dialog below md. It used to be "hidden … md:flex" with no counterpart, so
   * on a phone the entire history was unreachable - the PO's report. The body
   * sits in one function so the two presentations cannot drift apart; only the
   * scrolling wrapper differs.
   */
  function renderRail(bodyClassName: string) {
    return (
      <>
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
              className="rounded-control py-2 ps-9 pe-[11px] text-caption"
            />
          </div>
        </div>
        {/*
          One dialog for the whole rail, not one per row: only a single row can
          be awaiting confirmation, which pendingDelete already encodes, and a
          hundred mounted dialogs would each own a focus trap for nothing.
        */}
        <ConfirmDialog
          open={pendingDelete !== null}
          onOpenChange={(open) => {
            if (!open) setPendingDelete(null);
          }}
          title="حذف گفتگو"
          description={
            pendingDelete
              ? "گفتگوی «" + (pendingDelete.title ?? "گفتگوی بدون عنوان") + "» حذف می‌شود."
              : ""
          }
          consequences={[
            "این گفتگو از فهرست شما حذف می‌شود.",
            "پس از حذف، بازگرداندن آن از این صفحه ممکن نیست.",
          ]}
          confirmLabel="حذف گفتگو"
          busy={deleting}
          onConfirm={() => {
            if (pendingDelete) void deleteSession(pendingDelete);
          }}
        />
        <div className={bodyClassName} aria-label="گفتگوها">
          {grouped.length === 0 && (
            <div className="px-4 py-10 text-center">
              <p className="text-caption leading-[1.9] text-muted-foreground">
                هنوز گفتگویی ندارید. با «گفتگوی جدید» اولین سوال خود را از هوش سازمان بپرسید.
              </p>
            </div>
          )}
          {grouped.map((group) => (
            <div key={group.label}>
              <div className="px-2 pb-1 pt-2.5 text-micro font-bold tracking-[0.4px] text-muted-foreground">
                {group.label}
              </div>
              {/*
                The row moved from a <button> to a div holding two real buttons.
                Nested buttons are invalid HTML and the parser drops the inner
                one, so the delete control could never have existed inside the
                old markup. The div carries the hover/focus-within group that
                reveals the trash the same way the message copy action appears.
              */}
              {group.items.map((s) => (
                <div key={s.id} className="group relative mb-0.5">
                  <button
                    type="button"
                    onClick={() => {
                      void openSession(s.id, true);
                      // On a phone the rail is an overlay: pick a conversation and
                      // get out of the way, the same as any mobile drawer.
                      setRailOpen(false);
                    }}
                    aria-current={activeId === s.id ? "true" : undefined}
                    className={
                      "block w-full cursor-pointer rounded-control p-2.5 pe-16 text-start " +
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
                  {/*
                    Keyboard-reachable and not hover-only: the button stays in the
                    tab order at all times and only its visibility is hover-driven,
                    with focus-visible forcing it back into view.
                  */}
                  <button
                    type="button"
                    onClick={() => setPendingDelete(s)}
                    aria-label={"حذف گفتگوی «" + (s.title ?? "گفتگوی بدون عنوان") + "»"}
                    title="حذف گفتگو"
                    className="absolute bottom-2 end-2.5 flex size-6 cursor-pointer items-center justify-center rounded-xs text-muted-foreground opacity-0 transition-opacity hover:bg-error-bg hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
                  >
                    <Trash2 aria-hidden className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </>
    );
  }

  return (
    // A real <section> landmark, not an aria-label on a plain div: a label on a
    // div does nothing, so the whole chat surface was unlandmarked and had no
    // level-one heading (axe: region, page-has-heading-one). The heading is
    // visually hidden because the transcript is the page's content and a visible
    // title would push it down on the one screen that is all content.
    <section className="flex min-h-0 flex-1" aria-label="گفتگو">
      <h1 className="sr-only">گفتگو</h1>
      {/* — chat-list (mockup §۲۰) — */}
      <aside
        className="hidden w-[280px] shrink-0 flex-col border-e border-border bg-card md:flex"
        aria-label="فهرست گفتگوها"
      >
        {renderRail("flex-1 overflow-auto p-2")}
      </aside>

      {/* Mobile equivalent of the rail above. Radix owns the focus trap, Escape
          and the overlay, so this does not reimplement dialog behaviour. */}
      <Dialog open={railOpen} onOpenChange={setRailOpen}>
        <DialogContent
          className="flex max-h-[80dvh] flex-col gap-0 p-0 md:hidden"
          aria-label="فهرست گفتگوها"
        >
          <DialogHeader className="border-b border-border px-4 py-3 text-start">
            <DialogTitle className="text-subheading font-bold">گفتگوها</DialogTitle>
            <DialogDescription className="sr-only">
              فهرست گفتگوهای پیشین؛ برای باز کردن هر گفتگو روی آن بزنید.
            </DialogDescription>
          </DialogHeader>
          {renderRail("min-h-0 flex-1 overflow-auto p-2")}
        </DialogContent>
      </Dialog>

      {/* — chat-main — */}
      <section className="flex min-w-0 flex-1 flex-col bg-secondary" aria-label="پیام‌ها">
        {/* Below md there is no rail column, so this is the only way into the
            conversation history. */}
        <div className="flex items-center gap-2 border-b border-border px-[8%] py-2 md:hidden">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="rounded-control"
            onClick={() => setRailOpen(true)}
          >
            <History aria-hidden className="size-4" />
            گفتگوها
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rounded-control"
            onClick={() => navigate("/")}
          >
            <ArrowRight aria-hidden className="size-4" />
            بازگشت
          </Button>
          <span className="truncate text-caption font-bold text-foreground">
            {sessions.find((s) => s.id === activeId)?.title ?? "گفتگوی جدید"}
          </span>
        </div>
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
          ref={transcriptRef}
          aria-live="polite"
          aria-busy={busy}
          // PO report: right-click inside the chat text did not open the
          // browser's own menu. Nothing in the app suppresses contextmenu (no
          // global listener, no preventDefault - every listener is
          // keydown/scroll/visibilitychange) and no rule here disables
          // selection: the only select-none utilities in the codebase are on
          // menu items, labels and selects, and the built stylesheet has none
          // covering the transcript. select-text states that as intent so
          // drag-select plus the native Copy can never be broken by a later
          // utility landing on an ancestor.
          className="min-h-0 flex-1 select-text space-y-[18px] overflow-y-auto px-[8%] py-[26px]"
        >
          {messages.length === 0 && !busy && (
            <div className="flex h-full flex-col items-center justify-center px-[30px] text-center">
              <span
                aria-hidden
                className="mb-[18px] flex size-16 items-center justify-center rounded-card bg-primary text-primary-foreground shadow-raised"
              >
                <House className="size-[30px]" />
              </span>
              <h2 className="text-heading text-foreground">هوش سازمان آماده است</h2>
              <p className="mt-2 max-w-[440px] text-caption text-muted-foreground">
                سوال خود را درباره سازمان یا اسناد آن بپرسید. پاسخ‌ها با ارجاع به منابع داده می‌شوند.
              </p>
              <div className="mt-[22px] grid max-w-[640px] grid-cols-1 gap-2.5 sm:grid-cols-2">
                {SUGGESTS.map((s) => (
                  <button
                    key={s.text}
                    type="button"
                    onClick={() => setInput(s.text)}
                    className="cursor-pointer rounded-control border border-border bg-card p-[13px] pe-[15px] text-start text-caption font-semibold text-foreground shadow-card transition-colors hover:border-primary/40 hover:text-primary"
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
            const hasCitations = (m.citations ?? []).length > 0;
            return (
              <article
                key={m.id}
                // tabIndex makes the bubble programmatically focusable, which
                // is where the context menu returns focus on Escape, and id is
                // used only for that return trip.
                id={"chat-msg-" + m.id}
                tabIndex={-1}
                onContextMenu={(event) => {
                  // IN THE DESKTOP CLIENT, LET THE NATIVE MENU HAVE IT.
                  //
                  // This handler used to call preventDefault() while its comment
                  // claimed the native menu was "NOT suppressed" - the code and
                  // the comment disagreed, and the suppression was the bug that
                  // mattered: in the HiveOS Windows (Electron) client the
                  // right-click menu is built by the shell (desktop/src/main.js,
                  // attachContextMenu). Electron provides no default menu, so
                  // suppressing the event here left the user with nothing but
                  // this in-app menu - and the PO's report was specifically that
                  // copy from the text did not work.
                  //
                  // So under Electron this returns early and the shell menu
                  // (copy / select all / paste) handles it. In a real browser the
                  // browser menu already works, and this in-app menu is the
                  // keyboard-reachable one (Shift+F10 / the Menu key).
                  if (isElectron) return;
                  if (!messageText(m).trim()) return;
                  event.preventDefault();
                  setMenu({ message: m, x: event.clientX, y: event.clientY });
                }}
                className="group flex max-w-[820px] gap-3 outline-none"
                data-testid={"msg-" + m.role.toLowerCase()}
              >
                <span
                  aria-hidden
                  className={
                    "flex size-8 shrink-0 items-center justify-center rounded-control text-micro font-bold " +
                    (isUser
                      ? "border border-border bg-secondary text-muted-foreground"
                      : "bg-primary text-primary-foreground")
                  }
                >
                  {isUser ? "م" : <House className="size-[17px]" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2 text-micro font-bold text-muted-foreground">
                    {isUser ? "شما" : "هوش سازمان"}
                    {m.created_at && <span className="font-normal">{faTime(m.created_at)}</span>}
                  </div>
                  <div
                    className={
                      "rounded-card border px-4 py-3.5 text-body leading-[1.9] shadow-card " +
                      (isUser ? "border-primary/40 bg-accent" : "border-border bg-card")
                    }
                    // Clicking the answer expands its sources - the affordance a
                    // long press gives a phone user. A click that lands on the
                    // inline marker is left alone: the marker expands the panel
                    // itself and highlights one chip, which is a narrower intent.
                    onClick={(event) => {
                      if (!hasCitations) return;
                      const target = event.target as Element;
                      // The marker and the disclosure own their own clicks. The
                      // disclosure especially: without this the container would
                      // re-open it on the same click that collapsed it.
                      if (target.closest?.("[data-citation-marker]")) return;
                      if (target.closest?.("[data-citations-block]")) return;
                      setOpenCitations((open) => ({ ...open, [m.id]: true }));
                    }}
                  >
                    {/*
                      dir=auto: a Latin filename or a code span sits inside RTL
                      prose, and the first strong character decides a run's
                      direction - without it the punctuation of a marker jumps to
                      the wrong end.
                    */}
                    <div dir="auto">
                      {isUser ? (
                        <p className="whitespace-pre-wrap">{messageText(m)}</p>
                      ) : (
                        <AnswerBody message={m} onReveal={(marker) => revealCitation(m, marker)} />
                      )}
                      {hasCitations && (
                        <CitationList
                          message={m}
                          expanded={openCitations[m.id] === true}
                          flashMarker={flashCitation}
                          onToggle={() =>
                            setOpenCitations((open) => ({ ...open, [m.id]: !open[m.id] }))
                          }
                        />
                      )}
                    </div>
                  </div>
                  {!busy && (
                    <div className="mt-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        type="button"
                        className="inline-flex cursor-pointer items-center gap-[5px] rounded-xs border border-transparent px-2 py-[3px] text-micro font-semibold text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground min-h-11 md:min-h-0"
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
                className="flex size-8 shrink-0 items-center justify-center rounded-control bg-primary text-primary-foreground"
              >
                <House className="size-[17px]" />
              </span>
              <div className="rounded-card border border-border bg-card px-4 py-3.5 text-body text-muted-foreground">
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
          <div className="flex items-end gap-2.5 rounded-card border border-border bg-card px-3 py-2.5 transition-shadow focus-within:border-primary focus-within:ring-[3px] focus-within:ring-ring/20">
            <textarea
              rows={1}
              placeholder={blocked ? "برای ادامه، حساب خود را شارژ کنید…" : "سوال خود را بپرسید…"}
              aria-label="متن پیام"
              className="max-h-40 min-h-[44px] flex-1 resize-none border-none bg-transparent px-1 py-1.5 text-body leading-[1.7] text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-55 border-border bg-card"
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
              className="flex size-10 shrink-0 cursor-pointer items-center justify-center rounded-control transition-colors disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-muted-foreground bg-primary text-primary-foreground hover:bg-primary/90"
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

      {/*
        The custom context menu, portalled to the body by the primitive and
        positioned at the pointer. In-app so it is reachable by keyboard
        (Shift+F10 / the Menu key) as well as by right-click.
      */}
      <DropdownMenu
        open={menu !== null}
        onOpenChange={(open) => {
          if (!open) setMenu(null);
        }}
      >
        <DropdownMenuTrigger asChild>
          <span
            aria-hidden
            className="pointer-events-none fixed size-0"
            style={menu ? { left: menu.x, top: menu.y } : undefined}
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-44" align="start">
          <DropdownMenuItem
            aria-label="کپی پیام"
            onSelect={() => {
              if (!menu) return;
              void navigator.clipboard?.writeText(messageText(menu.message));
              closeMenu(menu.message.id);
            }}
          >
            <Copy aria-hidden className="size-4" />
            کپی
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </section>
  );
}
