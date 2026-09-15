import { cn } from "@/lib/utils"

/**
 * Body section of the official Dialog. shadcn models header/footer only, and
 * DialogContent already carries the horizontal padding, so this adds the
 * vertical rhythm the mockups use without touching dialog.tsx.
 */
export function DialogBody({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-body"
      className={cn("grid gap-4 overflow-y-auto px-6 py-1 text-body", className)}
      {...props}
    />
  )
}
