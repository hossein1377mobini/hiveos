/**
 * Who is signed in.
 *
 * v0.1 hard-coded «مدیر» / «مدیر سازمان» in the shell because
 * GET /auth/onboarding-status did not return names. [D10] The endpoint now sends
 * an `identity` block (H1, closed 2026-09-13) and the shell reads it through
 * `lib/identity-context.tsx`.
 *
 * Every field stays optional: an older backend, or a response shape that drifts,
 * must degrade to the role label rather than render an empty header or block the
 * app.
 */
/**
 * Field names are snake_case, matching the API and every other payload in the
 * app (`subscription.expires_at`, `knowledge_source.path`). They were camelCase
 * here while the backend sent snake_case, and because every field is optional
 * the mismatch typechecked cleanly and silently produced `undefined` — the
 * header kept showing «مدیر» with no error anywhere.
 */
export interface SessionIdentity {
  user_name?: string | null
  organization_name?: string | null
  plan_label?: string | null
  plan_expires_at?: string | null
}