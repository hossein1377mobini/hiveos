// Username validation — shared by OwnerAccount (register) and Login (re-login).
// PO decision + US-002 Amendment 2: English letters + digits + `.` and `@` only,
// exactly 3..50 chars, unique system-wide (server confirms availability).
// `-` and `_` are NOT allowed. Frontier blocks Persian/Arabic input at the source.

export const USERNAME_PATTERN = /^[A-Za-z0-9.@]{3,50}$/;

/** Character whitelist actually typed (used to strip disallowed chars as you type). */
const TYPABLE = /[^A-Za-z0-9.@]/g;

/**
 * Keep only allowed chars while the user is typing (English letters, digits, `.`, `@`).
 * Non-ASCII (Persian/Arabic/Cyrillic/emoji) and `-`/`_` are removed immediately.
 */
export function sanitizeUsernameInput(value: string): string {
  return value.replace(TYPABLE, "");
}

/**
 * Validate a (possibly partial) username.
 * Returns an error message (Persian) or null when valid.
 */
export function usernameError(value: string): string | null {
  if (!value) return "نام کاربری الزامی است.";
  if (value.length < 3) return "نام کاربری باید حداقل ۳ کاراکتر باشد.";
  if (value.length > 50) return "نام کاربری حداکثر ۵۰ کاراکتر است.";
  if (!USERNAME_PATTERN.test(value))
    return "تنها حروف انگلیسی، ارقام و کاراکترهای «.» و «@» مجاز است.";
  return null;
}
