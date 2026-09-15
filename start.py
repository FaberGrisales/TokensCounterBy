#!/usr/bin/env python3
import os
import sys

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Dependency check FIRST, using only the standard library. tokens_counter.main
# imports rich transitively, so importing it before this runs would turn a
# missing dependency into an ImportError traceback instead of an offer to
# install it. Everything else is imported after this returns.
from tokens_counter.dependencies import ensure_rich_or_exit

ensure_rich_or_exit()

from tokens_counter.main import main

if __name__ == "__main__":
    main()
