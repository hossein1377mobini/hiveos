import type { NavId } from "../components/AppShell";
import WalletPage from "./WalletPage";

/*
 * /subscription is the same page as /wallet.
 *
 * PO request 2026-09: «صفحه اشتراک و کیف پول رو هم با هم ادغام کن». The
 * subscription hero, the plan label and the «اشتراک و اعتبار» explainer are now
 * sections of WalletPage, and the path the old nav entry used must keep working
 * - a bookmark to /subscription that 404s is a worse answer than a merged page.
 *
 * Why a wrapper and not a bare re-export: <Subscription> was the only routable
 * page that took a prop. App.tsx still renders it as
 * <Subscription onNavigate={...} />, and a re-exported component that does not
 * accept that prop fails type-checking. The prop is deliberately ignored rather
 * than forwarded: its one use was the «خرید اعتبار مکمل» button that jumped to
 * the wallet, and the wallet charge form is now on this very page, so there is
 * nowhere left to jump to.
 *
 * Rendering the merged page here (rather than <Navigate to="/wallet">) means
 * /subscription resolves today, because a redirect needs the router and the
 * router lives in App.tsx, which this file does not own. Once App.tsx points
 * both paths at WalletPage and turns /subscription into a redirect, this whole
 * file - prop and all - can be deleted.
 */
export default function Subscription(_props: { onNavigate?: (id: NavId) => void }) {
  return <WalletPage />;
}
