"""Host resource monitoring for the admin panel (PO request 2026-09-13).

The panel has to answer "is this server healthy, and what is it doing" without
the PO opening an SSH session. Everything here reads the kernel's own files,
so there is no psutil dependency and nothing to install on the host.

The API runs in a container, where /proc shows the container's network and
disk namespace rather than the host's. HOST_PROC_DIR/HOST_SYS_DIR point at the
host's /proc and /sys, bind-mounted read-only by the compose file; when they
are absent (local dev, tests) the container's own /proc is used and the numbers
still answer, just scoped to the container.

CPU, network and disk-throughput are rates, so every reading keeps the previous
sample and reports the delta. First call after start reports zero rather than
the average since boot, which would be a meaningless number to display.
"""

import os
import shutil
import time
from pathlib import Path

# Sampling state: (monotonic timestamp, counter snapshot). Kept module-level so
# the delta survives between panel polls without touching the database.
_PREV: dict[str, tuple[float, dict]] = {}


def _proc_dir() -> Path:
    override = os.environ.get("HOST_PROC_DIR")
    root = Path(override) if override else Path("/proc")
    return root if root.is_dir() else Path("/proc")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _rate(key: str, counters: dict, now: float) -> dict:
    """Counter deltas since the previous sample, per second."""
    previous = _PREV.get(key)
    _PREV[key] = (now, counters)
    if previous is None:
        return {}
    elapsed = now - previous[0]
    if elapsed <= 0:
        return {}
    return {
        name: round((value - previous[1].get(name, value)) / elapsed, 2)
        for name, value in counters.items()
    }


def _counters() -> dict[str, int]:
    """Cumulative jiffies and byte counters the rates are computed from."""
    out: dict[str, int] = {}
    stat = _read(_proc_dir() / "stat")
    if stat:
        for line in stat.splitlines():
            if not line.startswith("cpu"):
                continue
            parts = line.split()
            # Fields: user nice system idle iowait irq softirq steal ...
            # idle + iowait are the only non-busy ones (index 4, 5).
            if len(parts) < 8:
                continue
            label = parts[0]
            try:
                # user nice system idle iowait irq softirq steal - idle and
                # iowait are the only non-busy fields, so they are subtracted
                # out; counting them as busy pins every reading at ~50%.
                total = sum(int(p) for p in parts[1:8])
                idle = int(parts[4]) + int(parts[5])
                busy = total - idle
            except ValueError:
                continue
            if label == "cpu":
                out["cpu_busy"] = busy
                out["cpu_idle"] = idle
            elif label[3:].isdigit():
                out[f"cpu{label[3:]}_busy"] = busy
                out[f"cpu{label[3:]}_idle"] = idle
    net = _read(_proc_dir() / "net/dev")
    if net:
        for line in net.splitlines():
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if name == "lo":
                continue
            fields = rest.split()
            if len(fields) >= 9:
                out[f"net_{name}_rx"] = int(fields[0])
                out[f"net_{name}_tx"] = int(fields[8])
    disk = _read(_proc_dir() / "diskstats")
    if disk:
        for line in disk.splitlines():
            fields = line.split()
            if len(fields) < 14:
                continue
            name = fields[2]
            if name.startswith(("loop", "ram", "dm-", "sr")):
                continue
            out[f"disk_{name}_read"] = int(fields[5]) * 512
            out[f"disk_{name}_write"] = int(fields[9]) * 512
    return out


def cpu_snapshot() -> dict:
    counters = _counters()
    now = time.monotonic()
    rates = _rate("counters", counters, now)
    cores = [k[: -len("_busy")] for k in counters if k.endswith("_busy")]
    # /proc is Linux-only; a Windows dev box still reports a usable core count.
    sample: dict = {"cores": len(cores) or (os.cpu_count() or 0), "per_core": [], "model": None}

    busy_delta = rates.get("cpu_busy")
    idle_delta = rates.get("cpu_idle")
    if busy_delta is not None and idle_delta is not None and (busy_delta + idle_delta) > 0:
        sample["percent"] = round(100.0 * busy_delta / (busy_delta + idle_delta), 1)
        sample["source"] = "instant"
    else:
        # First call after a restart has no previous sample to diff against.
        # Reporting null would paint the panel with a blank gauge on every
        # deploy, so fall back to the since-boot average and label it as such;
        # the next poll 15 seconds later replaces it with a live figure.
        busy = counters.get("cpu_busy")
        idle = counters.get("cpu_idle")
        if busy is not None and idle is not None and (busy + idle) > 0:
            sample["percent"] = round(100.0 * busy / (busy + idle), 1)
            sample["source"] = "since_boot"
        else:
            sample["percent"] = None
            sample["source"] = "unavailable"

    for index in range(len(cores)):
        b = rates.get(f"cpu{index}_busy")
        i = rates.get(f"cpu{index}_idle")
        if b is None or i is None or (b + i) <= 0:
            continue
        sample["per_core"].append(round(100.0 * b / (b + i), 1))

    info = _read(_proc_dir() / "cpuinfo")
    if info:
        for line in info.splitlines():
            if line.lower().startswith("model name"):
                sample["model"] = line.split(":", 1)[1].strip()
                break
    # getloadavg is POSIX-only, so a Windows dev box reports null instead of
    # the whole panel failing (the field is informational).
    getloadavg = getattr(os, "getloadavg", None)
    try:
        one, five, fifteen = getloadavg() if getloadavg else (None, None, None)
        sample["load"] = {
            "1m": round(one, 2) if one is not None else None,
            "5m": round(five, 2) if five is not None else None,
            "15m": round(fifteen, 2) if fifteen is not None else None,
        }
    except OSError:
        sample["load"] = {"1m": None, "5m": None, "15m": None}
    return sample


def memory_snapshot() -> dict:
    """Memory in bytes. 'available' is the kernel's own reclaimable estimate,
    which is the honest number to show - 'free' alone makes a healthy Linux box
    look full because of page cache."""
    meminfo = _read(_proc_dir() / "meminfo")
    values: dict[str, int] = {}
    if meminfo:
        for line in meminfo.splitlines():
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            parts = rest.split()
            if parts and parts[0].isdigit():
                values[name.strip()] = int(parts[0]) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    used = (total - available) if total is not None and available is not None else None
    swap_total = values.get("SwapTotal")
    swap_free = values.get("SwapFree")
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "percent": round(100.0 * used / total, 1) if used is not None and total else None,
        "cached_bytes": values.get("Cached"),
        "buffers_bytes": values.get("Buffers"),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": (swap_total - swap_free)
        if swap_total is not None and swap_free is not None
        else None,
    }


def disk_snapshot(paths: list[str] | None = None) -> dict:
    """Capacity per mount plus read/write throughput.

    statvfs on the container's own root reports the underlying filesystem, so
    the capacity figures are the host's even without extra mounts."""
    counters = _counters()
    now = time.monotonic()
    rates = _rate("disks", counters, now)

    mounts = []
    for path in paths or ["/"]:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        mounts.append(
            {
                "path": path,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent": round(100.0 * usage.used / usage.total, 1) if usage.total else None,
            }
        )

    devices: dict[str, dict] = {}
    for name, value in rates.items():
        if not name.startswith("disk_"):
            continue
        _, device, kind = name.split("_", 2)
        devices.setdefault(device, {})[kind] = value

    return {
        "mounts": mounts,
        "io": [{"device": d, **v} for d, v in sorted(devices.items())],
    }


def network_snapshot() -> dict:
    counters = _counters()
    now = time.monotonic()
    rates = _rate("network", counters, now)
    interfaces: dict[str, dict] = {}
    for name, value in rates.items():
        if not name.startswith("net_"):
            continue
        rest = name[len("net_") :]
        if not rest.endswith(("_rx", "_tx")):
            continue
        iface, kind = rest.rsplit("_", 1)
        interfaces.setdefault(iface, {})[kind] = value
    # Counters are absolute totals as well; the panel shows the rate.
    totals: dict[str, dict] = {}
    for name, value in counters.items():
        if not name.startswith("net_"):
            continue
        rest = name[len("net_") :]
        if not rest.endswith(("_rx", "_tx")):
            continue
        iface, kind = rest.rsplit("_", 1)
        totals.setdefault(iface, {})[kind + "_bytes"] = value
    merged = []
    for iface, speeds in sorted(interfaces.items()):
        merged.append({"name": iface, **speeds, **totals.get(iface, {})})
    return {"interfaces": merged}


def uptime_snapshot() -> dict:
    raw = _read(_proc_dir() / "uptime")
    seconds = None
    if raw:
        try:
            seconds = round(float(raw.split()[0]))
        except (IndexError, ValueError):
            seconds = None
    return {"uptime_seconds": seconds}


def _process_snapshot() -> list[dict]:
    """Top processes by resident memory.

    CPU per process needs jiffies deltas of its own, which is a second sampling
    ring; resident memory is the figure that actually explains an unhealthy
    box, so that is what is sampled per process."""
    proc = _proc_dir()
    rows: list[dict] = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return rows
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            statm = (entry / "statm").read_text().split()
            rss_pages = int(statm[1])
            cmdline = (entry / "cmdline").read_bytes().decode(errors="replace")
        except (OSError, IndexError, ValueError):
            continue
        name = cmdline.replace("\x00", " ").strip() or entry.name
        rows.append(
            {
                "pid": int(entry.name),
                "name": name[:120],
                "rss_bytes": rss_pages * os.sysconf("SC_PAGE_SIZE"),
            }
        )
    rows.sort(key=lambda r: r["rss_bytes"], reverse=True)
    return rows[:5]


def host_snapshot(disk_paths: list[str] | None = None) -> dict:
    return {
        "cpu": cpu_snapshot(),
        "memory": memory_snapshot(),
        "disk": disk_snapshot(disk_paths),
        "network": network_snapshot(),
        "uptime": uptime_snapshot(),
        "top_processes": _process_snapshot(),
    }


def reset() -> None:
    """Drop rate baselines; used by tests so deltas never leak between cases."""
    _PREV.clear()