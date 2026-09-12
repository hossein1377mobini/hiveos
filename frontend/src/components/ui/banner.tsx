import { AlertCircle, CheckCircle2, Info, ShieldAlert, type LucideIcon } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

// HiveOS Banner/Alert — mockup §۱۱ (.banner.error/success/warning/info/plain with
// 18px icon, bold title, secondary body, optional actions row).
type BannerTone = "error" | "success" | "warning" | "info" | "plain";

const TONE_ICON: Record<BannerTone, LucideIcon> = {
  error: AlertCircle,
  success: CheckCircle2,
  warning: ShieldAlert,
  info: Info,
  plain: Info,
};

const TONE_CLASS: Record<BannerTone, string> = {
  error: "border-error bg-error-bg text-error",
  success: "border-success bg-success-bg text-success",
  warning: "border-warning bg-warning-bg text-warning",
  info: "border-navy-200 bg-navy-50 text-navy-600",
  plain: "border-neutral-200 bg-neutral-50 text-neutral-600",
};

export function Banner({
  tone = "info",
  title,
  children,
  actions,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  tone?: BannerTone;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  const Icon = TONE_ICON[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-2.5 rounded-control border p-3 text-[13px]", TONE_CLASS[tone], className)}
      {...props}
    >
      <Icon aria-hidden className="mt-0.5 size-[18px] shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <div className="font-extrabold">{title}</div>}
        {children && <div className={cn(title && "mt-1", "text-neutral-600")}>{children}</div>}
        {actions && <div className="mt-2 flex gap-2">{actions}</div>}
      </div>
    </div>
  );
}
