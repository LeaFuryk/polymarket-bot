"""Combined quality check runner: Python tests + Next.js type check + frontend tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(label: str, cmd: list[str], cwd: Path | None = None) -> bool:
    """Run a command and return True if it succeeds."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}\n")
    result = subprocess.run(cmd, cwd=cwd)
    passed = result.returncode == 0
    status = "PASS" if passed else "FAIL"
    print(f"\n  [{status}] {label}\n")
    return passed


def main() -> None:
    """Run all quality checks."""
    root = Path(__file__).resolve().parents[3]  # project root
    dashboard_dir = root / "dashboard-next"

    results: list[tuple[str, bool]] = []

    # 1. Python tests
    results.append(
        (
            "Python tests (pytest)",
            _run("Python tests", [sys.executable, "-m", "pytest", "tests/", "-v"], cwd=root),
        )
    )

    # 2. Next.js TypeScript check
    if dashboard_dir.exists():
        results.append(
            (
                "TypeScript type check",
                _run("TypeScript type check", ["npx", "tsc", "--noEmit"], cwd=dashboard_dir),
            )
        )

        # 3. Next.js tests
        results.append(
            (
                "Frontend tests (Jest)",
                _run("Frontend tests", ["npm", "test", "--", "--watchAll=false"], cwd=dashboard_dir),
            )
        )
    else:
        print(f"\n  [SKIP] dashboard-next/ not found at {dashboard_dir}\n")

    # Summary
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    all_passed = True
    for label, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}")
        if not passed:
            all_passed = False
    print()

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
