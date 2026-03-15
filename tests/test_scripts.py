# ------------------------------------------------------------------------------
# This test module validates shell-script syntax and healthcheck behaviour.
# ------------------------------------------------------------------------------

from pathlib import Path
import os
import stat
import subprocess
import tempfile
import unittest


# ------------------------------------------------------------------------------
# This function returns the repository root for script execution tests.
# ------------------------------------------------------------------------------
def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------
# These tests validate script syntax and healthcheck exit behaviour.
# ------------------------------------------------------------------------------
class TestScripts(unittest.TestCase):
# --------------------------------------------------------------------------
# This test confirms shell scripts pass POSIX syntax checks.
# --------------------------------------------------------------------------
    def test_scripts_have_valid_shell_syntax(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATHS = [
            REPO_ROOT / "check-traversal-workers.sh",
            REPO_ROOT / "scripts" / "entrypoint.sh",
            REPO_ROOT / "scripts" / "start.sh",
            REPO_ROOT / "scripts" / "healthcheck.sh",
        ]

        for SCRIPT_PATH in SCRIPT_PATHS:
            RESULT = subprocess.run(
                ["sh", "-n", str(SCRIPT_PATH)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(RESULT.returncode, 0, msg=f"{SCRIPT_PATH}: {RESULT.stderr}")

# --------------------------------------------------------------------------
# This test confirms healthcheck passes with a fresh heartbeat file.
# --------------------------------------------------------------------------
    def test_healthcheck_passes_with_recent_heartbeat(self) -> None:
        REPO_ROOT = get_repo_root()
        HEALTHCHECK_PATH = REPO_ROOT / "scripts" / "healthcheck.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            ROOT_DIR = Path(TMPDIR)
            HEARTBEAT_PATH = ROOT_DIR / "pyiclodoc-drive-heartbeat.txt"
            HEARTBEAT_PATH.write_text("ok\n", encoding="utf-8")

            BIN_DIR = ROOT_DIR / "bin"
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            PARALLEL_PATH = BIN_DIR / "parallel"
            PARALLEL_PATH.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            PARALLEL_PATH.chmod(PARALLEL_PATH.stat().st_mode | stat.S_IXUSR)

            ENV = os.environ.copy()
            ENV["PATH"] = f"{BIN_DIR}{os.pathsep}{ENV.get('PATH', '')}"
            ENV["HEARTBEAT_FILE"] = str(HEARTBEAT_PATH)
            ENV["HEALTHCHECK_MAX_AGE_SECONDS"] = "900"

            RESULT = subprocess.run(
                ["sh", str(HEALTHCHECK_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

            self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)

# --------------------------------------------------------------------------
# This test confirms healthcheck fails when heartbeat file is absent.
# --------------------------------------------------------------------------
    def test_healthcheck_fails_without_heartbeat_file(self) -> None:
        REPO_ROOT = get_repo_root()
        HEALTHCHECK_PATH = REPO_ROOT / "scripts" / "healthcheck.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            ROOT_DIR = Path(TMPDIR)
            HEARTBEAT_PATH = ROOT_DIR / "missing-pyiclodoc-drive-heartbeat.txt"

            BIN_DIR = ROOT_DIR / "bin"
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            PARALLEL_PATH = BIN_DIR / "parallel"
            PARALLEL_PATH.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            PARALLEL_PATH.chmod(PARALLEL_PATH.stat().st_mode | stat.S_IXUSR)

            ENV = os.environ.copy()
            ENV["PATH"] = f"{BIN_DIR}{os.pathsep}{ENV.get('PATH', '')}"
            ENV["HEARTBEAT_FILE"] = str(HEARTBEAT_PATH)
            ENV["HEALTHCHECK_MAX_AGE_SECONDS"] = "900"

            RESULT = subprocess.run(
                ["sh", str(HEALTHCHECK_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

            self.assertNotEqual(RESULT.returncode, 0)

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper bounds output to the supported
# maximum when CPU count exceeds the configured cap.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_caps_recommendation_at_eight(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        RESULT = subprocess.run(
            ["sh", str(SCRIPT_PATH), "12"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 12\nRecommended SYNC_TRAVERSAL_WORKERS=8\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper preserves valid in-range input.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_uses_in_range_override(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        RESULT = subprocess.run(
            ["sh", str(SCRIPT_PATH), "4"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 4\nRecommended SYNC_TRAVERSAL_WORKERS=4\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper rejects non-numeric overrides.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_rejects_invalid_override(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        RESULT = subprocess.run(
            ["sh", str(SCRIPT_PATH), "abc"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(RESULT.returncode, 0)
        self.assertEqual(RESULT.stderr, "CPU count must be a positive integer.\n")


if __name__ == "__main__":
    unittest.main()
