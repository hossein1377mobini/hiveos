import {
  AlertCircleIcon,
  CheckCircle2Icon,
  InfoIcon,
  ShieldAlertIcon,
  type LucideIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { cn } from "@/lib/utils"

/**
 * HiveOS Banner — the five message tones of design-system §2.3 rendered with the
 * official Alert (role, grid layout, icon sizing, title/description slots all
 * come from Alert). Only the tone colour map is local, because shadcn models
 * two variants and the product brief defines five.
 */
export type BannerTone = "info" | "success" | "warning" | "error" | "plain"

const TONE_ICON: Record<BannerTone, LucideIcon> = {
  info: InfoIcon,
  success: CheckCircle2Icon,
  warning: ShieldAlertIcon,
  error: AlertCircleIcon,
  plain: InfoIcon,
}

const TONE_CLASS: Record<BannerTone, string> = {
  info: "border-info-border bg-info-bg text-info",
  success: "border-success-border bg-success-bg text-success",
  warning: "border-warning-border bg-warning-bg text-warning",
  error: "border-error-border bg-error-bg text-error",
  plain: "border-border bg-secondary text-muted-foreground",
}

export function Banner({
  tone = "info",
  title,
  children,
  actions,
  className,
  icon,
  ...props
}: React.ComponentProps<typeof Alert> & {
  tone?: BannerTone
  title?: React.ReactNode
  actions?: React.ReactNode
  icon?: LucideIcon | null
}) {
  const Icon = icon === undefined ? TONE_ICON[tone] : icon
  return (
    <Alert
      data-slot="banner"
      data-tone={tone}
      role={tone === "error" ? "alert" : "status"}
      className={cn("gap-x-2.5 gap-y-1 rounded-card px-3 py-3 text-caption", TONE_CLASS[tone], className)}
      {...props}
    >
      {Icon ? <Icon /> : null}
      {title ? <AlertTitle className="font-bold">{title}</AlertTitle> : null}
      {actions ? (
        <AlertDescription className="col-start-2 flex gap-2 text-current">{actions}</AlertDescription>
      ) : null}
      {children ? (
        <AlertDescription className="col-start-2 gap-0 text-current opacity-90">
          {children}
        </AlertDescription>
      ) : null}
    </Alert>
  )
}