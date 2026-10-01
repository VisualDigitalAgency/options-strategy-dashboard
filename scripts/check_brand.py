"""Fails if the app's name is hard-coded outside the few places allowed to hold the default.

The owner renames the app at runtime (issue #133), so code and lessons read it from engine/brand.py
(backend) or frontend/src/brand.jsx (frontend). Docs (*.md outside content/) may name it.
"""

import subprocess
import sys

NAME = "theta desk"
ALLOWED = {"engine/brand.py", "frontend/src/brand.jsx", "frontend/index.html", ".env.example",
           "scripts/check_brand.py"}

files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
bad = []
for path in files:
    if path in ALLOWED or (path.endswith(".md") and not path.startswith("content/")):
        continue
    try:
        text = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        continue
    bad += [f"{path}:{n}" for n, line in enumerate(text.splitlines(), 1) if NAME in line.lower()]
if bad:
    print("The app name is hard-coded here; use brand.name() / useBrand() instead:\n  " + "\n  ".join(bad))
    sys.exit(1)
print("OK: no hard-coded app name")
