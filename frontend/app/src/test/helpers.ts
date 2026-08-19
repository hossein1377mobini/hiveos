import { fireEvent, screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

// Shared fixtures + form-filling helpers used across the page tests and the
// wizard integration test. Kept here so a contract change (label text, option
// value, placeholder) is fixed in one place.

export const ORG_NAME = "شرکت داده‌پرداز آریا";
export const WHAT = "تحلیل داده و هوش مصنوعی برای سازمان‌ها";
export const PRODUCTS = "پلتفرم تحلیل و اتوماسیون سازمانی";
export const API_KEY = "sk-test-key-123";
export const PHONE = "+989123456789";
export const STRONG_PW = "Abcdef1!";

export async function fillValidOrg(user: UserEvent) {
  await user.type(screen.getByPlaceholderText(/شرکت/), ORG_NAME);
  await user.selectOptions(screen.getAllByRole("combobox")[0], "فناوری اطلاعات");
  await user.selectOptions(screen.getAllByRole("combobox")[1], "10_50");
  const [what, products] = screen.getAllByPlaceholderText(/توضیح دهید/);
  await user.type(what, WHAT);
  await user.type(products, PRODUCTS);
  await user.type(screen.getByPlaceholderText(/^sk/), API_KEY);
}

// Phone is set via fireEvent.change (full-value replace) because the input's
// display value is reformatted on every keystroke, which makes typed input
// flaky. Password/confirm are plain inputs and use user-event.
export async function fillValidOwner(
  user: UserEvent,
  opts: { phone?: string; password?: string; confirm?: string } = {},
) {
  fireEvent.change(screen.getByLabelText(/شماره موبایل/), {
    target: { value: opts.phone ?? PHONE },
  });
  await user.type(screen.getByLabelText(/^رمز عبور/), opts.password ?? STRONG_PW);
  await user.type(screen.getByLabelText(/تکرار رمز عبور/), opts.confirm ?? STRONG_PW);
}

export function fillOtp(code: string) {
  const boxes = screen.getAllByRole("textbox") as HTMLInputElement[];
  code.split("").forEach((ch, i) => fireEvent.change(boxes[i], { target: { value: ch } }));
  return boxes;
}
