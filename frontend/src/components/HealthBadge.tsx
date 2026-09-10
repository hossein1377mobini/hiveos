import { useEffect, useState } from "react";

type HealthState =
  | { status: "checking" }
  | { status: "ok"; environment: string }
  | { status: "unreachable" };

// Liveness contract from T-S0-2: GET /api/health → {status, environment, version}.
// Going through the dev proxy, a green badge here proves the frontend→API wiring
// end to end. The version field stays out of the UI (technical detail, terminology §7).
async function fetchHealth(signal: AbortSignal): Promise<HealthState> {
  try {
    const response = await fetch("/api/health", { signal });
    if (!response.ok) {
      return { status: "unreachable" };
    }
    const body = (await response.json()) as { status?: string; environment?: string };
    if (body.status !== "ok") {
      return { status: "unreachable" };
    }
    return { status: "ok", environment: body.environment ?? "unknown" };
  } catch {
    return { status: "unreachable" };
  }
}

export function HealthBadge() {
  const [health, setHealth] = useState<HealthState>({ status: "checking" });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).then(setHealth);
    return () => controller.abort();
  }, []);

  if (health.status === "checking") {
    return (
      <span className="text-sm text-neutral-400" role="status">
        در حال بررسی سلامت سرویس…
      </span>
    );
  }
  if (health.status === "unreachable") {
    return (
      <span className="rounded-control bg-error-bg px-3 py-1 text-sm text-error" role="status">
        سرویس در دسترس نیست
      </span>
    );
  }
  return (
    <span className="rounded-control bg-success-bg px-3 py-1 text-sm text-success" role="status">
      متصل — محیط {health.environment}
    </span>
  );
}
