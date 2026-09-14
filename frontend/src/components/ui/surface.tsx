import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/**
 * HiveOS page surface — the official Card with the product's elevation token and
 * padding applied once, so page files never restate border/background/radius.
 * Add `CardHeader`/`CardTitle`/`CardFooter` from "@/components/ui/card" inside
 * when a surface needs a heading or an action row.
 */
export function Surface({ className, ...props }: React.ComponentProps<typeof Card>) {
  return (
    <Card
      data-slot="surface"
      className={cn("gap-0 rounded-card border border-border bg-card p-6 shadow-card", className)}
      {...props}
    />
  )
}

export function SurfaceBody({ className, ...props }: React.ComponentProps<typeof CardContent>) {
  return <CardContent className={cn("p-0", className)} {...props} />
}

export { CardHeader, CardTitle, CardDescription, CardFooter, CardContent }
