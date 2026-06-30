#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan text files in the plugin for em-dash (U+2014) line by line."""

import os
import sys

EMDASH = "\u2014"
TEXT_EXTS = {".py", ".sql", ".md", ".txt", ".json", ".html", ".ini", ".cfg"}
ROOT = os.path.dirname(os.path.abspath(__file__))

def main():
    found = 0
    for dirpath, _dirnames, filenames in os.walk(ROOT):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in TEXT_EXTS:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for line_no, line in enumerate(f, 1):
                        if EMDASH in line:
                            print(f"{fp}:{line_no}:{line.rstrip()}")
                            found += 1
            except Exception as exc:
                print(f"ERR:{fp}:{exc}")
    print(f"TOTAL_EMDASH={found}")
    return 0 if found == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
