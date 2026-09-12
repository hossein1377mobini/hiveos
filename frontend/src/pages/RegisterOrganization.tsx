import { Building2, ChevronRight, ChevronLeft, Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { AuthBrand, Field, PanelHead, Stepper } from "../components/auth/parts";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { cn } from "../lib/utils";
import { Surface } from "../components/ui/surface";

// 01-register-organization.html — US-001 merged path (US-001/006). Three
// in-card panels (اطلاعات / توصیف / دسترسی هوش) behind the global stepper,
// exactly like the mockup. Business adaptation: the mockup's «نوع دسترسی»
// selection has no API field in v0.1 — rendered as the mockup's read-only
// choice (آنلاین checked, محلی disabled «به‌زودی»), nothing extra is sent.
const INDUSTRIES = [
  "فناوری اطلاعات",
  "مالی و بانکی",
  "تولید و صنعت",
  "بهداشت و درمان",
  "آموزش",
  "بازرگانی و خدمات",
  "سایر",
];

const SIZES = [
  { value: "lt_10", label: "کمتر از ۱۰ نفر" },
  { value: "10_50", label: "۱۰ تا ۵۰ نفر" },
  { value: "50_200", label: "۵۰ تا ۲۰۰ نفر" },
  { value: "200_500", label: "۲۰۰ تا ۵۰۰ نفر" },
  { value: "gt_500", label: "بیش از ۵۰۰ نفر" },
];

export default function RegisterOrganization({
  onCreated,
  onBack,
}: {
  onCreated: (organizationId: string) => void;
  onBack: () => void;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [size, setSize] = useState("10_50");
  const [businessDescription, setBusinessDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameInvalid = name.length > 0 && name.trim().length < 3;

  async function submit() {
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
    <section aria-label="ساخت سازمان">
      <AuthBrand title="ساخت سازمان" subtitle="سازمان جدید را در چند گام کوتاه تنظیم کنید." />
      <Stepper current={1} />

      <Surface className="p-7">
        {step === 0 && (
          <div>
            <PanelHead icon={Building2} title="اطلاعات سازمان" hint="گام ۱ از ۳" />
            <Field label="نام سازمان" required error={nameInvalid ? "نام سازمان باید حداقل ۳ کاراکتر باشد." : undefined}>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="مثلاً شرکت داده‌پرداز آریا"
                maxLength={100}
                className={cn(nameInvalid && "border-error focus:ring-error-bg")}
              />
              <div className="mt-[5px] text-xs text-neutral-400">بین ۳ تا ۱۰۰ کاراکتر.</div>
            </Field>
            <div className="flex gap-4">
              <Field label="صنعت" required className="min-w-0 flex-1">
                <select
                  value={industry}
                  onChange={(e) => setIndustry(e.target.value)}
                  aria-label="صنعت"
                  className="w-full cursor-pointer rounded-[10px] border border-neutral-200 bg-neutral-0 px-[13px] py-[11px] text-sm text-neutral-900 focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50"
                >
                  <option value="" disabled>
                    انتخاب کنید
                  </option>
                  {INDUSTRIES.map((i) => (
                    <option key={i} value={i}>
                      {i}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="اندازه سازمان" required className="min-w-0 flex-1">
                <select
                  value={size}
                  onChange={(e) => setSize(e.target.value)}
                  aria-label="اندازه سازمان"
                  className="w-full cursor-pointer rounded-[10px] border border-neutral-200 bg-neutral-0 px-[13px] py-[11px] text-sm text-neutral-900 focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50"
                >
                  {SIZES.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {error && (
              <div className="mb-4">
                <Banner tone="error">{error}</Banner>
              </div>
            )}
            <div className="mt-6 flex items-center gap-2.5">
              <LoadingButton className="flex-1" onClick={() => setStep(1)} disabled={name.trim().length < 3 || !industry}>
                ادامه
                <ChevronLeft aria-hidden className="rtl:-scale-x-100" />
              </LoadingButton>
            </div>
          </div>
        )}

        {step === 1 && (
          <div>
            <PanelHead icon={Sparkles} tone="teal" title="توصیف سازمان" hint="گام ۲ از ۳" />
            <Field
              label="کسب‌وکار شما چه می‌کند؟"
              hint="این توصیف به هوش سازمان کمک می‌کند پاسخ‌های دقیق‌تری به سؤال‌های شما بدهد."
            >
              <Textarea
                value={businessDescription}
                onChange={(e) => setBusinessDescription(e.target.value)}
                placeholder="توضیح دهید…"
              />
            </Field>
            {error && (
              <div className="mb-4">
                <Banner tone="error">{error}</Banner>
              </div>
            )}
            <div className="mt-6 flex items-center gap-2.5">
              <LoadingButton variant="ghost" onClick={() => setStep(0)}>
                <ChevronRight aria-hidden className="rtl:-scale-x-100" />
                قبلی
              </LoadingButton>
              <LoadingButton className="flex-1" onClick={() => setStep(2)} disabled={businessDescription.trim().length === 0}>
                ادامه
                <ChevronLeft aria-hidden className="rtl:-scale-x-100" />
              </LoadingButton>
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <PanelHead icon={Building2} tone="violet" title="دسترسی هوش سازمان" hint="گام ۳ از ۳" />
            <Field label="نوع دسترسی هوش" required>
              <div className="flex flex-wrap gap-3">
                <div className="relative min-w-[140px] flex-1 rounded-[13px] border border-navy-200 bg-navy-50 p-3.5 shadow-[0_0_0_1px_var(--focus-border)]">
                  <span
                    aria-hidden
                    className="absolute end-2.5 top-2.5 flex size-[17px] items-center justify-center rounded-full bg-navy-600 text-white"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="size-2.5">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </span>
                  <div className="text-sm font-bold text-neutral-900">آنلاین</div>
                  <div className="mt-0.5 text-xs text-neutral-600">
                    اتصال به هوش از طریق سرویس ابری؛ اتصال و کلیدها سمت HiveOS مدیریت می‌شود.
                  </div>
                </div>
                <div className="relative min-w-[140px] flex-1 rounded-[13px] border border-neutral-200 bg-neutral-0 p-3.5 opacity-55">
                  <span className="absolute end-2 top-2 rounded-full border border-warning bg-warning-bg px-2 py-px text-[10px] font-bold text-warning">
                    به‌زودی (نسخه ۰.۳)
                  </span>
                  <div className="text-sm font-bold text-neutral-900">محلی</div>
                  <div className="mt-0.5 text-xs text-neutral-600">اجرای هوش روی سرور خودتان</div>
                </div>
              </div>
            </Field>
            {error && (
              <div className="mb-4">
                <Banner tone="error">{error}</Banner>
              </div>
            )}
            <div className="mt-6 flex items-center gap-2.5">
              <LoadingButton variant="ghost" onClick={() => setStep(1)}>
                <ChevronRight aria-hidden className="rtl:-scale-x-100" />
                قبلی
              </LoadingButton>
              <LoadingButton className="flex-1" onClick={submit} loading={busy}>
                ساخت سازمان
              </LoadingButton>
            </div>
            <button
              type="button"
              onClick={onBack}
              className="mt-3 w-full cursor-pointer text-center text-xs text-neutral-600 underline-offset-4 hover:underline"
            >
              بازگشت به ورود
            </button>
          </div>
        )}
      </Surface>
    </section>
  );
}
