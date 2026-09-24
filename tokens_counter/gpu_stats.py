"""
GPU utilization %, for the floating window's system line. Standard library
only - psutil has no GPU support - with one source per platform:

- Windows: the "GPU Engine" performance counters, read through PDH with
  ctypes. It's what Task Manager uses, so it covers every vendor (the
  developer's machine is an Intel Iris Xe, where nvidia-smi doesn't exist).
  Task Manager's overall GPU % is the busiest single engine, where an
  engine's utilization is the sum over the per-process counter instances
  sharing its `luid_..._phys_N_eng_N`; this does the same, and matched
  PowerShell's Get-Counter within a point on real hardware.
- Linux: `nvidia-smi` when present (NVIDIA), else the kernel's
  `gpu_busy_percent` sysfs file (AMD). Intel iGPUs on Linux expose nothing
  comparable without root, so they read as unavailable.
- macOS: `ioreg`'s IOAccelerator "Device Utilization %" (Apple Silicon and
  Intel Macs).

Only the Windows path has been checked against real hardware; the Linux and
macOS paths are covered by tests on those tools' documented output. Every
path returns None rather than raising or guessing.
"""

import glob
import re
import subprocess
import sys
import threading
import time

_FIRST_SAMPLE_SECONDS = 0.2
_TOOL_TIMEOUT_SECONDS = 3


# --- Windows: PDH "GPU Engine" counters ------------------------------------

_ENGINE = re.compile(r"luid_(\w+?)_phys_(\d+)_eng_(\d+)_")
_pdh_state = {"query": None, "counter": None, "failed": False}
_pdh_lock = threading.Lock()


def busiest_engine_percent(samples):
    """
    Task Manager's GPU %: sum each engine's per-process instances, then take
    the busiest engine. `samples` is [(instance_name, value), ...].
    """
    engines = {}
    for name, value in samples:
        match = _ENGINE.search(name)
        if match:
            key = match.groups()
            engines[key] = engines.get(key, 0.0) + value
    if not engines:
        return None
    return max(0.0, min(100.0, max(engines.values())))


def _windows_samples():
    import ctypes
    from ctypes import wintypes

    PDH_FMT_DOUBLE = 0x00000200
    PDH_FMT_NOCAP100 = 0x00008000
    PDH_CSTATUS_OK = (0, 1)  # VALID_DATA, NEW_DATA

    class FmtValue(ctypes.Structure):
        _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

    class FmtItem(ctypes.Structure):
        _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", FmtValue)]

    pdh = ctypes.WinDLL("pdh")
    state = _pdh_state
    if state["query"] is None:
        query, counter = wintypes.HANDLE(), wintypes.HANDLE()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
            state["failed"] = True
            return None
        path = "\\GPU Engine(*)\\Utilization Percentage"
        if pdh.PdhAddEnglishCounterW(query, path, None, ctypes.byref(counter)) != 0:
            pdh.PdhCloseQuery(query)
            state["failed"] = True
            return None
        state.update(query=query, counter=counter)
        # A rate counter needs two collections before it has a value.
        pdh.PdhCollectQueryData(query)
        time.sleep(_FIRST_SAMPLE_SECONDS)

    if pdh.PdhCollectQueryData(state["query"]) != 0:
        return None
    flags = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
    size, count = wintypes.DWORD(0), wintypes.DWORD(0)
    pdh.PdhGetFormattedCounterArrayW(state["counter"], flags, ctypes.byref(size),
                                     ctypes.byref(count), None)
    if not size.value:
        return None
    buffer = (ctypes.c_byte * size.value)()
    if pdh.PdhGetFormattedCounterArrayW(state["counter"], flags, ctypes.byref(size),
                                        ctypes.byref(count), buffer) != 0:
        return None
    items = ctypes.cast(buffer, ctypes.POINTER(FmtItem))
    return [(items[i].szName, items[i].FmtValue.doubleValue)
            for i in range(count.value)
            if items[i].FmtValue.CStatus in PDH_CSTATUS_OK and items[i].szName]


def _windows_percent():
    with _pdh_lock:
        if _pdh_state["failed"]:
            return None
        samples = _windows_samples()
    return busiest_engine_percent(samples) if samples else None


# --- Linux / macOS -----------------------------------------------------------

def _run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=_TOOL_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_nvidia_smi(output):
    """`nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits`: one % per GPU."""
    values = [float(line) for line in (output or "").split() if re.fullmatch(r"\d+(\.\d+)?", line)]
    return max(values) if values else None


def parse_ioreg(output):
    """`ioreg -r -d 1 -c IOAccelerator`: "Device Utilization %"=NN per GPU."""
    values = [float(v) for v in re.findall(r'"Device Utilization %"\s*=\s*(\d+)', output or "")]
    return max(values) if values else None


def _linux_percent():
    output = _run(["nvidia-smi", "--query-gpu=utilization.gpu",
                   "--format=csv,noheader,nounits"])
    value = parse_nvidia_smi(output)
    if value is not None:
        return value
    values = []
    for path in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        try:
            with open(path) as f:
                values.append(float(f.read().strip()))
        except (OSError, ValueError):
            continue
    return max(values) if values else None


def get_gpu_percent():
    """Busiest GPU's utilization in %, or None where it can't be read."""
    try:
        if sys.platform == "win32":
            return _windows_percent()
        if sys.platform == "darwin":
            return parse_ioreg(_run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"]))
        return _linux_percent()
    except Exception:
        return None
