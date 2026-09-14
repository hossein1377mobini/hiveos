import * as React from "react"
import { RotateCcwIcon, TriangleAlertIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

/**
 * Top-level render guard. [A7]
 *
 * v0.1 had no error boundary anywhere, so a single throwing component (a null
 * dereference on an unexpected API shape was the realistic case) unmounted the
 * whole tree and left a blank white page with no message and no recovery.
 */
interface Props {
  children: React.ReactNode
  /** Shown instead of the generic copy when the boundary catches. */
  title?: string
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // The backend owns structured logging; the browser console is the only sink
    // available to the SPA, so keep the report complete here.
    console.error("[HiveOS] render error", error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="flex min-h-dvh items-center justify-center bg-secondary p-6">
        <div className="w-full max-w-md rounded-card border border-border bg-card p-6 text-center shadow-card">
          <span
            aria-hidden
            className="mx-auto mb-4 flex size-12 items-center justify-center rounded-control bg-error-bg text-error"
          >
            <TriangleAlertIcon className="size-6" />
          </span>
          <h1 className="text-title">{this.props.title ?? "خطای غیرمنتظره در نمایش صفحه"}</h1>
          <p className="mt-2 text-caption text-muted-foreground">
            این خطا در سامانه ثبت شد. می‌توانید صفحه را دوباره بارگذاری کنید؛ اگر تکرار شد،
            موضوع را به مدیر سامانه اطلاع دهید.
          </p>
          <p className="mono mt-3 truncate rounded-control bg-secondary px-3 py-2 text-micro text-muted-foreground" dir="ltr">
            {error.message || error.name}
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <Button
              onClick={() => {
                this.setState({ error: null })
              }}
              variant="outline"
            >
              تلاش مجدد
            </Button>
            <Button onClick={() => window.location.reload()}>
              <RotateCcwIcon className="size-4" />
              بارگذاری دوباره
            </Button>
          </div>
        </div>
      </div>
    )
  }
}
