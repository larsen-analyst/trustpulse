"""
pipeline/run_pipeline.py
TrustPulse — Master pipeline runner

Calls all ingest scripts in sequence. Each script is self-contained
and saves its own output to data/processed/.

Usage:
    python pipeline/run_pipeline.py               # Run all scripts
    python pipeline/run_pipeline.py --skip cqc    # Skip one script
    python pipeline/run_pipeline.py --only ae rtt # Run specific scripts only

Scripts run in this order:
    1.  ae
    2.  sickness
    3.  rtt
    4.  workforce
    5.  beds
    6.  discharge
    7.  cancelled_ops
    8.  cqc
    9.  oversight
    10. outpatients  (skipped automatically if source folder is missing)

After all ingest scripts complete, validate.py is run automatically.
"""

import argparse
import importlib
import sys
import time
import traceback
from pathlib import Path

# Add project root to path so pipeline modules resolve correctly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Script registry — order matters
# ---------------------------------------------------------------------------

SCRIPTS = [
    ("ae",           "pipeline.ingest.ae"),
    ("sickness",     "pipeline.ingest.sickness"),
    ("rtt",          "pipeline.ingest.rtt"),
    ("workforce",    "pipeline.ingest.workforce"),
    ("beds",         "pipeline.ingest.beds"),
    ("discharge",    "pipeline.ingest.discharge"),
    ("cancelled_ops","pipeline.ingest.cancelled_ops"),
    ("cqc",          "pipeline.ingest.cqc"),
    ("oversight",    "pipeline.ingest.oversight"),
    ("outpatients",  "pipeline.ingest.outpatients"),
]

# Scripts that are allowed to be missing without failing the whole pipeline
OPTIONAL_SCRIPTS = {"outpatients"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_script(name, module_path):
    """Import and run a single ingest script. Returns (success, elapsed_seconds).

    Supports two patterns:
    - Scripts with a run() function (cqc.py, oversight.py)
    - Scripts without run() that execute at import time (older scripts)
    """
    import runpy

    # Convert module path to file path
    rel_path = module_path.replace(".", "/") + ".py"
    script_path = PROJECT_ROOT / rel_path

    start = time.time()
    try:
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        # Execute every script directly as __main__ via runpy
        # This avoids __init__.py cascade issues and works for all script patterns
        runpy.run_path(str(script_path), run_name="__main__")

        elapsed = time.time() - start
        return True, elapsed

    except FileNotFoundError as e:
        elapsed = time.time() - start
        if name in OPTIONAL_SCRIPTS:
            print(f"  [SKIPPED] {name}: source files not found (optional script)")
            print(f"  Detail: {e}")
            return None, elapsed
        else:
            print(f"  [FAILED] {name}: {e}")
            return False, elapsed
    except Exception:
        elapsed = time.time() - start
        print(f"  [FAILED] {name}")
        traceback.print_exc()
        return False, elapsed


def main():
    parser = argparse.ArgumentParser(description="TrustPulse pipeline runner")
    parser.add_argument(
        "--skip", nargs="+", metavar="SCRIPT",
        help="Script names to skip (e.g. --skip cqc rtt)"
    )
    parser.add_argument(
        "--only", nargs="+", metavar="SCRIPT",
        help="Run only these scripts (e.g. --only ae sickness)"
    )
    args = parser.parse_args()

    skip = set(args.skip or [])
    only = set(args.only or [])

    # Determine which scripts to run
    to_run = []
    for name, module_path in SCRIPTS:
        if only and name not in only:
            continue
        if name in skip:
            print(f"  [SKIPPED] {name}: excluded via --skip")
            continue
        to_run.append((name, module_path))

    if not to_run:
        print("No scripts selected to run.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # Run each script
    # ---------------------------------------------------------------------------
    print("=" * 60)
    print("TrustPulse Pipeline Runner")
    print(f"Scripts to run: {[n for n, _ in to_run]}")
    print("=" * 60)

    pipeline_start = time.time()
    results = {}

    for name, module_path in to_run:
        print(f"\n>>> Running: {name}")
        print("-" * 40)
        success, elapsed = run_script(name, module_path)
        results[name] = (success, elapsed)
        if success is True:
            print(f"  [OK] {name} completed in {elapsed:.1f}s")
        elif success is None:
            pass  # Already printed skipped message
        else:
            print(f"  [FAILED] {name} failed after {elapsed:.1f}s")

    # ---------------------------------------------------------------------------
    # Run validate.py if it exists and we are not in --only mode
    # ---------------------------------------------------------------------------
    if not only:
        validate_path = PROJECT_ROOT / "pipeline" / "validate.py"
        if validate_path.exists():
            print(f"\n>>> Running: validate")
            print("-" * 40)
            try:
                import pipeline.validate as validate_module
                importlib.reload(validate_module)
                validate_module.run()
                print("  [OK] validate completed")
            except Exception:
                print("  [FAILED] validate")
                traceback.print_exc()
        else:
            print("\n[INFO] validate.py not found — skipping validation step")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    total_elapsed = time.time() - pipeline_start
    print("\n" + "=" * 60)
    print("Pipeline Summary")
    print("=" * 60)

    passed  = [n for n, (s, _) in results.items() if s is True]
    failed  = [n for n, (s, _) in results.items() if s is False]
    skipped = [n for n, (s, _) in results.items() if s is None]

    for name, (success, elapsed) in results.items():
        status = "OK     " if success is True else ("SKIPPED" if success is None else "FAILED ")
        print(f"  {status}  {name:<20} {elapsed:.1f}s")

    print("-" * 60)
    print(f"  Passed:  {len(passed)}")
    print(f"  Skipped: {len(skipped)}")
    print(f"  Failed:  {len(failed)}")
    print(f"  Total time: {total_elapsed:.1f}s")
    print("=" * 60)

    if failed:
        print(f"\nFailed scripts: {failed}")
        sys.exit(1)
    else:
        print("\nPipeline completed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
