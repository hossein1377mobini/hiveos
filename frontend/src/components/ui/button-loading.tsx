import { Spinner } from "@/components/ui/spinner"
import { Button } from "@/components/ui/button"

/**
 * Official Button + the HiveOS pending affordance. shadcn's Button deliberately
 * has no `loading` prop (compose Spinner + disabled instead), so this thin
 * wrapper keeps the call sites readable without forking button.tsx — the actual
 * button (variants, sizes, focus ring, RTL) is still the registry component.
 */
export function LoadingButton({
  loading = false,
  disabled,
  children,
  ...props
}: React.ComponentProps<typeof Button> & { loading?: boolean }) {
  return (
    <Button disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {loading ? <Spinner data-icon="inline-start" /> : null}
      {children}
    </Button>
  )
}
