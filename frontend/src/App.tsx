import { AppShell } from "./components/AppShell";
import { HealthBadge } from "./components/HealthBadge";

// T-S0-5 placeholder page: design-system tokens + shell layout sanity check.
// First real section («گفتگو») lands with epic-09 in S3; onboarding starts in S1.
export default function App() {
  return (
    <AppShell>
      <section className="mx-auto max-w-xl rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
        <h1 className="text-lg font-bold">پایه فرانت‌اند آماده است</h1>
        <p className="mt-2 text-sm text-neutral-600">
          این صفحه placeholder است. وضعیت اتصال به API:
        </p>
        <div className="mt-4">
          <HealthBadge />
        </div>
      </section>
    </AppShell>
  );
}
