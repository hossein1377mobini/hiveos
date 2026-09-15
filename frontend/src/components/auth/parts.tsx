import { Children, cloneElement, isValidElement, useId } from "react"
import { CheckIcon, type LucideIcon } from "lucide-react"


import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item"
import { Field as FieldPrimitive, FieldDescription, FieldLabel } from "@/components/ui/field"
import { cn } from "@/lib/utils"

/**
 * Shared building blocks of the 01-bootstrap pages. Each one is a thin, typed
 * composition over an official shadcn primitive (Field, Item, Separator) so the
 * shape, spacing scale and RTL behaviour stay in the registry — HiveOS only
 * supplies the values from design-system §3..§6.
 */

export function AuthBrand({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-5 flex flex-col items-center gap-3 text-center">
      <span
        aria-hidden
        className="inline-flex size-[52px] items-center justify-center rounded-card bg-primary text-primary-foreground shadow-card"
      >
        <HouseLogo className="size-[26px]" />
      </span>
      <div className="flex flex-col gap-1">
        <h1 className="text-title text-foreground">{title}</h1>
        <p className="text-caption text-muted-foreground">{subtitle}</p>
      </div>
    </div>
  )
}

export function HouseLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  )
}

const STEPS = ["ساخت سازمان", "مدیر", "تأیید کد", "فضای کار", "هوش سازمان", "اسناد"] as const

export function Stepper({ current }: { current: number }) {
  return (
    <div
      role="group"
      aria-label="مراحل راه‌اندازی"
      data-slot="stepper"
      className="mb-[22px] flex items-center gap-0.5 overflow-hidden rounded-card border bg-card p-3 shadow-card"
    >
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n < current ? "done" : n === current ? "active" : "todo"
        return (
          <div key={label} className="contents">
            {i > 0 && (
              <div
                aria-hidden
                className={cn("mx-px h-0.5 min-w-1 flex-1 rounded-xs", n <= current ? "bg-success" : "bg-border")}
              />
            )}
            <div className="flex shrink-0 items-center gap-[5px]">
              <span
                data-state={state}
                className={cn(
                  "inline-flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-micro font-bold",
                  state === "todo" && "border-border bg-secondary text-muted-foreground",
                  state === "active" && "border-primary bg-primary text-primary-foreground",
                  state === "done" && "border-success bg-success text-primary-foreground",
                )}
              >
                {state === "done" ? <CheckIcon className="size-3" /> : faDigit(n)}
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-micro",
                  state === "active" ? "font-bold text-primary" : state === "done" ? "text-muted-foreground" : "text-muted-foreground/70",
                )}
              >
                {label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export type PanelTone = "primary" | "teal" | "amber" | "violet" | "success" | "error"

const TONE_CLASS: Record<PanelTone, string> = {
  primary: "bg-info-bg text-info",
  teal: "bg-teal-soft text-teal",
  amber: "bg-amber-soft text-amber",
  violet: "bg-violet-soft text-violet",
  success: "bg-success-bg text-success",
  error: "bg-error-bg text-error",
}

export function PanelHead({
  icon: Icon,
  tone = "primary",
  title,
  hint,
  center = false,
}: {
  icon: LucideIcon
  tone?: PanelTone
  title: string
  hint?: string
  center?: boolean
}) {
  return (
    <div className={cn("mb-5 flex items-center gap-3", center && "justify-center")}>
      <span aria-hidden className={cn("inline-flex size-[38px] shrink-0 items-center justify-center rounded-control", TONE_CLASS[tone])}>
        <Icon className="size-[19px]" />
      </span>
      <h2 className="text-heading text-foreground">{title}</h2>
      {hint && <span className="ms-auto whitespace-nowrap text-micro text-muted-foreground">{hint}</span>}
    </div>
  )
}

/**
 * Form field — the official Field/FieldLabel/FieldDescription trio plus the
 * HiveOS label affordances (required star, «اختیاری» mark).
 */
export function Field({
  label,
  required = false,
  optional = false,
  hint,
  error,
  children,
  className,
  htmlFor,
}: {
  label: React.ReactNode
  required?: boolean
  optional?: boolean
  hint?: React.ReactNode
  error?: React.ReactNode
  children: React.ReactNode
  className?: string
  /** Filled in automatically; pass it only to point at a control Field cannot see. */
  htmlFor?: string
}) {
  // The label used to be rendered with htmlFor={undefined} because no caller
  // ever passed one, so none of the signup fields were named for a screen
  // reader — the label was decoration. The first real control among the children
  // now receives a generated id and the label points at it. [E]
  const generatedId = useId()
  const controlId = htmlFor ?? generatedId
  // Children is an array whenever a field has more than one child (the input plus
  // a helper row), and isValidElement is false for an array, so the whole tree
  // used to be skipped in exactly those cases.
  const labelled = Array.isArray(children)
    ? Children.toArray(children).map((child) => withControlId(child, controlId))
    : withControlId(children, controlId)

  return (
    <FieldPrimitive data-invalid={error ? true : undefined} className={cn("mb-[18px] gap-1.5 last:mb-0", className)}>
      <FieldLabel htmlFor={controlId} className="w-auto gap-1 text-caption font-bold text-foreground">
        {label}
        {required && <span className="text-error">*</span>}
        {optional && <span className="text-micro font-normal text-muted-foreground">(اختیاری)</span>}
      </FieldLabel>
      {labelled}
      {hint && <FieldDescription className="text-caption">{hint}</FieldDescription>}
      {error && <FieldDescription className="text-caption text-error">{error}</FieldDescription>}
    </FieldPrimitive>
  )
}

/** Native elements a <label for> may legally point at. */
const LABELLABLE_TAGS = new Set(["input", "textarea", "select", "button"])

/**
 * Give the field's first real control the field's id, so the label resolves to
 * something a browser and a screen reader both accept.
 *
 * The control is not always the first child: the mobile field wraps its input in
 * an input-group with a +98 prefix, and the password field wraps it with the eye
 * toggle. Pointing the label at those wrappers is invalid — a browser ignores a
 * label aimed at a <div> and the field ends up unnamed. So the tree is walked
 * until something labellable is found, and only that element is rebuilt.
 */
function withControlId(node: React.ReactNode, id: string): React.ReactNode {
  if (!isValidElement(node)) return node

  const props = node.props as {
    id?: string
    "data-slot"?: string
    children?: React.ReactNode
  }
  // An explicit id is the caller's decision and is left alone.
  if (props.id) return node
  const source = node as React.ReactElement<{ id?: string }>

  const tag = typeof node.type === "string" ? node.type : ""

  // A plain HTML element is either the control or a layout wrapper. A wrapper
  // (the +98 input-group, the password eye) is recursed into; a labellable tag
  // is the control.
  if (tag) {
    if (tag !== "button" && LABELLABLE_TAGS.has(tag)) return cloneElement(source, { id })
    const nested = descend(props.children, id)
    return nested ? cloneElement(node as React.ReactElement<{ children?: React.ReactNode }>, { children: nested }) : node
  }

  // A component. Input/Textarea render their id straight onto the control, but a
  // Radix Root (Select) renders no element at all — its id would go nowhere. So
  // the children are searched first, and the component is only given the id when
  // nothing inside it could take one. [E]
  const nested = descend(props.children, id)
  if (nested) {
    return cloneElement(node as React.ReactElement<{ children?: React.ReactNode }>, { children: nested })
  }
  return cloneElement(source, { id })
}

/** Rebuild the children list with the id placed, or return null if nothing took it. */
function descend(children: React.ReactNode, id: string): React.ReactNode | null {
  const items = Children.toArray(children)
  let patched = false
  const next = items.map((child) => {
    if (patched) return child
    const candidate = withControlId(child, id)
    if (candidate !== child) patched = true
    return candidate
  })
  return patched ? next : null
}

export function StepsList({
  items,
}: {
  items: ReadonlyArray<{ name: string; desc?: string; state: "done" | "active" | "todo" | "error"; marker?: string }>
}) {
  return (
    <Item variant="default" size="default" className="flex-col gap-0 rounded-none border-0 p-0">
      {items.map((item, index) => (
        <div key={item.name} className="contents">
          {index > 0 && (
            <span aria-hidden className="ms-[11px] h-2 w-0.5 self-start bg-border" />
          )}
          <Item className="items-start gap-3.5 rounded-none border-0 px-0 py-3">
            <ItemMedia
              data-state={item.state}
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full border-2 bg-card text-caption font-bold",
                item.state === "todo" && "border-border text-muted-foreground",
                item.state === "active" && "border-primary bg-info-bg text-primary",
                item.state === "done" && "border-success bg-success text-primary-foreground",
                item.state === "error" && "border-error bg-error text-primary-foreground",
              )}
            >
              {item.state === "done" ? <CheckIcon className="size-3.5" /> : (item.marker ?? "")}
            </ItemMedia>
            <ItemContent className="gap-0.5 pt-px">
              <ItemTitle className="text-body font-bold">{item.name}</ItemTitle>
              {item.desc && <ItemDescription className="text-caption">{item.desc}</ItemDescription>}
            </ItemContent>
          </Item>
        </div>
      ))}
    </Item>
  )
}

const FA = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"]

/** Integer or digit string → Persian digits (no separators). */
export function faDigit(n: number | string): string {
  return String(n)
    .split("")
    .map((c) => FA[Number(c)] ?? c)
    .join("")
}
