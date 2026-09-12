import { Bell, BookOpen, CalendarClock, House, LogOut, MessageCircle, MoreVertical, Wallet, Zap } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { clearToken } from "../api/client";
import { cn } from "../lib/utils";

// App shell — mockup 10-shell/01-app-shell.html + the real shell markup used by
// every post-login mockup page (sidebar 248px on inline-start, brand block,
// section headings, user chip with «خروج» menu, 58px topbar with breadcrumbs).
// Sidebar keeps five items incl. «اشتراک» (dev-guidelines §2, PO 2026-09-14).

type NavItem = { id: NavId; label: string; icon: ComponentType<{ className?: string }> };

const NAV_GROUPS: ReadonlyArray<{ section: string; items: readonly NavItem[] }> = [
  { section: "هوش سازمان", items: [{ id: "chat", label: "گفتگو", icon: MessageCircle }] },
  { section: "دانش سازمان", items: [{ id: "knowledge", label: "دانش سازمان", icon: BookOpen }] },
  {
    section: "مدیریت",
    items: [
      { id: "usage", label: "اعتبار و مصرف", icon: Zap },
      { id: "wallet", label: "کیف پول", icon: Wallet },
      { id: "subscription", label: "اشتراک", icon: CalendarClock },
    ],
  },
];

export type NavId = "chat" | "knowledge" | "usage" | "wallet" | "subscription";

const NAV_LABEL: Record<NavId, string> = {
  chat: "گفتگو",
  knowledge: "دانش سازمان",
  usage: "اعتبار و مصرف",
  wallet: "کیف پول",
  subscription: "اشتراک",
};

function UserChip() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className={cn("relative cursor-pointer rounded-[10px] p-2 hover:bg-neutral-50", open && "bg-neutral-50")}>
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-2.5 text-start"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-navy-600 text-xs font-extrabold text-white"
        >
          م
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-bold text-neutral-900">مدیر</span>
          <span className="block text-[11px] text-neutral-400">مدیر سازمان</span>
        </span>
        <MoreVertical aria-hidden className="size-[15px] text-neutral-400" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute bottom-[calc(100%+8px)] end-2 z-40 min-w-[180px] rounded-[12px] border border-neutral-200 bg-neutral-0 p-1.5 shadow-pop"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              clearToken();
              location.reload();
            }}
            className="flex w-full cursor-pointer items-center gap-2.5 rounded-[9px] px-3 py-2.5 text-[13px] font-semibold text-neutral-600 transition-colors hover:bg-neutral-50 hover:text-neutral-900"
          >
            <LogOut aria-hidden className="size-4 rtl:-scale-x-100" />
            خروج
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({
  children,
  active,
  onNavigate,
  breadcrumb,
  actions,
  flush = false,
}: {
  children: ReactNode;
  active?: NavId;
  onNavigate?: (id: NavId) => void;
  /** Topbar breadcrumb; defaults to the active section label (mockup: crumbs). */
  breadcrumb?: ReactNode;
  /** Extra topbar icon buttons (e.g. chat search) — rendered before the bell. */
  actions?: ReactNode;
  /** Full-height pages (chat) render without main padding — mockup .main--flush. */
  flush?: boolean;
}) {
  return (
    <div className="flex min-h-dvh bg-neutral-50">
      <aside
        aria-label="ناوبری اصلی"
        className="sticky top-0 flex h-dvh w-[248px] shrink-0 flex-col border-e border-neutral-200 bg-neutral-0"
      >
        <div className="flex items-center gap-2.5 px-4 pb-3.5 pt-[18px]">
          <span
            aria-hidden
            className="flex size-[34px] shrink-0 items-center justify-center rounded-[10px] bg-navy-600 text-white"
          >
            <House className="size-[18px]" />
          </span>
          <span className="text-[14.5px] font-extrabold text-neutral-900" dir="ltr">
            HiveOS
          </span>
        </div>
        <nav className="flex-1 overflow-auto px-3 pt-1" aria-label="بخش‌ها">
          {NAV_GROUPS.map((group) => (
            <div key={group.section}>
              <div className="px-2.5 pb-1.5 pt-3.5 text-[10.5px] font-extrabold tracking-[0.5px] text-neutral-400">
                {group.section}
              </div>
              <ul>
                {group.items.map(({ id, label, icon: Icon }) => {
                  const isActive = active === id;
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        onClick={() => onNavigate?.(id)}
                        aria-current={isActive ? "page" : undefined}
                        className={cn(
                          "relative mb-0.5 flex w-full cursor-pointer items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-[13.5px] font-semibold transition-colors",
                          isActive
                            ? "bg-navy-50 font-bold text-navy-600 before:absolute before:-start-3 before:bottom-2 before:top-2 before:w-[3px] before:rounded-[3px] before:bg-navy-600 before:content-['']"
                            : "text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900",
                        )}
                      >
                        <Icon aria-hidden className="size-[17px]" />
                        {label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        <div className="border-t border-neutral-200 p-3">
          <UserChip />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-[58px] shrink-0 items-center gap-3 border-b border-neutral-200 bg-neutral-0 px-[22px]">
          <div className="flex min-w-0 items-center gap-1.5 text-[13px] text-neutral-600">
            {breadcrumb ?? <span className="font-bold text-neutral-900">{active ? NAV_LABEL[active] : ""}</span>}
          </div>
          <div className="ms-auto flex items-center gap-2">
            {actions}
            <button
              type="button"
              aria-label="اعلان‌ها"
              className="relative flex size-9 cursor-pointer items-center justify-center rounded-[10px] border border-neutral-200 bg-neutral-0 text-neutral-600 transition-colors hover:bg-neutral-50 hover:text-neutral-900"
            >
              <Bell aria-hidden className="size-[17px]" />
              <span
                aria-hidden
                className="absolute end-2 top-[7px] size-[7px] rounded-full border-[1.5px] border-white bg-error"
              />
            </button>
          </div>
        </header>
        <main className={cn("min-w-0 flex-1", flush ? "flex flex-col" : "px-7 pb-12 pt-6")}>{children}</main>
      </div>
    </div>
  );
}

export type { NavItem };
export { NAV_LABEL };
