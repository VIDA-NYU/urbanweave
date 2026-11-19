"""Execute the tutorial notebooks in place, so their saved outputs (tables, reports and SVG maps)
come from the current code.

    python tools/run_tutorials.py                # every notebook in tutorials/
    python tools/run_tutorials.py 03 05          # those whose names start with these prefixes
    python tools/run_tutorials.py --check        # execute without saving; fail on any error

Needs the ``tutorials`` extra (``pip install -e '.[raster,osm,tutorials]'``). Each notebook runs in
a fresh kernel with ``tutorials/`` as its working directory.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ROOT = Path(__file__).resolve().parents[1]
TUTORIALS = ROOT / "tutorials"


def run(path: Path, *, save: bool, timeout: int = 600) -> float:
    nb = nbformat.read(path, as_version=4)
    t0 = time.time()
    NotebookClient(nb, timeout=timeout, kernel_name="python3", resources={"metadata": {"path": str(TUTORIALS)}}).execute()
    if save:
        for cell in nb.cells:  # keep diffs small: no execution timing metadata
            cell.get("metadata", {}).pop("execution", None)
        nbformat.write(nb, path)
    return time.time() - t0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefixes", nargs="*")
    ap.add_argument("--check", action="store_true", help="execute without saving")
    args = ap.parse_args(argv)
    books = sorted(p for p in TUTORIALS.glob("[0-9]*.ipynb")
                   if not args.prefixes or any(p.name.startswith(x) for x in args.prefixes))
    if not books:
        print("No notebooks matched.", file=sys.stderr)
        return 1
    failed = 0
    for p in books:
        try:
            secs = run(p, save=not args.check)
        except CellExecutionError as err:  # the failing cell and the error, without the kernel's traceback
            import re

            plain = re.sub(r"\x1b\[[0-9;]*m", "", str(err)).splitlines()
            source = plain[2:plain.index("------------------", 2)] if "------------------" in plain[2:] else plain[:10]
            print(f"{p.name}: FAILED in\n  " + "\n  ".join(source[:8]) + f"\n{err.ename}: {err.evalue}", file=sys.stderr)
            failed += 1
            continue
        print(f"{p.name}: {secs:.1f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
