const STEPS = ["ساخت سازمان", "مدیر", "تأیید کد", "فضای کار", "هوش سازمان", "اسناد"];

export default function Stepper({ active }: { active: number }) {
  return (
    <ol className="stepper" style={{ display: "flex", gap: 6, padding: 0, margin: "0 0 22px", listStyle: "none", flexWrap: "wrap" }}>
      {STEPS.map((s, i) => {
        const done = i < active;
        const cur = i === active;
        return (
          <li
            key={s}
            style={{
              flex: 1,
              textAlign: "center",
              padding: "8px 6px",
              borderRadius: 10,
              fontSize: 12.5,
              fontWeight: 600,
              background: done ? "var(--ok-weak)" : cur ? "var(--brand-weak)" : "var(--surface)",
              color: done ? "var(--ok)" : cur ? "var(--brand)" : "var(--muted)",
              border: "1px solid var(--border)",
            }}
          >
            {s}
          </li>
        );
      })}
    </ol>
  );
}
