import * as React from "react"
import { AlertTriangleIcon, ShieldAlertIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/**
 * The product's single destructive-action gate. [D5/D6]
 *
 * v0.1 used window.confirm and window.prompt for irreversible money- and
 * account-level operations (granting credit, deleting an organization, removing
 * a user). Those cannot be styled, cannot carry a reason, cannot be tested, and
 * read as an unfinished product to an administrator.
 *
 * Three escalating levels, chosen by how hard the action is to undo:
 *   - standard : reversible-ish. One click to confirm.
 *   - critical : touches money or access. Requires a written reason.
 *   - paranoid : destroys an account or its data. Requires typing a phrase.
 */
export type ConfirmLevel = "standard" | "critical" | "paranoid"

export interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  /** What is about to happen, in plain language. */
  description: React.ReactNode
  /** Concrete consequences, rendered as a bulleted list. */
  consequences?: string[]
  level?: ConfirmLevel
  confirmLabel?: string
  cancelLabel?: string
  /** Phrase the operator must type at the paranoid level. */
  confirmPhrase?: string
  /** When true, a non-empty reason is required before confirming. */
  requireReason?: boolean
  reasonLabel?: string
  reasonPlaceholder?: string
  busy?: boolean
  onConfirm: (input: { reason: string }) => void | Promise<void>
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  consequences,
  level = "standard",
  confirmLabel = "تأیید",
  cancelLabel = "انصراف",
  confirmPhrase,
  requireReason,
  reasonLabel = "دلیل این عملیات",
  reasonPlaceholder = "برای ثبت در رویدادهای سامانه، دلیل را بنویسید…",
  busy = false,
  onConfirm,
}: ConfirmDialogProps) {
  const [reason, setReason] = React.useState("")
  const [typed, setTyped] = React.useState("")

  // Reason is mandatory above the standard level even when the caller does not
  // ask for it: an audit row without a "why" is not an audit row.
  const needsReason = requireReason ?? level !== "standard"
  const needsPhrase = level === "paranoid" && Boolean(confirmPhrase)
  const phraseOk = !needsPhrase || typed.trim() === confirmPhrase
  const reasonOk = !needsReason || reason.trim().length >= 3
  const canConfirm = phraseOk && reasonOk && !busy

  React.useEffect(() => {
    if (!open) {
      setReason("")
      setTyped("")
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-5" data-testid="confirm-dialog">
        <DialogHeader className="gap-3 text-start">
          <span
            aria-hidden
            className={cn(
              "flex size-10 items-center justify-center rounded-control",
              level === "standard" ? "bg-warning-bg text-warning" : "bg-error-bg text-error",
            )}
          >
            {level === "standard" ? (
              <AlertTriangleIcon className="size-5" />
            ) : (
              <ShieldAlertIcon className="size-5" />
            )}
          </span>
          <DialogTitle className="text-title">{title}</DialogTitle>
          <DialogDescription className="text-caption leading-relaxed">{description}</DialogDescription>
        </DialogHeader>

        {consequences && consequences.length > 0 && (
          <ul className="grid gap-1.5 rounded-control border border-border bg-secondary p-3 text-caption">
            {consequences.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        )}

        {needsReason && (
          <div className="grid gap-2">
            <Label htmlFor="confirm-reason" className="text-micro text-muted-foreground">
              {reasonLabel}
            </Label>
            <Textarea
              id="confirm-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={reasonPlaceholder}
              rows={2}
              className="text-caption"
              data-testid="confirm-reason"
            />
          </div>
        )}

        {needsPhrase && (
          <div className="grid gap-2">
            <Label htmlFor="confirm-phrase" className="text-micro text-muted-foreground">
              برای تأیید، عبارت
              <span className="mono mx-1 font-bold text-error">{confirmPhrase}</span>
              را تایپ کنید
            </Label>
            <Input
              id="confirm-phrase"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              className="mono h-9 text-caption"
              autoComplete="off"
              data-testid="confirm-phrase"
            />
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            variant={level === "standard" ? "default" : "destructive"}
            onClick={() => void onConfirm({ reason: reason.trim() })}
            disabled={!canConfirm}
            data-testid="confirm-submit"
          >
            {busy ? "در حال انجام…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
