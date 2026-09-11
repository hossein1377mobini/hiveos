import { BookOpen, CalendarClock, CreditCard, MessageCircle, Wallet } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

// v0.1 sidebar sections — dev-guidelines-v0.1 §2 (five items incl. «اشتراک»,
// PO decision 2026-09-14). Labels follow product/terminology §7.
const NAV_ITEMS: ReadonlyArray<{
  id: NavId;
  label: string;
  icon: ComponentType<{ className?: string }>;
}> = [
  { id: "chat", label: "گفتگو", icon: MessageCircle },
  { id: "knowledge", label: "دانش سازمان", icon: BookOpen },
  { id: "usage", label: "اعتبار و مصرف", icon: CreditCard },
  { id: "wallet", label: "کیف پول", icon: Wallet },
  { id: "subscription", label: "اشتراک", icon: CalendarClock },
];

export type NavId = "chat" | "knowledge" | "usage" | "wallet" | "subscription";

// App shell skeleton per ui-mockups spec §1.2: full-width header, sidebar on
// inline-start (right in RTL), main region. v0.1 nav is a static placeholder —
// sections become routable as their epics land (S1..S4, development-workflow §8).
// The session list placement (spec Q3) is a PO decision, so the sidebar keeps
// only the nav block for now.
export function AppShell({
  children,
  active,
  onNavigate,
}: {
  children: ReactNode;
  active?: NavId;
  onNavigate?: (id: NavId) => void;
}) {
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex shrink-0 items-center gap-4 border-b border-neutral-200 bg-neutral-0 px-4 py-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex size-8 items-center justify-center rounded-control bg-navy-600 text-sm font-bold text-white"
          >
            H
          </span>
          <span className="text-base font-bold" dir="ltr">
            HiveOS
          </span>
        </div>
        <div className="text-sm">
          <span className="font-medium">فضای کار</span>
          <span className="ms-2 text-xs text-neutral-400">v0.1</span>
        </div>
        <div className="ms-auto flex items-center gap-2">
          <span
            aria-hidden
            className="flex size-8 items-center justify-center rounded-full bg-navy-50 text-sm font-bold text-navy-800"
          >
            م
          </span>
          <span className="text-sm">مدیر</span>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="ناوبری اصلی" className="w-56 shrink-0 border-e border-neutral-200 bg-neutral-0 p-3">
          <ul className="space-y-1">
            {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onNavigate?.(id)}
                  aria-current={active === id ? "page" : undefined}
                  className={
                    "flex w-full items-center gap-2 rounded-control px-3 py-2 text-sm " +
                    (active === id
                      ? "bg-navy-50 font-bold text-navy-700"
                      : "text-neutral-600 hover:bg-neutral-50")
                  }
                >
                  <Icon aria-hidden className="size-4" />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <main className="min-w-0 flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
