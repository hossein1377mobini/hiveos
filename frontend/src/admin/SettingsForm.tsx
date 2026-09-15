import * as React from "react"
import { PlusIcon, RotateCcwIcon, Trash2Icon } from "lucide-react"

import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select"
import { Textarea } from "../components/ui/textarea"
import { cn } from "../lib/utils"
import type { SettingDefinition, SettingField } from "./settings-schema"

/**
 * Schema-driven settings form.
 *
 * Replaces the raw JSON textareas of v0.1. Every value the operator can produce
 * here is a value the backend's Pydantic model accepts, because the two are
 * written against the same field list (see settings-schema.ts). [D8/D13]
 */

export type SettingsValues = Record<string, unknown>

/** Turns a stored JSON object into form state, applying the declared defaults. */
export function toFormValues(
  definition: SettingDefinition,
  stored: SettingsValues,
): SettingsValues {
  const next: SettingsValues = {}
  for (const field of definition.fields) {
    const raw = stored[field.name]
    if (field.kind === "list") {
      next[field.name] = Array.isArray(raw) ? raw.join("\n") : ""
    } else if (field.kind === "numberMap") {
      next[field.name] =
        raw && typeof raw === "object" && !Array.isArray(raw)
          ? Object.entries(raw as Record<string, number>).map(([key, value]) => ({
              key,
              value: String(value),
            }))
          : []
    } else if (raw === null || raw === undefined) {
      // A select is pre-filled with the value the server would fall back to
      // rather than left on its placeholder: a dropdown cannot render "the
      // default is X" as a free-text value, and an empty dropdown reads as
      // "unset" when the runtime is in fact using something.
      next[field.name] =
        field.kind === "select" && field.effectiveDefault !== undefined
          ? String(field.effectiveDefault)
          : ""
    } else {
      next[field.name] = String(raw)
    }
  }
  return next
}

/**
 * Turns form state back into the JSON the API expects.
 * Returns the payload, or a list of Persian validation messages.
 */
export function toPayload(
  definition: SettingDefinition,
  values: SettingsValues,
): { payload: SettingsValues; errors: string[] } {
  const payload: SettingsValues = {}
  const errors: string[] = []

  for (const field of definition.fields) {
    const value = values[field.name]

    if (field.kind === "list") {
      payload[field.name] = String(value ?? "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
      continue
    }

    if (field.kind === "numberMap") {
      const rows = Array.isArray(value) ? (value as Array<{ key: string; value: string }>) : []
      const map: Record<string, number> = {}
      for (const row of rows) {
        const name = row.key.trim()
        if (!name) continue
        const amount = Number(row.value)
        if (!Number.isFinite(amount)) {
          errors.push("مدت پلن «" + name + "» باید عدد باشد.")
          continue
        }
        map[name] = amount
      }
      payload[field.name] = map
      continue
    }

    if (field.kind === "number") {
      const text = String(value ?? "").trim()
      if (text === "") {
        // An empty numeric field is only acceptable when the field is optional;
        // sending "" would fail the schema with an unreadable message.
        if (field.required) errors.push(field.label + " را وارد کنید.")
        else continue
      } else {
        const amount = Number(text)
        if (!Number.isFinite(amount)) {
          errors.push(field.label + " باید عدد باشد.")
          continue
        }
        if (field.min !== undefined && amount < field.min) {
          errors.push(field.label + " نباید کمتر از " + field.min + " باشد.")
          continue
        }
        if (field.max !== undefined && amount > field.max) {
          errors.push(field.label + " نباید بیشتر از " + field.max + " باشد.")
          continue
        }
        payload[field.name] = amount
      }
      continue
    }

    const text = String(value ?? "").trim()
    if (field.required && !text) {
      errors.push(field.label + " را وارد کنید.")
      continue
    }
    // Optional text fields are omitted rather than sent as "", so a cleared key
    // stays cleared instead of overwriting a value with an empty string.
    if (text || field.required) payload[field.name] = text
  }

  return { payload, errors }
}

/**
 * The "what is actually in force" note under a field the operator has not set.
 *
 * The PO opened the pipeline panel and read the blank "سقف حجم هر فایل" as "no
 * limit", while the server was rejecting every upload over 25 MB. The runtime
 * fills an absent key from its own default and never from the empty form, so
 * the panel has to say so: a blank control must not read as "nothing applies".
 *
 * An empty LIST is the one case where blank is the real answer — no allowlist
 * means every model, and no format list means the server does not filter — and
 * those fields carry no `effectiveDefault`, so no note is rendered.
 */
function FieldNote({ field, value }: { field: SettingField; value: unknown }) {
  if (field.effectiveDefault === undefined) return null
  if (String(value ?? "").trim() !== "") return null
  return (
    <p data-testid={"setting-default-" + field.name} className="text-micro text-muted-foreground">
      خالی است؛ در حال حاضر{" "}
      <span className="mono font-bold text-foreground">{String(field.effectiveDefault)}</span>{" "}
      اعمال می‌شود (مقدار پیش‌فرض).
    </p>
  )
}

function FieldControl({
  field,
  value,
  onChange,
  defaults,
  onRestoreDefault,
}: {
  field: SettingField
  value: unknown
  onChange: (next: unknown) => void
  /**
   * Server-supplied shipped values, keyed by field name. Fetched rather than
   * imported so the "suggested" text the panel restores is byte-identical to
   * the one the runtime falls back to - a copy in the frontend would drift and
   * the operator would be restoring a prompt the model never sees.
   */
  defaults: Record<string, string>
  onRestoreDefault?: (fieldName: string) => void
}) {
  const id = "setting-" + field.name

  if (field.kind === "select") {
    return (
      <Select value={String(value ?? "")} onValueChange={onChange}>
        <SelectTrigger id={id} className="h-9 w-full text-caption" aria-label={field.label}>
          <SelectValue placeholder="انتخاب کنید" />
        </SelectTrigger>
        <SelectContent>
          {(field.options ?? []).map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  if (field.kind === "multiline") {
    return (
      <div className="grid gap-2">
        <Textarea
          id={id}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
          rows={field.rows ?? 5}
          placeholder={field.placeholder}
          className={cn("text-caption leading-relaxed", field.ltr && "mono")}
          dir={field.ltr ? "ltr" : "rtl"}
        />
        {field.defaultFrom && onRestoreDefault && (
          <div className="flex items-center justify-between gap-2">
            <span className="text-micro text-muted-foreground">
              {String(value ?? "").trim() ? "متن سفارشی فعال است." : "متن پیشنهادی محصول فعال است."}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="rounded-control"
              disabled={!defaults[field.defaultFrom]}
              onClick={() => {
                const suggested = defaults[field.defaultFrom!]
                if (suggested) onChange(suggested)
              }}
            >
              <RotateCcwIcon aria-hidden className="size-3.5" />
              بازگرداندن متن پیشنهادی
            </Button>
          </div>
        )}
      </div>
    )
  }

  if (field.kind === "list") {
    return (
      <Textarea
        id={id}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        rows={4}
        placeholder={field.placeholder}
        className={cn("text-caption leading-relaxed", field.ltr && "mono")}
        dir={field.ltr ? "ltr" : "rtl"}
      />
    )
  }
  if (field.kind === "numberMap") {
    const rows = Array.isArray(value) ? (value as Array<{ key: string; value: string }>) : []
    return (
      <div className="grid gap-2">
        {/* Keyed by position on purpose: the operator can rename a plan while
            typing, and keying by the name would remount the row and steal focus
            on every keystroke. Rows are only ever added and removed at the end. */}
        {rows.map((row, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              value={row.key}
              aria-label={field.rowsLabel ? field.rowsLabel + " " + (index + 1) : field.label}
              placeholder="نام پلن"
              className="h-9 flex-1 text-caption"
              onChange={(event) => {
                const next = [...rows]
                next[index] = { ...row, key: event.target.value }
                onChange(next)
              }}
            />
            <Input
              value={row.value}
              aria-label={(field.rowsLabel ?? field.label) + " — مدت روز"}
              placeholder="روز"
              inputMode="numeric"
              className="h-9 w-24 text-caption"
              onChange={(event) => {
                const next = [...rows]
                next[index] = { ...row, value: event.target.value }
                onChange(next)
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={"حذف " + (row.key || String(index + 1))}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              <Trash2Icon className="size-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit rounded-control"
          onClick={() => onChange([...rows, { key: "", value: "" }])}
        >
          <PlusIcon className="size-3.5" />
          افزودن {field.rowsLabel ?? "ردیف"}
        </Button>
      </div>
    )
  }

  return (
    <Input
      id={id}
      type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
      value={String(value ?? "")}
      onChange={(event) => onChange(event.target.value)}
      placeholder={field.placeholder}
      min={field.min}
      max={field.max}
      inputMode={field.kind === "number" ? "numeric" : undefined}
      autoComplete={field.kind === "password" ? "new-password" : "off"}
      className={cn("h-9 text-caption", field.ltr && "mono")}
      dir={field.ltr ? "ltr" : "rtl"}
    />
  )
}

export function SettingsForm({
  definition,
  values,
  onChange,
  defaults = {},
}: {
  definition: SettingDefinition
  values: SettingsValues
  onChange: (next: SettingsValues) => void
  /** Shipped values from the settings GET, used by "restore suggested". */
  defaults?: Record<string, string>
}) {
  // Preserve the declared order while grouping: a settings page that jumps
  // around is harder to scan than one that follows the schema.
  const groups = React.useMemo(() => {
    const map = new Map<string, SettingField[]>()
    for (const field of definition.fields) {
      const group = field.group ?? ""
      const bucket = map.get(group)
      if (bucket) bucket.push(field)
      else map.set(group, [field])
    }
    return [...map.entries()]
  }, [definition])

  return (
    <div className="grid gap-5">
      {groups.map(([group, fields]) => (
        <fieldset key={group || "_"} className="grid gap-4">
          {group && (
            <legend className="text-micro font-bold text-muted-foreground">{group}</legend>
          )}
          {fields.map((field) => (
            <div key={field.name} className="grid gap-1.5">
              <Label htmlFor={"setting-" + field.name} className="text-caption font-bold">
                {field.label}
                {field.required && <span className="text-error"> *</span>}
              </Label>
              <FieldControl
                field={field}
                value={values[field.name]}
                onChange={(next) => onChange({ ...values, [field.name]: next })}
                defaults={defaults}
                onRestoreDefault={
                  field.defaultFrom
                    ? () => onChange({ ...values, [field.name]: defaults[field.defaultFrom!] ?? "" })
                    : undefined
                }
              />
              <FieldNote field={field} value={values[field.name]} />
              {field.hint && (
                <p className="text-micro leading-relaxed text-muted-foreground">{field.hint}</p>
              )}
            </div>
          ))}
        </fieldset>
      ))}
    </div>
  )
}
