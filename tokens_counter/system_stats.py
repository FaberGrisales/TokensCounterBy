"""
CPU, RAM, GPU and disk activity for the floating window's top line.

CPU/RAM/disk use psutil, an OPTIONAL dependency (see dependencies.py): the
standard library has no cross-platform way to read them. GPU comes from
gpu_stats.py (standard library only), so it shows even without psutil.
When nothing at all can be read, get_system_stats() returns None and the
window simply omits the line.
"""

import time

# Previous (timestamp-free) samples for the rate readings below, kept here
# rather than inside psutil: psutil 7.2 stores cpu_percent()'s last sample
# per THREAD, and the floating window collects stats on a new worker thread
# every refresh - so every call looked like a first call and read 0.0.
_last_cpu = None      # (total_cpu_seconds, idle_cpu_seconds)
_last_disk = None     # (monotonic_seconds, bytes_read + bytes_written)
_FIRST_SAMPLE_SECONDS = 0.2


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def is_available():
    return _psutil() is not None


def _claude_process_rss(psutil):
    """
    Resident memory of every process named like Claude (Claude Desktop and
    its helpers, the Claude Code binary), in bytes. Matched on process name
    only - reading command lines needs extra privileges on some platforms.
    """
    total = 0
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (proc.info.get("name") or "").lower()
            mem = proc.info.get("memory_info")
        except (psutil.Error, AttributeError):
            continue
        if "claude" in name and mem is not None:
            total += mem.rss
    return total


def _cpu_sample(psutil):
    t = psutil.cpu_times()
    # Same accounting as psutil's own cpu_percent: busy = total - idle - iowait.
    idle = t.idle + getattr(t, "iowait", 0.0)
    return sum(t), idle


def _cpu_percent(psutil):
    global _last_cpu
    if _last_cpu is None:
        _last_cpu = _cpu_sample(psutil)
        time.sleep(_FIRST_SAMPLE_SECONDS)
    total, idle = _cpu_sample(psutil)
    prev_total, prev_idle = _last_cpu
    _last_cpu = (total, idle)
    elapsed = total - prev_total
    if elapsed <= 0:
        return None
    busy = elapsed - (idle - prev_idle)
    return max(0.0, min(100.0, busy / elapsed * 100))


def _disk_bytes_per_second(psutil):
    """
    Read + write throughput across all disks - activity, like Task Manager's
    Disk column, not how full a disk is. psutil exposes no cross-platform
    "active time" percentage (busy_time is Linux-only), so this is a rate.
    """
    global _last_disk
    io = psutil.disk_io_counters()
    if io is None:
        return None
    now = time.monotonic()
    moved = io.read_bytes + io.write_bytes
    if _last_disk is None:
        _last_disk = (now, moved)
        return None
    prev_time, prev_moved = _last_disk
    _last_disk = (now, moved)
    if now <= prev_time:
        return None
    return max(0.0, (moved - prev_moved) / (now - prev_time))


def _gpu_percent():
    from tokens_counter.gpu_stats import get_gpu_percent
    return get_gpu_percent()


def get_system_stats():
    """
    {"cpu_percent", "ram_used", "ram_total", "ram_percent", "gpu_percent",
    "disk_bytes_per_sec", "claude_rss"} (bytes for sizes), or None when
    nothing could be read.

    CPU and disk are rates since the previous call. The first CPU reading
    blocks for _FIRST_SAMPLE_SECONDS so it's never a fake 0%; the first disk
    reading is None (shown once the next refresh has a second sample).
    Never raises: any field it can't read is None.
    """
    stats = {"cpu_percent": None, "ram_used": None, "ram_total": None,
             "ram_percent": None, "gpu_percent": None, "disk_bytes_per_sec": None,
             "claude_rss": None}
    try:
        stats["gpu_percent"] = _gpu_percent()
    except Exception:
        pass

    psutil = _psutil()
    if psutil is None:
        return stats if stats["gpu_percent"] is not None else None
    try:
        stats["cpu_percent"] = _cpu_percent(psutil)
    except Exception:
        pass
    try:
        vm = psutil.virtual_memory()
        stats.update(ram_used=vm.total - vm.available, ram_total=vm.total,
                     ram_percent=vm.percent)
    except Exception:
        pass
    try:
        stats["disk_bytes_per_sec"] = _disk_bytes_per_second(psutil)
    except Exception:
        pass
    try:
        stats["claude_rss"] = _claude_process_rss(psutil)
    except Exception:
        pass
    return stats


def _rate(bytes_per_sec):
    if bytes_per_sec >= 1024 ** 2:
        return f"{bytes_per_sec / 1024 ** 2:.1f} MB/s"
    return f"{bytes_per_sec / 1024:.0f} KB/s"


def _gb(value):
    return f"{value / 1024 ** 3:.1f}"


def format_stats(stats):
    """
    Short labelled parts for the window, e.g.
    [("CPU", "23%", 23.0), ("RAM", "11.2/31.8 GB", 35.0), ...]:
    (label, text, percent-for-colouring or None). Fields that couldn't be
    read are left out rather than shown as 0.
    """
    if not stats:
        return []
    parts = []
    if stats.get("cpu_percent") is not None:
        parts.append(("CPU", f"{stats['cpu_percent']:.0f}%", stats["cpu_percent"]))
    if stats.get("ram_used") is not None and stats.get("ram_total"):
        parts.append(("RAM", f"{_gb(stats['ram_used'])}/{_gb(stats['ram_total'])} GB",
                      stats.get("ram_percent")))
    if stats.get("gpu_percent") is not None:
        parts.append(("GPU", f"{stats['gpu_percent']:.0f}%", stats["gpu_percent"]))
    if stats.get("disk_bytes_per_sec") is not None:
        parts.append(("Disk", _rate(stats["disk_bytes_per_sec"]), None))
    if stats.get("claude_rss"):
        parts.append(("Claude", f"{_gb(stats['claude_rss'])} GB", None))
    return parts
