#!/usr/bin/env python3
import os
import sys

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tokens_counter.main import main

if __name__ == "__main__":
    main()
