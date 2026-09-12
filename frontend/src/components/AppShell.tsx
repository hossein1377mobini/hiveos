import {
  BellIcon,
  BookOpenIcon,
  CalendarClockIcon,
  ChevronRightIcon,
  HouseIcon,
  LogOutIcon,
  MessageCircleIcon,
  WalletIcon,
  ZapIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

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
import { LoadingButton } from "./ui/button-loading"
import { clearToken } from "../api/client"

// App shell — mockup 10-shell/01-app-shell.html. Structure comes from the
// official Sidebar + Breadcrumb + DropdownMenu primitives (RTL-aware, responsive
// and keyboard-navigable out of the box); the 248px rail and 58px topbar of the
// mockup are expressed through the SidebarProvider width token and offsets.

export type NavId = "chat" | "knowledge" | "usage" | "wallet" | "subscription"

type NavItem = { id: NavId; label: string; icon: LucideIcon }

const NAV_GROUPS: ReadonlyArray<{ section: string; items: readonly NavItem[] }> = [
  { section: "هوش سازمان", items: [{ id: "chat", label: "گفتگو", icon: MessageCircleIcon }] },
  { section: "دانش سازمان", items: [{ id: "knowledge", label: "دانش سازمان", icon: BookOpenIcon }] },
  {
    section: "مدیریت",
    items: [
      { id: "usage", label: "اعتبار و مصرف", icon: ZapIcon },
      { id: "wallet", label: "کیف پول", icon: WalletIcon },
      { id: "subscription", label: "اشتراک", icon: CalendarClockIcon },
    ],
  },
]

const NAV_LABEL: Record<NavId, string> = {
  chat: "گفتگو",
  knowledge: "دانش سازمان",
  usage: "اعتبار و مصرف",
  wallet: "کیف پول",
  subscription: "اشتراک",
}

function UserChip() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent">
          <span
            aria-hidden
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-primary text-xs font-extrabold text-sidebar-primary-foreground"
          >
            م
          </span>
          <span className="grid min-w-0 flex-1 text-start leading-tight">
            <span className="truncate text-[13px] font-bold text-sidebar-foreground">مدیر</span>
            <span className="truncate text-[11px] text-muted-foreground">مدیر سازمان</span>
          </span>
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="min-w-[180px]">
        <DropdownMenuLabel className="text-[11px] text-muted-foreground">حساب کاربری</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => {
            clearToken()
            location.reload()
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
  active,
  onNavigate,
  breadcrumb,
  actions,
  flush = false,
}: {
  children: ReactNode
  active?: NavId
  onNavigate?: (id: NavId) => void
  /** Topbar breadcrumb; defaults to the active section label (mockup: crumbs). */
  breadcrumb?: ReactNode
  /** Extra topbar controls (e.g. chat search) — rendered before the bell. */
  actions?: ReactNode
  /** Full-height pages (chat) render without main padding — mockup .main--flush. */
  flush?: boolean
}) {
  return (
    <SidebarProvider className="min-h-dvh">
      <Sidebar side="right" collapsible="icon" className="border-e">
        <SidebarHeader className="flex-row items-center gap-2.5 px-2 py-3.5">
          <span
            aria-hidden
            className="flex size-[34px] shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground"
          >
            <HouseIcon className="size-[18px]" />
          </span>
          <span className="truncate text-[14.5px] font-extrabold text-sidebar-foreground" dir="ltr">
            HiveOS
          </span>
        </SidebarHeader>
        <SidebarContent>
          {NAV_GROUPS.map((group) => (
            <SidebarGroup key={group.section}>
              <SidebarGroupLabel className="text-[10.5px] font-extrabold tracking-[0.5px]">
                {group.section}
              </SidebarGroupLabel>
              <SidebarMenu>
                {group.items.map(({ id, label, icon: Icon }) => (
                  <SidebarMenuItem key={id}>
                    <SidebarMenuButton
                      type="button"
                      isActive={active === id}
                      aria-current={active === id ? "page" : undefined}
                      tooltip={label}
                      onClick={() => onNavigate?.(id)}
                      className="h-auto py-[9px] text-[13.5px] font-semibold data-[active=true]:font-bold"
                    >
                      <Icon aria-hidden />
                      <span>{label}</span>
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
              <UserChip />
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-30 flex h-[58px] shrink-0 items-center gap-3 border-b bg-background px-[22px]">
          <SidebarTrigger aria-label="نمایش یا پنهان کردن ناوبری" />
          <Breadcrumb className="min-w-0">
            <BreadcrumbList className="flex-nowrap text-[13px]">
              {active ? (
                <>
                  <BreadcrumbItem className="hidden sm:inline-flex">
                    <BreadcrumbLink asChild>
                      <LoadingButton type="button" onClick={() => onNavigate?.(active)} className="cursor-pointer">
                        HiveOS
                      </LoadingButton>
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator className="hidden sm:inline-flex rtl:-scale-x-100">
                    <ChevronRightIcon />
                  </BreadcrumbSeparator>
                </>
              ) : null}
              <BreadcrumbItem className="min-w-0">
                <BreadcrumbPage className="truncate font-bold text-foreground">
                  {breadcrumb ?? (active ? NAV_LABEL[active] : "")}
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <div className="ms-auto flex items-center gap-2">
            {actions}
            <SidebarMenuButton
              type="button"
              size="lg"
              aria-label="اعلان‌ها"
              tooltip="اعلان‌ها"
              className="relative size-9 justify-center rounded-lg border bg-background p-0 text-muted-foreground hover:text-foreground"
            >
              <BellIcon aria-hidden className="size-[17px]" />
              <span
                aria-hidden
                className="absolute end-2 top-[7px] size-[7px] rounded-full border-[1.5px] border-background bg-error"
              />
            </SidebarMenuButton>
          </div>
        </header>
        <main className={flush ? "flex min-w-0 flex-1 flex-col pb-0" : "min-w-0 flex-1 px-7 pb-12 pt-6"}>
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

export type { NavItem }
export { NAV_LABEL }
