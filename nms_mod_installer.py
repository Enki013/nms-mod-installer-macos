#!/usr/bin/env python3
"""
Backward-compatibility shim for git-cloned installs.

For PyPI users the entry point is `nms-mod-installer` which maps directly to
nms_mod_installer.installer:main via pyproject.toml.

Git users who run `python3 nms_mod_installer.py ...` are forwarded here.
"""
import sys
from pathlib import Path

# Make the src layout importable without pip install
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nms_mod_installer.installer import main  # noqa: E402

if __name__ == "__main__":
    main()
