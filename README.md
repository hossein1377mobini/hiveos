# HiveOS

پلتفرم «کارمند دیجیتال» / سازمان-آمیز (Organizational Intelligence Platform) — v0.1 (**Hive Mind**).

اسکلت monorepo طبق **ADR-002** (Repository Structure). منبع رسمی مستندات: `docs/`.

## ساختار

```
hiveos/
├── docs/            # مستندات پروژه (ADR، PRD، Backlog، Architecture، Standards، API، Design)
├── frontend/        # رابط کاربری React (فقط UX/ارتباط با Backend — بدون منطق تجاری/AI)
├── backend/         # Backend .NET (Business Logic، Auth، Database، Integrations) — فاز ۲
├── ai/              # موتور هوش مصنوعی (Agentها، LLM، RAG، Services)
├── infrastructure/  # Docker/Compose، CI/CD، Deployment، Kubernetes
├── scripts/         # اسکریپتهای کمکی (Build، Migration، Utilities، Maintenance)
└── README.md
```

## موقعیت فعلی (وضعیت 2026-08-18)

- **استک v0.1 (ADR-019):** Python-first (AI Runtime + thin API) — گیتوی .NET فاز ۲؛ Vector Store = **pgvector**؛ Embedding = **fastembed محلی**؛ OTP = **Mock اول**؛ مجوز = **نقش Owner ساده**.
- بورد/تسکهای Epic-01 در Kaneo هماهنگ میشوند (منتظر جریان شروع طبق فلوی توسعه PO).

## قوانین ساختار (ADR-002)

1. هیچ فایل مستندی خارج از `docs/` قرار نگیرد.
2. هیچ کد AI داخل `backend/` قرار نگیرد.
3. هیچ Business Logic داخل `frontend/` قرار نگیرد.
4. هر بخش فقط مسئولیت خودش را دارد.
