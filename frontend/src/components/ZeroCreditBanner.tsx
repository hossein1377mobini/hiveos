import { Banner } from "./ui/banner";

/**
 * The "you are out of credit" notice.
 *
 * It lives in its own module because two surfaces need it: the wallet page and
 * the chat composer, where running out mid-conversation is the actual failure
 * the notice exists for. It previously sat in Wallet.tsx, so Chat.tsx imported
 * the whole wallet page — a route-level module — just to render one banner. [D9]
 */
export function ZeroCreditBanner({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <Banner tone="error" title="اعتبار شما به پایان رسیده است." data-testid="zero-credit-banner">
      برای ادامه گفتگو، حساب خود را شارژ کنید.
    </Banner>
  );
}
