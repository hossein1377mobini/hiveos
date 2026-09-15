/*
 * /wallet is one address for the merged wallet + subscription page.
 *
 * PO request 2026-09: «صفحه اشتراک و کیف پول رو هم با هم ادغام کن». The two
 * screens answer one question - what can I still spend, and until when - so the
 * content now lives in a single component, WalletPage, under a single route.
 *
 * This file re-exports it rather than duplicating the route element, so the
 * merged page is the ONLY implementation: /wallet renders it through here and
 * /subscription (pages/Subscription.tsx) re-exports the same component, which
 * is why neither address can 404 while App.tsx is rewired. Once App.tsx points
 * both paths at WalletPage (and turns /subscription into a redirect), this file
 * is a one-line alias that can be deleted.
 */
export { default } from "./WalletPage";
