import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// HiveOS Input — mockup assets/hiveos.css §۶ (padding 11/13, focus ring accent).
const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "w-full rounded-control border border-neutral-200 bg-neutral-0 px-[13px] py-[11px] text-sm text-neutral-900 transition-colors",
        "placeholder:text-neutral-400",
        "focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50",
        "disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-400",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };
