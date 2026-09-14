import {
  BellIcon,
  BookOpenIcon,
  CalendarClockIcon,
  ChevronRightIcon,
  HouseIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MessageCircleIcon,
  SearchIcon,
  WalletIcon,
  ZapIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useEffect, useRef, type ReactNode } from "react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "./ui/breadcrumb"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "./ui/sidebar"
import { Button } from "./ui/button"
import { CommandPalette, useCommandPalette, type CommandItem } from "./ui/command-palette"
import { clearToken } from "../api/client"
import type { SessionIdentity } from "../lib/session"
import { cn } from "../lib/utils"

/**
 * App shell — the organisation-facing frame.
 *
 * Rewritten for v0.5:
 *  - navigation is real routing (NavLink), so every section is linkable,
 *    bookmarkable and restores on refresh. [A4/D1]
 *  - a Ctrl/⌘+K command palette jumps between sections from anywhere. [D2]
 *  - the user chip shows the real organisation and user names when the API
 *    supplies them, falling back to the role label rather than hard-coding it. [D10]
 *  - the notification bell is a real control with a described, disabled state
 *    instead of an inert icon with a permanent red dot. [D11]
 *  - type sizes come from the seven-step scale. [B1]
 */

export type NavId = "chat" | "knowledge" | "usage" | "wallet" | "subscription"

type NavItem = { id: NavId; label: string; icon: LucideIcon; path: string; keyword: string }

const NAV_GROUPS: ReadonlyArray<{ section: string; items: readonly NavItem[] }> = [
  {
    section: "هوش سازمان",
    items: [
      {
        id: "chat",
        label: "گفتگو",
        icon: MessageCircleIcon,
        path: "/chat",
        keyword: "هوش مصنوعی پرسش پاسخ گفتگو",
      },
    ],
  },
  {
    section: "دانش سازمان",
    items: [
      {
        id: "knowledge",
        label: "دانش سازمان",
        icon: BookOpenIcon,
        path: "/knowledge",
        keyword: "اسناد مدرک پوشه آپلود جستجو",
      },
    ],
  },
  {
    section: "مدیریت",
    items: [
      {
        id: "usage",
        label: "اعتبار و مصرف",
        icon: ZapIcon,
        path: "/usage",
        keyword: "توکن هزینه مصرف اعتبار",
      },
      {
        id: "wallet",
        label: "کیف پول",
        icon: WalletIcon,
        path: "/wallet",
        keyword: "شارژ پرداخت تراکنش موجودی",
      },
      {
        id: "subscription",
        label: "اشتراک",
        icon: CalendarClockIcon,
        path: "/subscription",
        keyword: "پلن تمدید دوره اشتراک",
      },
    ],
  },
]

export const NAV_LABEL: Record<NavId, string> = {
  chat: "گفتگو",
  knowledge: "دانش سازمان",
  usage: "اعتبار و مصرف",
  wallet: "کیف پول",
  subscription: "اشتراک",
}

const PATH_LABEL: Record<string, string> = {
  "/chat": "گفتگو",
  "/knowledge": "دانش سازمان",
  "/usage": "اعتبار و مصرف",
  "/wallet": "کیف پول",
  "/subscription": "اشتراک",
  "/admin": "پنل مدیریت",
}

function UserMenu({ identity }: { identity?: SessionIdentity | null }) {
  const navigate = useNavigate()
  const name = identity?.user_name?.trim() || "مدیر"
  const role = identity?.organization_name?.trim()
    ? identity.organization_name
    : "مدیر سازمان"
  const initial = name.slice(0, 1)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent">
          <span
            aria-hidden
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-primary text-micro font-bold text-sidebar-primary-foreground"
          >
            {initial}
          </span>
          <span className="grid min-w-0 flex-1 text-start leading-tight">
            <span className="truncate text-caption font-bold text-sidebar-foreground">{name}</span>
            <span className="truncate text-micro text-muted-foreground">{role}</span>
          </span>
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="min-w-[190px]">
        <DropdownMenuLabel className="text-micro text-muted-foreground">حساب کاربری</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => {
            clearToken()
            navigate("/login", { replace: true })
          }}
        >
          <LogOutIcon data-icon="inline-start" className="rtl:-scale-x-100" />
          خروج
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function AppShell({
  children,
  breadcrumb,
  actions,
  flush = false,
  identity,
}: {
  children: ReactNode
  /** Overrides the breadcrumb leaf; defaults to the active route label. */
  breadcrumb?: ReactNode
  /** Extra topbar controls (e.g. chat search) — rendered before the bell. */
  actions?: ReactNode
  /** Full-height pages (chat) render without main padding. */
  flush?: boolean
  identity?: SessionIdentity | null
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const palette = useCommandPalette()
  const mainRef = useRef<HTMLElement>(null)

  // Skip the very first render: focusing <main> on initial load would scroll
  // past the header and swallow the browser's own focus behaviour.
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [location.pathname])

  const activeItem = NAV_GROUPS.flatMap((group) => group.items).find((item) =>
    location.pathname.startsWith(item.path),
  )
  const crumbLabel = activeItem ? activeItem.label : (PATH_LABEL[location.pathname] ?? "")

  const commands: CommandItem[] = [
    ...NAV_GROUPS.flatMap((group) =>
      group.items.map((item) => ({
        id: "nav-" + item.id,
        label: item.label,
        group: group.section,
        path: item.path,
        icon: item.icon,
        keywords: [item.keyword],
      })),
    ),
    {
      id: "nav-admin",
      label: "پنل مدیریت سامانه",
      group: "سامانه",
      path: "/admin",
      icon: LayoutDashboardIcon,
      keywords: ["ادمین", "مدیریت", "سازمان‌ها", "تنظیمات", "رویدادها"],
    },
  ]

  return (
    <SidebarProvider className="min-h-dvh">
      <Sidebar side="right" collapsible="icon" className="border-e">
        <SidebarHeader className="flex-row items-center gap-2.5 px-2 py-3.5">
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-control bg-sidebar-primary text-sidebar-primary-foreground"
          >
            <HouseIcon className="size-4.5" />
          </span>
          <span className="truncate text-heading font-bold tracking-tight text-sidebar-foreground" dir="ltr">
            HiveOS
          </span>
        </SidebarHeader>
        <SidebarContent>
          {NAV_GROUPS.map((group) => (
            <SidebarGroup key={group.section}>
              <SidebarGroupLabel className="text-micro font-bold tracking-[0.4px]">
                {group.section}
              </SidebarGroupLabel>
              <SidebarMenu>
                {group.items.map(({ id, label, icon: Icon, path }) => (
                  <SidebarMenuItem key={id}>
                    <SidebarMenuButton asChild tooltip={label}>
                      <NavLink
                        to={path}
                        className="h-auto py-2 text-caption font-medium data-[active=true]:font-bold"
                      >
                        <Icon aria-hidden />
                        <span>{label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroup>
          ))}
        </SidebarContent>
        <SidebarFooter className="border-t">
          <SidebarMenu>
            <SidebarMenuItem>
              <UserMenu identity={identity} />
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2.5 border-b border-border bg-background/95 px-4 backdrop-blur-sm">
          <SidebarTrigger aria-label="نمایش یا پنهان کردن ناوبری" />
          <Breadcrumb className="min-w-0">
            <BreadcrumbList className="flex-nowrap text-caption">
              <BreadcrumbItem className="hidden sm:inline-flex">
                <BreadcrumbLink asChild>
                  <button
                    type="button"
                    onClick={() => navigate("/chat")}
                    className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground"
                  >
                    HiveOS
                  </button>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator className="hidden sm:inline-flex rtl:-scale-x-100">
                <ChevronRightIcon className="size-3.5" />
              </BreadcrumbSeparator>
              <BreadcrumbItem className="min-w-0">
                <BreadcrumbPage className="truncate font-bold text-foreground">
                  {breadcrumb ?? crumbLabel}
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>

          <div className="ms-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => palette.setOpen(true)}
              className="hidden rounded-control text-muted-foreground md:inline-flex"
              aria-keyshortcuts="Control+K"
            >
              <SearchIcon className="size-3.5" />
              جستجو
              <kbd className="mono ms-1 rounded-xs border border-border bg-secondary px-1 py-px text-micro">
                Ctrl K
              </kbd>
            </Button>
            {actions}
            <Button
              variant="outline"
              size="icon-sm"
              disabled
              aria-label="اعلان‌ها — به‌زودی"
              title="مرکز اعلان‌ها در نسخهٔ بعدی فعال می‌شود."
              className="rounded-control"
            >
              <BellIcon className="size-4" />
            </Button>
          </div>
        </header>
        {/* A client-side route change does not move focus: a keyboard or screen
            reader user stays parked on the sidebar link they just activated and
            never learns the page content changed. Focus is moved to the main
            landmark, which carries an accessible name. tabIndex={-1} makes it
            programmatically focusable without adding a tab stop. [E1] */}
        <main
          ref={mainRef}
          tabIndex={-1}
          aria-label={crumbLabel || "محتوای صفحه"}
          className={cn(
            "outline-none",
            flush ? "flex min-w-0 flex-1 flex-col pb-0" : "min-w-0 flex-1 px-6 pb-12 pt-6",
          )}
        >
          {children}
        </main>
      </SidebarInset>

      <CommandPalette items={commands} open={palette.open} onOpenChange={palette.setOpen} />
    </SidebarProvider>
  )
}

export type { NavItem }
