import {
  AlertCircle,
  ArrowRight,
  Brain,
  ChevronDown,
  Copy,
  Download,
  FileText,
  History,
  House,
  Plus,
  Search,
  Send,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, API_BASE } from "../api/client";
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
import { useLive } from "../lib/live";
import { faDate, faNum, faRelative, faTime, humanSize, norm } from "../utils/format";

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
  /**
   * Server-reported in-flight flag (B4).
   *
   * Optional because an older server omits it; the client also tracks the
   * conversations it started itself, and the two sources are unioned. A missing
   * field must never be read as "not generating" when this tab knows better.
   */
  generating?: boolean;
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
  content: { text?: string; artifacts?: Artifact[] | null } | null;
  citations?: Citation[] | null;
  /**
   * Files the agent created while answering (B3).
   *
   * Server-side the "artifacts" array rides on the execution output and is
   * copied onto the persisted assistant message. It is optional on purpose: an
   * older server answers without it, and an empty array means "nothing was
   * created". Neither may crash the page or paint an empty box.
   */
  artifacts?: Artifact[] | null;
  /**
   * The execution behind this row, when the server reports it.
   *
   * Used only to match a live execution output to the answer it produced, so
   * the artifact cards can be shown on the live turn as well as in history.
   * The field is not guaranteed, so every read falls back to a text match.
   */
  execution_id?: string | null;
  created_at: string;
}

/**
 * Keep the current array when a refresh delivered the same rows.
 *
 * The transcript effect follows new content, and a poll that returned an
 * identical list would hand React a new array on every tick - which re-fires
 * the smooth scroll and drags the pane to the bottom while the user is reading.
 * Identity is the ordered list of message ids: nothing else the transcript
 * renders can change without a row arriving or leaving.
 */
function mergeMessages(current: ChatMessage[], next: ChatMessage[]): ChatMessage[] {
  if (current.length === next.length && current.every((m, i) => m.id === next[i]?.id)) {
    return current;
  }
  return next;
}

/**
 * One file the agent produced, as POST /executions/{id}/run reports it.
 *
 * Every field is optional at the type level. This array is being added by a
 * parallel backend change, so the page has to survive a payload that is missing
 * a key, carries an extra one, or arrives as an empty array.
 */
interface Artifact {
  asset_id?: string;
  name?: string;
  extension?: string;
  size_bytes?: number;
  asset_type?: string;
}

/**
 * The files an answer produced, from every place the server puts them.
 *
 * Read from "artifacts" (the persisted assistant message) first, then from
 * "content.artifacts" the way citations are read off a stored message, and
 * finally from the enclosing execution output - which is the only source for a
 * live answer while the transcript is being refreshed. Anything that is not an
 * array is treated as absent, because guessing here would render a broken card.
 */
function artifactsOf(message: ChatMessage, output?: unknown): Artifact[] {
  const lists: unknown[] = [
    message.artifacts,
    message.content?.artifacts,
    (output as { artifacts?: unknown } | undefined)?.artifacts,
  ];
  for (const list of lists) {
    if (Array.isArray(list) && list.length > 0) return list as Artifact[];
  }
  return [];
}

/**
 * A human size, in Persian digits.
 *
 * An absent or non-numeric size is reported as an unknown size rather than as
 * "zero" - a zero-byte file and an unreported one are different facts, and only
 * one of them is about the file.
 */
function artifactSize(bytes: number | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "حجم نامشخص";
  return humanSize(bytes);
}

/**
 * What the file is, in Persian. Reports are .html and charts .png; anything
 * else is described by its own extension rather than by a guess.
 */
function artifactLabel(artifact: Artifact): string {
  const kind = (artifact.asset_type ?? "").toLowerCase();
  const ext = (artifact.extension ?? "").toLowerCase().replace(/^\./, "");
  if (kind.includes("chart") || ext === "png" || ext === "jpg" || ext === "jpeg") return "نمودار";
  if (kind.includes("report") || ext === "html" || ext === "htm" || ext === "pdf") return "گزارش";
  return ext ? "فایل " + ext.toUpperCase() : "فایل";
}

/**
 * The download URL for a stored asset.
 *
 * Built from API_BASE, not a hardcoded prefix: the client already owns the
 * "/api/v1" root (see api/client.ts) and a second copy here is how the two
 * silently drift apart. The backend route is
 * GET /knowledge-assets/{asset_id}/download (backend/knowledge/router.py:434).
 */
function artifactHref(assetId: string): string {
  const root = API_BASE.replace(/\/+$/, "");
  return root + "/knowledge-assets/" + encodeURIComponent(assetId) + "/download";
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

/**
 * One remembered line, exactly as GET /agent/memory returns it (B5).
 *
 * Read from the current Agent.tsx before that page is deleted rather than
 * guessed: the row carries its kind and creation date, which is what the
 * compact surface lists, and the delete endpoint is keyed by this id.
 */
interface MemoryRow {
  id: string;
  kind: string;
  content: string;
  weight: number;
  hits: number;
  misses: number;
  active: boolean;
  created_at: string | null;
}

/** The kinds the server stores, named in Persian (mirrors Agent.tsx). */
const KIND_LABEL: Record<string, string> = {
  fact: "واقعیت",
  preference: "ترجیح",
  decision: "تصمیم",
  summary: "خلاصه",
};

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

/**
 * The files an answer created, as evidence rather than as a claim.
 *
 * The model may say it wrote a report; this card is what proves it: the row
 * comes from the server's own artifact list and the link downloads the stored
 * asset. "data-artifacts-block" lets the bubble's click handler stand down, the
 * same way the citation disclosure does.
 *
 * Nothing renders for an empty or absent list. A "no files" box under every
 * answer would be pure noise, and the PO's complaint was the opposite - that a
 * created file was invisible.
 */
function ArtifactList({ message, output }: { message: ChatMessage; output?: unknown }) {
  const artifacts = artifactsOf(message, output);
  if (artifacts.length === 0) return null;
  return (
    <div
      className="mt-2.5 border-t border-dashed border-border pt-2.5"
      data-artifacts-block={"artifacts-" + message.id}
    >
      <div className="mb-2 flex items-center gap-1.5 text-micro font-bold text-muted-foreground">
        <FileText aria-hidden className="size-3.5" />
        {faNum(artifacts.length)} فایل ساخته شد
      </div>
      <ul className="flex flex-wrap gap-2">
        {artifacts.map((artifact, index) => {
          const name = artifact.name ?? "فایل بدون نام";
          const downloadable = typeof artifact.asset_id === "string" && artifact.asset_id.length > 0;
          return (
            <li
              key={(artifact.asset_id ?? "") + ":" + name + ":" + index}
              data-testid="chat-artifact"
              className="flex min-w-0 max-w-full items-center gap-2.5 rounded-control border border-border bg-secondary px-3 py-2 text-caption"
            >
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-control bg-card text-muted-foreground"
              >
                <FileText className="size-4" />
              </span>
              <span className="min-w-0">
                <span dir="auto" className="block truncate font-bold">
                  {name}
                </span>
                <span className="block text-micro text-muted-foreground">
                  {artifactLabel(artifact)} · {artifactSize(artifact.size_bytes)}
                </span>
              </span>
              {downloadable ? (
                <a
                  href={artifactHref(artifact.asset_id as string)}
                  download={name}
                  data-testid="chat-artifact-download"
                  aria-label={"دانلود " + name}
                  className="ms-1 inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-xs border border-border bg-card px-2 py-1 text-micro font-semibold text-foreground transition-colors hover:border-primary hover:text-primary"
                >
                  <Download aria-hidden className="size-3.5" />
                  دانلود
                </a>
              ) : (
                // No asset id means there is nothing to download: a dead link
                // would be worse than an honest "saved on the server".
                <span className="ms-1 shrink-0 text-micro text-muted-foreground">ذخیره شد</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function Chat() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [wallet, setWallet] = useState<WalletMini | null>(null);
  const [input, setInput] = useState("");
  const [filter, setFilter] = useState("");
  /**
   * Whether the conversation on screen is generating (B1/B2).
   *
   * Derived from the per-session map, so switching to another conversation
   * cannot inherit it: the composer is free and stays typable. Declared early
   * because the transcript's scroll effect reads it.
   */
  const [activeId, setActiveId] = useState<string | null>(null);
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
  /** The session the pane is showing, readable from an async callback. */
  const viewedRef = useRef<string | null>(null);
  /**
   * Single-flight guard per conversation, covering only the send-to-start
   * window: up to and including the POST that starts the run.
   *
   * It is released the moment the run exists, because from then on the
   * generating state (below) is what refuses a second send - and that state is
   * also what the stop control and the rail indicator read.
   */
  const sendingRef = useRef<Record<string, boolean>>({});
  /**
   * Synchronous mirror of the generating set.
   *
   * The refusal in startGeneration cannot read React state: the keydown that
   * triggers it may run before React has re-rendered with the new map, and a
   * guard that reads stale state lets the second send through. A ref updates
   * in the same tick, so the refusal is deterministic.
   */
  const genRef = useRef<Record<string, boolean>>({});
  /**
   * Conversations whose run THIS tab started and is still watching.
   *
   * The server's "generating" flag and this tab's own set are two sources for
   * one fact. This ref is what keeps them from fighting: a server row that says
   * "not generating" clears a stale indicator, but never one this tab is still
   * driving - a status poll that lags behind the run must not flicker the rail.
   */
  const editingRunRef = useRef<Record<string, boolean>>({});
  /** Callbacks run when a generation for one conversation finishes. */
  const runListenersRef = useRef<Record<string, (() => void) | undefined>>({});
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
  /**
   * B1/B2: which conversations are generating, keyed by session id.
   *
   * This replaced ONE global boolean that froze the whole page: the composer
   * was disabled and the send path returned early, so a single in-flight answer
   * made every other conversation unusable. The key is the session, so two
   * conversations can be in flight at once and neither blocks the other.
   */
  const [generating, setGenerating] = useState<Record<string, boolean>>({});
  /** The execution behind each generating conversation, so it can be stopped. */
  const [runIds, setRunIds] = useState<Record<string, string>>({});
  /**
   * Conversations whose answer landed while the user was elsewhere (B1).
   *
   * The rail marks them so the finished answer is discoverable without being
   * yanked back to it - the view must not be hijacked by a background answer.
   */
  const [unseen, setUnseen] = useState<Record<string, boolean>>({});
  /** What POST /executions/{id}/run returned, kept per execution id. */
  const [execOutputs, setExecOutputs] = useState<
    Record<string, { text?: string; artifacts?: Artifact[] }>
  >({});
  /** The clipboard confirmation, keyed by message id. */
  const [copied, setCopied] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  /** «حافظه» - the compact memory surface folded into the chat page (B5). */
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryBusyId, setMemoryBusyId] = useState<string | null>(null);

  /**
   * Whether the conversation on screen is generating (B1/B2).
   *
   * Derived from the per-session map, so switching to another conversation
   * cannot inherit it: the composer is free and stays typable. Declared before
   * every effect because the transcript's scroll effect reads it.
   */
  const viewGenerating = activeId !== null && generating[activeId] === true;
  /** Credit gate: a blocked wallet disables the composer, nothing else. */
  const blocked = wallet?.blocked === true;
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
  /** Refresh the credit state; the composer and the banner both read it. */
  const loadWallet = useCallback(async () => {
    try {
      const w = await api<WalletMini>("GET", "/wallet");
      setWallet({ balance: w.balance, blocked: w.blocked });
    } catch (e) {
      // F: swallowing this left 'blocked' at its old value - the composer and
      // the zero-credit banner could both contradict the real balance.
      setError(e instanceof Error ? e.message : "دریافت وضعیت اعتبار ناموفق بود.");
    }
  }, []);

  /**
   * Take the server's own conversation list as the rail's truth (B4).
   *
   * The list endpoint reports a per-conversation "generating" flag, which is
   * how a run started in another tab - or finishing in one - shows up here
   * without a reload. The local set still wins for a conversation this tab is
   * driving, because that run's end is known here first.
   */
  const applyServerSessions = useCallback((items: SessionItem[]) => {
    setSessions(items);
    setGenerating((current) => {
      const next = { ...current };
      let changed = false;
      for (const row of items) {
        if (row.generating === true) {
          if (!next[row.id]) {
            next[row.id] = true;
            changed = true;
          }
        } else if (next[row.id] && editingRunRef.current[row.id] !== true) {
          // The server no longer reports it as generating and this tab is not
          // the one running it: the indicator is stale and goes.
          delete next[row.id];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, []);

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
    applyServerSessions(items);
    return items;
  }, [applyServerSessions]);

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
      setMessages((current) => mergeMessages(current, data.items ?? []));
      // Looking at a conversation is what marks its finished answer as seen.
      setUnseen((current) => (current[id] ? { ...current, [id]: false } : current));
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
    await loadWallet();
  }, [loadSessions, openSession, loadWallet]);

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
  }, [messages, viewGenerating]);


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

  /**
   * Send a message and start watching its answer.
   *
   * Concurrency choice (B2): a SECOND send into a conversation that is already
   * generating is refused, with a Persian sentence, and the text stays in the
   * composer. Queueing was the alternative. It was rejected because a queued
   * question has no visible state - the user cannot see what is waiting, cannot
   * cancel it, and if the first answer fails the queue either runs anyway or
   * silently disappears. It also bills twice for one gesture. Refusing keeps
   * the text where the user can edit or resend it, which is the smaller lie.
   *
   * The refusal is scoped to the SAME conversation: another conversation is
   * free to send at the same time, which is what B1/B2 asked for.
   */
  async function startGeneration(text: string): Promise<void> {
    // A brand-new organization has no sessions, so activeId is null on the
    // first screen. This used to return here with no message and no error,
    // which made the send button look broken. Create the session on demand
    // instead - typing a question should never require a separate click.
    let sessionId = activeIdRef.current;
    // Because the composer stays enabled while an answer is in flight (B2),
    // Enter can be pressed twice before a created session's id exists. This
    // ref, not the rendering state, is what makes that double-send single: a
    // "draft" key covers the window before the first session id exists, and the
    // session id covers every send after that.
    const guardKey = sessionId === null ? "draft" : sessionId;
    if (sendingRef.current[guardKey]) return;
    if (sessionId !== null && genRef.current[sessionId] === true) {
      setError("این گفتگو هنوز در حال پاسخ‌گویی است؛ تا پایان پاسخ صبر کنید یا آن را متوقف کنید.");
      return;
    }
    sendingRef.current[guardKey] = true;
    followRef.current = true;
    setLastSent(text);
    setInput("");
    setError(null);
    try {
      if (sessionId === null) {
        const createdSession = await api<{ id: string }>("POST", "/chat/sessions", {});
        sessionId = createdSession.id;
        activeIdRef.current = sessionId;
        viewedRef.current = sessionId;
        setActiveId(sessionId);
        // From here the conversation is real and may be returned to.
        saveChatView(sessionId, 0);
      }
      const target: string = sessionId;
      await api("POST", "/chat/sessions/" + target + "/messages", { text });
      setMessages((m) => [
        ...m,
        { id: "local-" + Date.now(), role: "USER", content: { text }, created_at: "" },
      ]);
      genRef.current = { ...genRef.current, [target]: true };
      editingRunRef.current[target] = true;
      setGenerating((g) => ({ ...g, [target]: true }));
      const created = await api<{ id: string }>("POST", "/executions", {
        input: { text },
        chat_session_id: target,
      });
      setRunIds((r) => ({ ...r, [target]: created.id }));
      // The window this guard protects is over: the run now exists, so a second
      // send must be refused by the generating state with a Persian reason -
      // not silently swallowed by this lock.
      sendingRef.current[target] = false;
      if (sessionId === target) sendingRef.current.draft = false;
      // Registered before the blocking POST returns: if the status poll sees
      // the run finish first, the handler still awaits this request and can
      // then decide what to say about it.
      const runFinished = new Promise<void>((resolve) => {
        runListenersRef.current[target] = resolve;
      });
      const done = await api<{
        status: string;
        output: { text?: string; artifacts?: Artifact[] } | null;
        error: { message: string } | null;
      }>("POST", "/executions/" + created.id + "/run");
      let settledByPoller = false;
      await Promise.race([
        runFinished.then(() => {
          settledByPoller = true;
        }),
        new Promise<void>((resolve) => {
          window.setTimeout(resolve, 0);
        }),
      ]);
      if (done.output) {
        setExecOutputs((o) => ({ ...o, [created.id]: done.output as { text?: string; artifacts?: Artifact[] } }));
      }
      if (settledByPoller) {
        // The live watch already reported the outcome and refreshed the
        // transcript; re-reporting it here would only duplicate the work.
      } else if (done.status === "CANCELLED") {
        // Cancelled before the answer landed: say so. A cancelled run must
        // never be dressed up as a completed answer.
        setError("پاسخ‌گویی متوقف شد.");
      } else if (done.status === "COMPLETED") {
        await openSession(target);
        await loadWallet();
      } else {
        setError(done.error?.message ?? "اجرای پاسخ ناموفق بود.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "ارسال پیام ناموفق بود.");
    } finally {
      sendingRef.current[guardKey] = false;
    }
  }

  /** The form and the retry control both route here; Enter is the PO's path. */
  function send(e?: React.FormEvent, override?: string) {
    e?.preventDefault();
    // The retry button passes the failed text explicitly: reading 'input' here
    // would see the already-cleared state and the retry would silently no-op.
    const text = (override ?? input).trim();
    if (!text) return;
    void startGeneration(text);
  }

  /**
   * Clear the generating state for a conversation and mark it unread when the
   * user is not looking at it.
   *
   * The view is never redirected: a background answer is a rail indicator, not
   * a jump. Yanking the pane to the generating conversation is exactly the
   * behaviour B1 reported as "cannot switch chats".
   */
  function settleRun(sessionId: string) {
    editingRunRef.current[sessionId] = false;
    if (genRef.current[sessionId]) {
      const next = { ...genRef.current };
      delete next[sessionId];
      genRef.current = next;
    }
    setGenerating((g) => {
      if (!g[sessionId]) return g;
      const next = { ...g };
      delete next[sessionId];
      return next;
    });
    if (viewedRef.current !== sessionId) {
      setUnseen((u) => ({ ...u, [sessionId]: true }));
    }
  }

  async function cancelRun(sessionId: string) {
    const executionId = runIds[sessionId];
    setCancelling(true);
    try {
      if (executionId) {
        // POST /executions/{id}/cancel is scoped to the caller: the service
        // resolves the row by organization_id and answers 404 for a foreign id
        // (backend/execution/service.py:cancel_execution).
        await api("POST", "/executions/" + executionId + "/cancel");
      }
      settleRun(sessionId);
      // Drop the run id too, so the status poll stops asking about a run that
      // is already over.
      setRunIds((r) => (r[sessionId] ? { ...r, [sessionId]: "" } : r));
      setError("پاسخ‌گویی متوقف شد.");
    } catch (err) {
      // The run keeps going, so its indicator must too: only the reason lands.
      setError(err instanceof Error ? err.message : "توقف پاسخ‌گویی ناموفق بود.");
    } finally {
      setCancelling(false);
    }
  }

  /**
   * B4: poll the transcript of the conversation on screen while it generates.
   *
   * "path === null" when idle is deliberate: the hook runs no timer at all, so
   * a settled page costs nothing. A failed poll keeps the rows already on
   * screen (the hook's own rule), so a dropped request cannot blank the thread.
   */
  const viewSessionId = activeId;
  const isViewGenerating = viewSessionId !== null && generating[viewSessionId] === true;
  const liveMessages = useLive<{ items: ChatMessage[] }>(
    isViewGenerating && viewSessionId
      ? "/chat/sessions/" + viewSessionId + "/messages"
      : null,
    2000,
  );

  useEffect(() => {
    if (!isViewGenerating) return;
    const items = liveMessages.data?.items;
    if (!items) return;
    // Only ever apply rows for the conversation on screen: a poll that lands
    // after the user switched away must not paint another thread's messages.
    if (viewSessionId === null || activeIdRef.current !== viewSessionId) return;
    setMessages((current) => mergeMessages(current, items));
  }, [liveMessages.data, isViewGenerating, viewSessionId]);

  /**
   * B4: the rail follows the server while anything is in flight.
   *
   * "path === null" while idle, so a settled page runs no timer. This is what
   * keeps another tab's (or another device's) running answer visible here, and
   * what clears the indicator once that run ends.
   */
  const anyGenerating = Object.keys(generating).length > 0;
  const liveSessions = useLive<{ items: SessionItem[] }>(
    anyGenerating ? "/chat/sessions" : null,
    2500,
  );

  useEffect(() => {
    const items = liveSessions.data?.items;
    if (!items) return;
    applyServerSessions(
      items.filter((s) => s.message_count === undefined || s.message_count > 0),
    );
  }, [liveSessions.data, applyServerSessions]);

  /**
   * B4 + the stop control: watch the run itself, so the answer lands and the
   * indicator clears without navigating away and back.
   *
   * The transcript poll alone cannot end the generating state: the server says
   * nothing about a conversation's in-flight flag on the message list, so the
   * execution's own status is the one honest source for "it is finished".
   */
  // Only watched while the conversation is genuinely generating: a run id left
  // over from a finished run must not keep a timer (or a request) alive, and
  // the completed run's output is already captured by the poller itself.
  const watchedRunId =
    viewSessionId !== null && generating[viewSessionId] === true
      ? runIds[viewSessionId] || null
      : null;
  const runStatus = useLive<{ status: string; output?: { text?: string; artifacts?: Artifact[] } | null }>(
    watchedRunId ? "/executions/" + watchedRunId : null,
    1000,
  );

  useEffect(() => {
    const data = runStatus.data;
    if (!watchedRunId || !viewSessionId || !data) return;
    if (viewSessionId !== null && generating[viewSessionId] !== true) return;
    if (data.status !== "COMPLETED" && data.status !== "FAILED" && data.status !== "CANCELLED") return;
    if (data.output) {
      setExecOutputs((o) => ({ ...o, [watchedRunId]: data.output as { text?: string; artifacts?: Artifact[] } }));
    }
    // The answer has landed, so the send path must not announce "still going"
    // when its own request finally returns - and the transcript must be
    // refreshed so the answer and its files appear without navigation (B4).
    runListenersRef.current[viewSessionId]?.();
    settleRun(viewSessionId);
    setRunIds((r) => (r[viewSessionId] ? { ...r, [viewSessionId]: "" } : r));
    void openSession(viewSessionId);
    void loadWallet();
    // settleRun and openSession are stable enough here: the effect is keyed on
    // the run status, and re-running it is a no-op once the id is cleared.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runStatus.data, watchedRunId, viewSessionId]);

  /** Load the user's memories when the surface is opened. */
  const loadMemories = useCallback(async () => {
    setMemoryError(null);
    try {
      const data = await api<{ memories: MemoryRow[] }>("GET", "/agent/memory");
      setMemories(data.memories ?? []);
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "دریافت حافظه ناموفق بود.");
    }
  }, []);

  useEffect(() => {
    if (memoryOpen) void loadMemories();
  }, [memoryOpen, loadMemories]);

  async function forgetMemory(id: string) {
    setMemoryBusyId(id);
    setMemoryError(null);
    try {
      await api("DELETE", "/agent/memory/" + id);
      setMemories((rows) => rows.filter((row) => row.id !== id));
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "حذف ناموفق بود.");
    } finally {
      setMemoryBusyId(null);
    }
  }

  async function addMemory() {
    const content = memoryDraft.trim();
    if (!content) return;
    setMemoryBusy(true);
    setMemoryError(null);
    try {
      // kind "fact" is the manual-entry kind, matching the deleted page.
      await api("POST", "/agent/memory", { content, kind: "fact" });
      setMemoryDraft("");
      await loadMemories();
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "افزودن ناموفق بود.");
    } finally {
      setMemoryBusy(false);
    }
  }

  /** Copy an answer, confirming it in the row rather than in a toast. */
  async function copyMessage(message: ChatMessage) {
    try {
      // Absent in an insecure context and in the desktop shell's older builds;
      // the guard keeps the click a no-op instead of a thrown rejection.
      if (!navigator.clipboard?.writeText) return;
      await navigator.clipboard.writeText(messageText(message));
      setCopied(message.id);
      window.setTimeout(() => setCopied((current) => (current === message.id ? null : current)), 2000);
    } catch {
      /* Nothing was copied; the label simply does not change. */
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
                    {/*
                      B1/B4: the row states that this conversation is generating
                      (or has an unseen answer) while the user is elsewhere. The
                      indicator is per row, so it is the discoverable stand-in
                      for the view jump that used to happen.
                    */}
                    {(generating[s.id] === true || unseen[s.id] === true) && (
                      <span
                        className="absolute end-2.5 top-1/2 -translate-y-1/2"
                        data-testid={generating[s.id] ? "chat-row-generating" : "chat-row-unseen"}
                      >
                        {generating[s.id] ? (
                          <span
                            role="status"
                            aria-label="در حال پاسخ‌گویی"
                            className="block size-3 animate-spin rounded-full border-2 border-primary border-t-transparent"
                          />
                        ) : (
                          <span
                            role="status"
                            aria-label="پاسخ تازه"
                            className="block size-2 rounded-full bg-primary"
                          />
                        )}
                      </span>
                    )}
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

      {/*
        B5: the memory surface lives inside the chat route now. The standalone
        «ایجنت من» page is being deleted, and memory is part of what the
        assistant knows about the user - not a separate destination.
      */}
      <Dialog open={memoryOpen} onOpenChange={setMemoryOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto">
          <DialogHeader className="text-start">
            <DialogTitle>حافظه</DialogTitle>
            <DialogDescription>
              چیزهایی که دستیار از گفتگوهای شما به خاطر سپرده است. هر مورد را می‌توانید حذف کنید.
            </DialogDescription>
          </DialogHeader>
          {memoryError && (
            <p role="alert" data-testid="memory-error" className="text-caption text-error">
              {memoryError}
            </p>
          )}
          <ul className="grid max-h-[40dvh] gap-2 overflow-y-auto" aria-label="فهرست حافظه">
            {memories.length === 0 && (
              <li className="text-caption text-muted-foreground">
                هنوز چیزی به خاطر سپرده نشده است.
              </li>
            )}
            {memories.map((memory) => (
              <li
                key={memory.id}
                data-testid="memory-row"
                className="flex items-start gap-3 rounded-control border border-border px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-micro text-muted-foreground">
                    <span className="rounded-pill bg-secondary px-2 py-0.5">
                      {KIND_LABEL[memory.kind] ?? memory.kind}
                    </span>
                    <span>{memory.created_at ? faRelative(memory.created_at) : ""}</span>
                  </div>
                  <p className="mt-1 text-caption text-foreground">{memory.content}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={"حذف این خاطره: " + memory.content}
                  data-testid="memory-forget"
                  disabled={memoryBusyId === memory.id}
                  onClick={() => void forgetMemory(memory.id)}
                >
                  <Trash2 aria-hidden className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
          <div className="grid gap-2">
            <textarea
              rows={2}
              maxLength={600}
              aria-label="افزودن به حافظه"
              data-testid="memory-draft"
              placeholder="چیزی که می‌خواهید دستیار همیشه بداند…"
              className="w-full rounded-control border border-border bg-card px-3 py-2 text-caption text-foreground outline-none focus-visible:border-primary"
              value={memoryDraft}
              onChange={(event) => setMemoryDraft(event.target.value)}
            />
            <div>
              <Button
                variant="outline"
                size="sm"
                data-testid="memory-add"
                disabled={memoryBusy || memoryDraft.trim().length === 0}
                onClick={() => void addMemory()}
              >
                {memoryBusy ? "در حال افزودن…" : "افزودن به حافظه"}
              </Button>
            </div>
          </div>
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
            data-testid="chat-memory-open"
            onClick={() => setMemoryOpen(true)}
          >
            <Brain aria-hidden className="size-4" />
            حافظه
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
          aria-busy={viewGenerating}
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
          {messages.length === 0 && !viewGenerating && (
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
                      {!isUser && (
                        <ArtifactList
                          message={m}
                          output={
                            m.execution_id
                              ? execOutputs[m.execution_id]
                              : Object.values(execOutputs).find((o) => o.text === messageText(m))
                          }
                        />
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
                  {!viewGenerating && (
                    <div className="mt-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button
                        type="button"
                        data-testid={"chat-copy-" + m.id}
                        className="inline-flex cursor-pointer items-center gap-[5px] rounded-xs border border-transparent px-2 py-[3px] text-micro font-semibold text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground min-h-11 md:min-h-0"
                        onClick={() => void copyMessage(m)}
                        aria-label={isUser ? "کپی پیام من" : "کپی پاسخ هوش سازمان"}
                      >
                        <Copy aria-hidden className="size-[13px] rtl:-scale-x-100" />
                        {copied === m.id ? "کپی شد" : "کپی"}
                      </button>
                      {copied === m.id && (
                        <span role="status" aria-live="polite" className="sr-only">
                          پاسخ کپی شد.
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </article>
            );
          })}

          {viewGenerating && (
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
                {lastSent && !viewGenerating ? (
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
              disabled={blocked}
            />
            {viewGenerating && (
              // Stopping is not the same as sending: it acts on the run, so it
              // sits beside the send control and only while one is in flight.
              <button
                type="button"
                data-testid="chat-stop"
                disabled={cancelling}
                onClick={() => {
                  if (activeId !== null) void cancelRun(activeId);
                }}
                className="flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-control border border-border px-3 text-caption font-bold text-foreground transition-colors hover:border-destructive hover:text-destructive disabled:opacity-55"
                aria-label="توقف پاسخ‌گویی"
              >
                <Square aria-hidden className="size-3.5" />
                توقف
              </button>
            )}
            <button
              type="submit"
              disabled={blocked || input.trim().length === 0}
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
