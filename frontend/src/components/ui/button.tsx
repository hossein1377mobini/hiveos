import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// HiveOS Button — design-system §3 (Variant/Size/Loading/Disabled/Focus) with
// mockup assets/hiveos.css §۹ values (btn / btn-primary / btn-sm / btn-xs ...).
const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center gap-2 whitespace-nowrap font-bold transition-all disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-200 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-navy-600 text-white shadow-[0_3px_12px_rgba(43,58,115,0.28)] hover:-translate-y-px hover:bg-navy-800 hover:shadow-[0_6px_18px_rgba(43,58,115,0.34)]",
        secondary:
          "border border-neutral-200 bg-neutral-0 text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900",
        ghost: "text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900",
        destructive: "bg-error text-white hover:bg-[#9A1F14]",
        "danger-soft": "border border-error bg-error-bg text-error hover:bg-[#fbd9d7]",
        accent: "border border-navy-200 bg-navy-50 text-navy-600 hover:bg-[#e2e7f8]",
        link: "text-navy-600 underline-offset-4 hover:underline",
      },
      size: {
        default: "rounded-control px-5 py-3 text-sm",
        sm: "rounded-[9px] px-3.5 py-2 text-[12.5px]",
        xs: "rounded-[7px] px-2.5 py-[5px] text-[11.5px]",
        lg: "rounded-control px-[26px] py-[14px] text-[15px]",
        icon: "rounded-[9px] p-[9px]",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

const Spinner = () => (
  <span
    aria-hidden
    className="size-4 animate-spin rounded-full border-2 border-current/30 border-t-current"
  />
);

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? (
          <>
            <Spinner />
            {children}
          </>
        ) : (
          children
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
