import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// HiveOS Textarea — mockup §۶ (min-height 84, line-height 1.8).
const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full resize-y rounded-control border border-neutral-200 bg-neutral-0 px-[13px] py-[11px] text-sm text-neutral-900 transition-colors",
        "min-h-[84px] leading-[1.8]",
        "placeholder:text-neutral-400",
        "focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50",
        "disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-400",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export { Textarea };
