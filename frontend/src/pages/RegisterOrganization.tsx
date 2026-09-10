import { useState } from "react";
import { api } from "../api/client";

// 01-register-organization.html — US-001 merged path (US-001/006).
export default function RegisterOrganization({
  onCreated,
  onBack,
}: {
  onCreated: (organizationId: string) => void;
  onBack: () => void;
}) {
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [size, setSize] = useState("10_50");
  const [businessDescription, setBusinessDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ organization_id: string }>("POST", "/auth/register-organization", {
        name,
        industry,
        size,
        business_description: businessDescription || null,
      });
      onCreated(data.organization_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
      <h1 className="text-lg font-bold">ساخت سازمان</h1>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <label className="block">
          <span className="text-sm font-semibold">نام سازمان</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required minLength={3} className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2" />
        </label>
        <label className="block">
          <span className="text-sm font-semibold">حوزه فعالیت</span>
          <input value={industry} onChange={(e) => setIndustry(e.target.value)} required className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2" />
        </label>
        <label className="block">
          <span className="text-sm font-semibold">تعداد افراد</span>
          <select value={size} onChange={(e) => setSize(e.target.value)} className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2">
            <option value="lt_10">کمتر از ۱۰</option>
            <option value="10_50">۱۰ تا ۵۰</option>
            <option value="50_200">۵۰ تا ۲۰۰</option>
            <option value="200_500">۲۰۰ تا ۵۰۰</option>
            <option value="gt_500">بیش از ۵۰۰</option>
          </select>
        </label>
        <label className="block">
          <span className="text-sm font-semibold">توصیف کسب‌وکار (اختیاری)</span>
          <textarea value={businessDescription} onChange={(e) => setBusinessDescription(e.target.value)} rows={3} className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2" />
        </label>
        {error && <div className="rounded-control bg-error-bg p-3 text-sm text-error">{error}</div>}
        <div className="flex gap-2">
          <button type="submit" disabled={busy} className="flex-1 rounded-control bg-navy-600 py-2 font-bold text-white disabled:opacity-60">
            {busy ? "..." : "ادامه"}
          </button>
          <button type="button" onClick={onBack} className="rounded-control border border-neutral-200 px-4 py-2 text-sm">
            بازگشت
          </button>
        </div>
      </form>
    </section>
  );
}
