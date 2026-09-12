import { forwardRef, type LabelHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// HiveOS label — mockup §۶ (13px, bold, 6px margin). Plain element: no Radix
// primitive needed for a static label (shadcn equates it anyway).
const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        "block text-[13px] font-bold text-neutral-900 select-none",
        "peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Label.displayName = "Label";

export { Label };
