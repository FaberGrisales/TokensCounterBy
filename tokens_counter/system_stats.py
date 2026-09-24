"""
CPU, RAM and disk usage for the floating window's top line.

Uses psutil, an OPTIONAL dependency (see dependencies.py): the standard
library has no cross-platform way to read CPU or memory usage (Windows needs
ctypes into kernel32, Linux /proc, macOS Mach calls). Without psutil,
get_system_stats() returns None and the window simply omits the line.
"""

import os

# psutil's cpu_percent(interval=None) measures since the previous call and
# returns a meaningless 0.0 on the very first one. The first call therefore
# measures over a short blocking interval instead - fine, since the window
# collects stats on a worker thread.
_FIRST_SAMPLE_SECONDS = 0.2
_primed = False


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


def get_system_stats():
    """
    {"cpu_percent", "ram_used", "ram_total", "ram_percent", "disk_percent",
    "claude_rss"} (bytes for sizes), or None when psutil isn't installed.

    `cpu_percent` is the usage since the previous call; the first call
    blocks for _FIRST_SAMPLE_SECONDS so it never reports a fake 0%.
    Never raises: any field it can't read is None.
    """
    psutil = _psutil()
    if psutil is None:
        return None

    stats = {"cpu_percent": None, "ram_used": None, "ram_total": None,
             "ram_percent": None, "disk_percent": None, "claude_rss": None}
    global _primed
    try:
        stats["cpu_percent"] = psutil.cpu_percent(
            interval=None if _primed else _FIRST_SAMPLE_SECONDS)
        _primed = True
    except Exception:
        pass
    try:
        vm = psutil.virtual_memory()
        stats.update(ram_used=vm.total - vm.available, ram_total=vm.total,
                     ram_percent=vm.percent)
    except Exception:
        pass
    try:
        stats["disk_percent"] = psutil.disk_usage(os.path.expanduser("~")).percent
    except Exception:
        pass
    try:
        stats["claude_rss"] = _claude_process_rss(psutil)
    except Exception:
        pass
    return stats


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
    if stats.get("disk_percent") is not None:
        parts.append(("Disk", f"{stats['disk_percent']:.0f}%", stats["disk_percent"]))
    if stats.get("claude_rss"):
        parts.append(("Claude", f"{_gb(stats['claude_rss'])} GB", None))
    return parts
