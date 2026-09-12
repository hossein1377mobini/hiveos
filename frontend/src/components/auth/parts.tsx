import { Check, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

// Shared building blocks of the 01-bootstrap mockup pages: brand block,
// global 6-step stepper, panel head, form field, vertical step list.
// Values follow assets/hiveos.css §۳/§۴/§۵/§۶/«مراحل عمودی».

export function AuthBrand({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-5 text-center">
      <span
        aria-hidden
        className="inline-flex size-[52px] items-center justify-center rounded-[14px] bg-navy-600 text-white shadow-[0_8px_20px_rgba(43,58,115,0.25)]"
      >
        <HouseLogo className="size-[26px]" />
      </span>
      <h1 className="mt-3.5 text-[21px] font-extrabold text-neutral-900">{title}</h1>
      <p className="mt-1 text-[13px] text-neutral-600">{subtitle}</p>
    </div>
  );
}

export function HouseLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

const STEPS = ["ساخت سازمان", "مدیر", "تأیید کد", "فضای کار", "هوش سازمان", "اسناد"] as const;

export function Stepper({ current }: { current: number }) {
  return (
    <div className="mb-[22px] flex items-center gap-0.5 overflow-hidden rounded-[14px] border border-neutral-200 bg-neutral-0 p-3 shadow-card">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const state = n < current ? "done" : n === current ? "active" : "todo";
        return (
          <div key={label} className="contents">
            {i > 0 && <div className={cn("mx-px h-0.5 min-w-1 flex-1 rounded-[2px]", n <= current ? "bg-success" : "bg-neutral-200")} />}
            <div className="flex shrink-0 items-center gap-[5px]">
              <span
                className={cn(
                  "inline-flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold",
                  state === "todo" && "border-neutral-200 bg-neutral-50 text-neutral-400",
                  state === "active" && "border-navy-600 bg-navy-600 text-white",
                  state === "done" && "border-success bg-success text-white",
                )}
              >
                {state === "done" ? <Check className="size-3" /> : faDigit(n)}
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-[11.5px]",
                  state === "active" ? "font-bold text-navy-600" : state === "done" ? "text-neutral-600" : "text-neutral-400",
                )}
              >
                {label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export type PanelTone = "primary" | "teal" | "amber" | "violet" | "success" | "error";

const TONE_CLASS: Record<PanelTone, string> = {
  primary: "bg-navy-50 text-navy-600",
  teal: "bg-teal-soft text-teal",
  amber: "bg-amber-soft text-amber",
  violet: "bg-violet-soft text-violet",
  success: "bg-success-bg text-success",
  error: "bg-error-bg text-error",
};

export function PanelHead({
  icon: Icon,
  tone = "primary",
  title,
  hint,
  center = false,
}: {
  icon: LucideIcon;
  tone?: PanelTone;
  title: string;
  hint?: string;
  center?: boolean;
}) {
  return (
    <div className={cn("mb-5 flex items-center gap-3", center && "justify-center")}>
      <span aria-hidden className={cn("inline-flex size-[38px] shrink-0 items-center justify-center rounded-[11px]", TONE_CLASS[tone])}>
        <Icon className="size-[19px]" />
      </span>
      <h2 className="text-[17px] font-extrabold text-neutral-900">{title}</h2>
      {hint && <span className="ms-auto whitespace-nowrap text-[11px] text-neutral-400">{hint}</span>}
    </div>
  );
}

export function Field({
  label,
  required = false,
  optional = false,
  hint,
  error,
  children,
  className,
}: {
  label: ReactNode;
  required?: boolean;
  optional?: boolean;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-[18px] last:mb-0", className)}>
      <label className="mb-1.5 block text-[13px] font-bold text-neutral-900">
        {label} {required && <span className="text-error">*</span>}
        {optional && <span className="text-[11.5px] font-normal text-neutral-400"> (اختیاری)</span>}
      </label>
      {children}
      {hint && <div className="mt-[5px] text-xs text-neutral-400">{hint}</div>}
      {error && <div className="mt-1.5 text-xs text-error">{error}</div>}
    </div>
  );
}

export function StepsList({
  items,
}: {
  items: ReadonlyArray<{ name: string; desc?: string; state: "done" | "active" | "todo" | "error"; marker?: string }>;
}) {
  return (
    <div>
      {items.map((item) => (
        <div key={item.name} className="relative flex gap-3.5 py-3">
          {!Object.is(items[items.length - 1], item) && (
            <span aria-hidden className="absolute bottom-0 end-[11px] top-[34px] w-0.5 bg-neutral-200" />
          )}
          <span
            className={cn(
              "z-[1] flex size-6 shrink-0 items-center justify-center rounded-full border-2 bg-neutral-0 text-[13px] font-bold",
              item.state === "todo" && "border-neutral-200 text-neutral-400",
              item.state === "active" && "border-navy-600 bg-navy-50 text-navy-600",
              item.state === "done" && "border-success bg-success text-white",
              item.state === "error" && "border-error bg-error text-white",
            )}
          >
            {item.state === "done" ? <Check className="size-3.5" /> : (item.marker ?? "")}
          </span>
          <div className="min-w-0 flex-1 pt-px">
            <div className="text-sm font-bold text-neutral-900">{item.name}</div>
            {item.desc && <div className="mt-0.5 text-xs text-neutral-600">{item.desc}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

const FA = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

/** Integer or digit string → Persian digits (no separators). */
export function faDigit(n: number | string): string {
  return String(n)
    .split("")
    .map((c) => FA[Number(c)] ?? c)
    .join("");
}