#!/usr/bin/env python3
import os
import sys

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# On Windows, output that isn't the native console (Git Bash's mintty, a
# pipe) defaults to cp1252, which can't encode the banner's box drawing
# characters - the app crashed on its first print. The native console is
# already UTF-8, so this only changes the cases that would otherwise crash.
for _stream in (sys.stdout, sys.stderr):
    if _stream and (_stream.encoding or "").lower().replace("-", "") != "utf8":
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

# Dependency check FIRST, using only the standard library. tokens_counter.main
# imports rich transitively, so importing it before this runs would turn a
# missing dependency into an ImportError traceback instead of an offer to
# install it. Everything else is imported after this returns.
from tokens_counter.dependencies import ensure_rich_or_exit

ensure_rich_or_exit()

from tokens_counter.main import main

if __name__ == "__main__":
    main()
