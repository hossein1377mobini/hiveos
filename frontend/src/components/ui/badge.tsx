import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// HiveOS Badge — mockup §۱۰ (badge.* with semantic tones + optional status dot).
const badgeVariants = cva(
  "inline-flex items-center gap-[5px] whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] font-bold [&_svg]:size-3",
  {
    variants: {
      variant: {
        neutral: "border border-neutral-200 bg-neutral-50 text-neutral-600",
        success: "bg-success-bg text-success",
        warning: "bg-warning-bg text-warning",
        error: "bg-error-bg text-error",
        info: "bg-navy-50 text-navy-600",
        teal: "bg-teal-soft text-teal",
        amber: "bg-amber-soft text-amber",
        violet: "bg-violet-soft text-violet",
        outlined: "border border-neutral-200 bg-transparent text-neutral-600",
      },
      size: {
        default: "",
        lg: "px-3.5 py-[5px] text-xs",
      },
    },
    defaultVariants: { variant: "neutral", size: "default" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

function Badge({ className, variant, size, dot = false, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, size }), className)} {...props}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export { Badge, badgeVariants };
