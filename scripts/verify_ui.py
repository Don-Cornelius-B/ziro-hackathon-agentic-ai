"""
Pre-Push UI & Official Test Verification Script.
Executes both tests/test_official_suite.py and tests/test_ui_interactions.py.
Outputs required confirmation banner if and only if all tests pass.
"""

import subprocess
import sys


def main():
    # Ensure Windows console supports UTF-8 characters (emojis)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_official_suite.py",
        "tests/test_ui_interactions.py",
        "-v",
        "--tb=short",
    ]

    print("=" * 70)
    print("🚀 RUNNING FULL END-TO-END VERIFICATION SUITE...")
    print("=" * 70)
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n" + "=" * 70)
        print("✅ ALL UI BUTTONS, SYNC CONTROLS, AND LOGIC VERIFIED. SAFE TO COMMIT AND PUSH.")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print(f"❌ TEST SUITE FAILED with exit code {result.returncode}")
        print("=" * 70)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
