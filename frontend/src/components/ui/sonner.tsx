"use client";

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/**
 * HiveOS toast surface.
 *
 * Light mode only (PO decision), so the theme is pinned instead of read from a
 * provider — the previous version pulled next-themes for a value that was
 * always "system" and had no provider to supply it anyway. [B2/C15]
 *
 * Positioned bottom-inline-start so it clears the sidebar on the right and
 * never covers the composer in the chat column.
 */
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      dir="rtl"
      position="bottom-left"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius-control)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
};

export { Toaster };
