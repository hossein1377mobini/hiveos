import { useState } from "react";
import { api, describeError } from "../api";
import type { OrganizationCreate, Organization } from "../api";
import Stepper from "../Stepper";

const PROVIDERS = ["OpenAI", "Anthropic", "DeepSeek", "Google", "LiteLLM"];
const INDUSTRIES = ["فناوری اطلاعات", "مشاوره مدیریت", "خدمات مالی", "آموزش و دانشگاه", "تولید و صنعت", "بهداشت و درمان", "سایر"];
const SIZES = [
  { v: "lt_10", l: "کمتر از ۱۰ نفر" },
  { v: "10_to_49", l: "۱۰ تا ۴۹ نفر" },
  { v: "50_to_199", l: "۵۰ تا ۱۹۹ نفر" },
  { v: "200_to_499", l: "۲۰۰ تا ۴۹۹ نفر" },
  { v: "ge_500", l: "بیش از ۵۰۰ نفر" },
];

export default function RegisterOrganization({ onDone }: { onDone: (org: Organization) => void }) {
  const [form, setForm] = useState<OrganizationCreate>({
    displayName: "",
    industry: "",
    companySize: "",
    businessDescription: { whatYouDo: "", productsServices: "" },
    aiModel: { provider: "DeepSeek", apiKey: "" },
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (patch: Partial<OrganizationCreate>) => setForm((f) => ({ ...f, ...patch }));

  async function submit() {
    setError("");
    if (!form.displayName.trim() || form.displayName.trim().length < 3) return setError("نام سازمان باید حداقل ۳ نویسه باشد.");
    if (!form.industry) return setError("صنعت را انتخاب کنید.");
    if (!form.companySize) return setError("اندازه سازمان را انتخاب کنید.");
    if (form.businessDescription.whatYouDo.trim().length < 10 || form.businessDescription.productsServices.trim().length < 10)
      return setError("توصیف سازمان باید حداقل ۱۰ نویسه باشد.");
    if (!form.aiModel.apiKey.trim()) return setError("کلید هوش مصنوعی را وارد کنید.");
    setBusy(true);
    try {
      const org = await api.createOrganization(form);
      onDone(org);
    } catch (e) {
      setError(describeError(e, "خطا در ساخت سازمان"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <Stepper active={0} />
      <div className="card">
        <h2 style={{ marginTop: 0 }}>اطلاعات سازمان</h2>
        <div className="field">
          <label>نام سازمان</label>
          <input
            value={form.displayName}
            onChange={(e) => set({ displayName: e.target.value })}
            placeholder="مثلاً شرکت داده‌پرداز آریا"
          />
        </div>
        <div className="field">
          <label>صنعت</label>
          <select value={form.industry} onChange={(e) => set({ industry: e.target.value })}>
            <option value="">انتخاب کنید</option>
            {INDUSTRIES.map((i) => (
              <option key={i} value={i}>{i}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>اندازه سازمان</label>
          <select value={form.companySize} onChange={(e) => set({ companySize: e.target.value })}>
            <option value="">انتخاب کنید</option>
            {SIZES.map((s) => (
              <option key={s.v} value={s.v}>{s.l}</option>
            ))}
          </select>
        </div>

        <h2>توصیف سازمان</h2>
        <div className="field">
          <label>سازمان دقیقاً چه می‌کند؟</label>
          <textarea rows={2} value={form.businessDescription.whatYouDo} onChange={(e) => set({ businessDescription: { ...form.businessDescription, whatYouDo: e.target.value } })} placeholder="توضیح دهید…" />
        </div>
        <div className="field">
          <label>مهم‌ترین محصولات / خدمات</label>
          <textarea rows={2} value={form.businessDescription.productsServices} onChange={(e) => set({ businessDescription: { ...form.businessDescription, productsServices: e.target.value } })} placeholder="توضیح دهید…" />
        </div>

        <h2>اتصال هوش سازمان</h2>
        <div className="field">
          <label>ارائه‌دهنده هوش مصنوعی</label>
          <div className="provider-grid">
            {PROVIDERS.map((p) => (
              <div key={p} className={`provider ${form.aiModel.provider === p ? "selected" : ""}`} onClick={() => set({ aiModel: { ...form.aiModel, provider: p } })}>
                {p}
              </div>
            ))}
            <div className="provider coming">سایر <small>(به‌زودی)</small></div>
          </div>
        </div>
        <div className="field">
          <label>کلید API</label>
          <input type="password" value={form.aiModel.apiKey} onChange={(e) => set({ aiModel: { ...form.aiModel, apiKey: e.target.value } })} placeholder="sk-…" />
          <span className="hint">کلید به‌صورت رمزنگاری‌شده ذخیره می‌شود و هرگز نمایش داده نمی‌شود.</span>
        </div>

        {error && <div className="alerts"><div className="alert error">{error}</div></div>}

        <button className="btn-primary" onClick={submit} disabled={busy} style={{ width: "100%" }}>
          {busy ? "در حال ساخت…" : "ساخت سازمان"}
        </button>
      </div>
    </div>
  );
}
