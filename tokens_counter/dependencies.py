"""
Startup dependency checks, so nothing has to be installed by hand.

Two kinds of dependency, and they are NOT interchangeable:

- pip packages (`rich`) install into whatever interpreter is running, with
  `sys.executable -m pip`. Safe, reversible, no privileges.
- tkinter is NOT a pip package. It ships with Python on Windows and macOS,
  but on Linux it's a separate OS package (python3-tk), which means a
  privileged system-wide install. `pip install tkinter` installs an
  unrelated dead package from PyPI - never suggest it.

This module only ever *describes* what's missing and how to fix it. It never
installs anything on its own: `install()` runs exactly the command that was
shown to the user, and main.py only calls it after an explicit yes. A system
package manager running under sudo is the most privileged thing this app can
trigger, so it stays opt-in and visible, the same way delete_session() does.
"""

import importlib.util
import os
import shutil
import subprocess
import sys

# Minimum Python this app is tested against. f-strings with `=`, walrus and
# dataclasses are all older than this; the real floor is that the tkinter
# and rich versions shipped for anything older are no longer packaged.
MIN_PYTHON = (3, 8)


def _module_available(module_name):
    """True if `module_name` can be imported without actually importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _linux_tk_command():
    """The right tkinter install command for whichever package manager exists."""
    managers = [
        ("apt-get", ["sudo", "apt-get", "install", "-y", "python3-tk"]),
        ("dnf", ["sudo", "dnf", "install", "-y", "python3-tkinter"]),
        ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "tk"]),
        ("zypper", ["sudo", "zypper", "install", "-y", "python3-tk"]),
        ("apk", ["sudo", "apk", "add", "python3-tkinter"]),
    ]
    for binary, command in managers:
        if shutil.which(binary):
            return command
    return None


def _tkinter_requirement():
    """
    How to get tkinter on this platform, or why we can't do it automatically.

    Returns (command, manual_hint). `command` is None when there's nothing
    safe to run - on Windows tkinter comes from the Python installer itself,
    so the only fix is re-running it with the tcl/tk component ticked.
    """
    if sys.platform == "win32":
        return None, (
            "tkinter ships with Python on Windows. Re-run the python.org installer, "
            "choose Modify, and tick 'tcl/tk and IDLE'."
        )
    if sys.platform == "darwin":
        if shutil.which("brew"):
            return ["brew", "install", "python-tk"], None
        return None, (
            "tkinter ships with the python.org build of Python on macOS. Either install "
            "Python from python.org, or install Homebrew and run: brew install python-tk"
        )
    command = _linux_tk_command()
    if command:
        return command, None
    return None, (
        "Install your distribution's Python tkinter package "
        "(commonly named python3-tk or python3-tkinter)."
    )


def check_python_version():
    """Returns an error string if this interpreter is too old, else None."""
    if sys.version_info < MIN_PYTHON:
        need = ".".join(str(p) for p in MIN_PYTHON)
        have = ".".join(str(p) for p in sys.version_info[:3])
        return f"Python {need}+ is required (this is {have})."
    return None


def check_dependencies():
    """
    Report every dependency's state without installing anything.

    Returns a list of dicts: `module`, `label`, `required` (the app cannot
    run without it), `installed`, `command` (argv to install it, or None),
    and `manual_hint` (what to tell the user when `command` is None).
    """
    tk_command, tk_hint = _tkinter_requirement()
    specs = [
        {
            "module": "rich",
            "label": "rich (terminal rendering)",
            "required": True,
            "command": [sys.executable, "-m", "pip", "install", "rich"],
            "manual_hint": None,
            "why": "Every view in the app is rendered with it.",
        },
        {
            "module": "tkinter",
            "label": "tkinter (floating always-on-top window)",
            "required": False,
            "command": tk_command,
            "manual_hint": tk_hint,
            "why": "Only needed for the floating monitor; the rest of the app works without it.",
        },
    ]
    for spec in specs:
        spec["installed"] = _module_available(spec["module"])
    return specs


def missing(required_only=False):
    """The dependencies that aren't installed, optionally only the required ones."""
    return [
        d for d in check_dependencies()
        if not d["installed"] and (d["required"] or not required_only)
    ]


def describe(dep):
    """One-line, copy-pasteable description of how to install `dep`."""
    if dep["command"]:
        return " ".join(dep["command"])
    return dep["manual_hint"] or "No automatic install available on this platform."


def install(dep):
    """
    Run the exact command `describe()` showed for `dep`.

    Returns (success, message). Never raises: a failed install has to leave
    the app usable enough to print why. Output is inherited rather than
    captured so a sudo password prompt (Linux) is actually visible and
    answerable - capturing it would hang on an invisible prompt.
    """
    if not dep["command"]:
        return False, dep["manual_hint"] or "No automatic install available on this platform."

    try:
        completed = subprocess.run(dep["command"], check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)

    if completed.returncode != 0:
        return False, f"'{' '.join(dep['command'])}' exited with code {completed.returncode}."

    # A freshly installed module won't be importable until the import caches
    # are told to look again - without this, an install that really did
    # succeed still reports the module as missing for the rest of the run.
    importlib.invalidate_caches()
    if not _module_available(dep["module"]):
        return False, (
            f"{dep['label']} still isn't importable after installing. "
            "Restarting the app usually picks it up."
        )
    return True, f"{dep['label']} installed."


def ensure_rich_or_exit():
    """
    Bootstrap check for the one hard dependency, run before rich is imported.

    This has to work with nothing but the standard library - by the time any
    module that does `from rich...` is imported, a missing rich is already an
    ImportError traceback. That's why start.py calls this first and why the
    prompts here use plain print/input instead of the app's own rendering.
    """
    error = check_python_version()
    if error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if _module_available("rich"):
        return

    dep = next(d for d in check_dependencies() if d["module"] == "rich")
    print("Missing required dependency: rich (the terminal rendering library).")
    print(f"  Install command: {describe(dep)}")
    if os.environ.get("TOKENS_COUNTER_AUTO_INSTALL") == "1":
        answer = "y"
    else:
        try:
            answer = input("Install it now? [Y/n] ").strip().lower() or "y"
        except (EOFError, KeyboardInterrupt):
            answer = "n"

    if answer not in ("y", "yes", "s", "si", "sí"):
        print("Cannot start without rich. Install it and run again.")
        sys.exit(1)

    ok, message = install(dep)
    print(message)
    if not ok:
        sys.exit(1)
