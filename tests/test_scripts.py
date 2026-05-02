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
# This test confirms `.dockerignore` excludes local-only files with explicit
# project rules instead of relying on a broad markdown wildcard.
# --------------------------------------------------------------------------
    def test_dockerignore_matches_project_build_contract(self) -> None:
        REPO_ROOT = get_repo_root()
        DOCKERIGNORE_TEXT = (REPO_ROOT / ".dockerignore").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("*.md", DOCKERIGNORE_TEXT)
        self.assertIn(".github/", DOCKERIGNORE_TEXT)
        self.assertIn("PROMPT.md", DOCKERIGNORE_TEXT)
        self.assertIn("README.md", DOCKERIGNORE_TEXT)
        self.assertIn("scripts/check_docs.py", DOCKERIGNORE_TEXT)
        self.assertIn("tests/", DOCKERIGNORE_TEXT)
        self.assertNotIn("scripts/entrypoint.sh", DOCKERIGNORE_TEXT)
        self.assertNotIn("scripts/start.sh", DOCKERIGNORE_TEXT)
        self.assertNotIn("scripts/healthcheck.sh", DOCKERIGNORE_TEXT)

# --------------------------------------------------------------------------
# This test confirms the Dockerfile copies only the runtime shell scripts
# needed by the image instead of the whole local scripts directory.
# --------------------------------------------------------------------------
    def test_dockerfile_copies_only_runtime_shell_scripts(self) -> None:
        REPO_ROOT = get_repo_root()
        DOCKERFILE_TEXT = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn(
            "COPY scripts/entrypoint.sh scripts/start.sh scripts/healthcheck.sh /app/scripts/",
            DOCKERFILE_TEXT,
        )
        self.assertNotIn("COPY scripts /app/scripts", DOCKERFILE_TEXT)

# --------------------------------------------------------------------------
# This test confirms the Dockerfile marks each runtime shell script as
# executable, including the healthcheck used by Docker health probing.
# --------------------------------------------------------------------------
    def test_dockerfile_marks_runtime_scripts_executable(self) -> None:
        REPO_ROOT = get_repo_root()
        DOCKERFILE_TEXT = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("/app/scripts/entrypoint.sh", DOCKERFILE_TEXT)
        self.assertIn("/app/scripts/start.sh", DOCKERFILE_TEXT)
        self.assertIn("/app/scripts/healthcheck.sh", DOCKERFILE_TEXT)
        self.assertNotIn("/bin/parallel", DOCKERFILE_TEXT)

# --------------------------------------------------------------------------
# This test confirms the Dockerfile no longer uses the microcheck stage now
# that healthcheck no longer depends on the copied `parallel` binary.
# --------------------------------------------------------------------------
    def test_dockerfile_no_longer_uses_microcheck_stage(self) -> None:
        REPO_ROOT = get_repo_root()
        DOCKERFILE_TEXT = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertNotIn("AS microcheck", DOCKERFILE_TEXT)
        self.assertNotIn("COPY --from=microcheck", DOCKERFILE_TEXT)
        self.assertNotIn("MCK_VER", DOCKERFILE_TEXT)

# --------------------------------------------------------------------------
# This test confirms the image-level healthcheck verifier only passes build
# arguments that the Dockerfile still consumes.
# --------------------------------------------------------------------------
    def test_healthcheck_verifier_uses_only_live_build_args(self) -> None:
        REPO_ROOT = get_repo_root()
        VERIFIER_TEXT = (
            REPO_ROOT / "scripts" / "check_image_healthcheck.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('--build-arg "ALP_VER=${ALP_VER}"', VERIFIER_TEXT)
        self.assertNotIn("MCK_VER", VERIFIER_TEXT)

# --------------------------------------------------------------------------
# This test confirms shell scripts pass POSIX syntax checks.
# --------------------------------------------------------------------------
    def test_scripts_have_valid_shell_syntax(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATHS = [
            REPO_ROOT / "check-traversal-workers.sh",
            REPO_ROOT / "scripts" / "check_image_healthcheck.sh",
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

            ENV = os.environ.copy()
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

            ENV = os.environ.copy()
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
# This test confirms healthcheck honours the configured heartbeat age budget.
# --------------------------------------------------------------------------
    def test_healthcheck_uses_configured_max_age_budget(self) -> None:
        REPO_ROOT = get_repo_root()
        HEALTHCHECK_PATH = REPO_ROOT / "scripts" / "healthcheck.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            ROOT_DIR = Path(TMPDIR)
            HEARTBEAT_PATH = ROOT_DIR / "pyiclodoc-drive-heartbeat.txt"
            HEARTBEAT_PATH.write_text("ok\n", encoding="utf-8")
            OLD_EPOCH = int(os.path.getmtime(HEARTBEAT_PATH)) - 70
            os.utime(HEARTBEAT_PATH, (OLD_EPOCH, OLD_EPOCH))

            ENV = os.environ.copy()
            ENV["HEARTBEAT_FILE"] = str(HEARTBEAT_PATH)
            ENV["HEALTHCHECK_MAX_AGE_SECONDS"] = "65"

            RESULT = subprocess.run(
                ["sh", str(HEALTHCHECK_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

            self.assertNotEqual(RESULT.returncode, 0)

# --------------------------------------------------------------------------
# This test confirms healthcheck uses the shared default heartbeat budget
# when no explicit env override is set.
# --------------------------------------------------------------------------
    def test_healthcheck_uses_default_max_age_budget_when_unset(self) -> None:
        REPO_ROOT = get_repo_root()
        HEALTHCHECK_PATH = REPO_ROOT / "scripts" / "healthcheck.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            ROOT_DIR = Path(TMPDIR)
            HEARTBEAT_PATH = ROOT_DIR / "pyiclodoc-drive-heartbeat.txt"
            HEARTBEAT_PATH.write_text("ok\n", encoding="utf-8")
            OLD_EPOCH = int(os.path.getmtime(HEARTBEAT_PATH)) - 70
            os.utime(HEARTBEAT_PATH, (OLD_EPOCH, OLD_EPOCH))

            ENV = os.environ.copy()
            ENV["HEARTBEAT_FILE"] = str(HEARTBEAT_PATH)
            ENV.pop("HEALTHCHECK_MAX_AGE_SECONDS", None)

            RESULT = subprocess.run(
                ["sh", str(HEALTHCHECK_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

            self.assertNotEqual(RESULT.returncode, 0)

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper caps recommendations at the
# highest supported traversal-worker tier.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_caps_recommendation_at_four(self) -> None:
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
            "Detected CPU count: 12\nRecommended SYNC_TRAVERSAL_WORKERS=4\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper moves to the four-worker tier
# at the first capped boundary.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_uses_four_worker_boundary_at_seven_cpu(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        RESULT = subprocess.run(
            ["sh", str(SCRIPT_PATH), "7"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 7\nRecommended SYNC_TRAVERSAL_WORKERS=4\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper recommends a conservative value
# for a four-CPU host.
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
            "Detected CPU count: 4\nRecommended SYNC_TRAVERSAL_WORKERS=2\n",
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

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper prefers Linux "nproc" output
# when it is available.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_prefers_nproc_detection(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            BIN_DIR = Path(TMPDIR) / "bin"
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            NPROC_PATH = BIN_DIR / "nproc"
            NPROC_PATH.write_text("#!/bin/sh\nprintf '6\\n'\n", encoding="utf-8")
            NPROC_PATH.chmod(NPROC_PATH.stat().st_mode | stat.S_IXUSR)

            ENV = os.environ.copy()
            ENV["PATH"] = f"{BIN_DIR}{os.pathsep}{ENV.get('PATH', '')}"

            RESULT = subprocess.run(
                ["/bin/sh", str(SCRIPT_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 6\nRecommended SYNC_TRAVERSAL_WORKERS=3\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper falls back to "getconf" when
# "nproc" is unavailable.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_falls_back_to_getconf(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            BIN_DIR = Path(TMPDIR) / "bin"
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            NPROC_PATH = BIN_DIR / "nproc"
            GETCONF_PATH = BIN_DIR / "getconf"
            NPROC_PATH.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            GETCONF_PATH.write_text("#!/bin/sh\nprintf '2\\n'\n", encoding="utf-8")
            NPROC_PATH.chmod(NPROC_PATH.stat().st_mode | stat.S_IXUSR)
            GETCONF_PATH.chmod(GETCONF_PATH.stat().st_mode | stat.S_IXUSR)

            ENV = {"PATH": f"{BIN_DIR}{os.pathsep}/usr/bin{os.pathsep}/bin"}

            RESULT = subprocess.run(
                ["/bin/sh", str(SCRIPT_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 2\nRecommended SYNC_TRAVERSAL_WORKERS=2\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper falls back to "/proc/cpuinfo"
# style parsing when command-based detection is unavailable.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_falls_back_to_proc_cpuinfo(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        with tempfile.TemporaryDirectory() as TMPDIR:
            BIN_DIR = Path(TMPDIR) / "bin"
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            CPUINFO_PATH = Path(TMPDIR) / "cpuinfo"
            NPROC_PATH = BIN_DIR / "nproc"
            GETCONF_PATH = BIN_DIR / "getconf"
            NPROC_PATH.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            GETCONF_PATH.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            NPROC_PATH.chmod(NPROC_PATH.stat().st_mode | stat.S_IXUSR)
            GETCONF_PATH.chmod(GETCONF_PATH.stat().st_mode | stat.S_IXUSR)
            CPUINFO_PATH.write_text(
                "processor\t: 0\nprocessor\t: 1\nprocessor\t: 2\n",
                encoding="utf-8",
            )

            ENV = {
                "PATH": f"{BIN_DIR}{os.pathsep}/usr/bin{os.pathsep}/bin",
                "PROC_CPUINFO_PATH": str(CPUINFO_PATH),
            }

            RESULT = subprocess.run(
                ["/bin/sh", str(SCRIPT_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=ENV,
            )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 3\nRecommended SYNC_TRAVERSAL_WORKERS=2\n",
        )

# --------------------------------------------------------------------------
# This test confirms traversal-worker helper keeps single-CPU hosts on one
# traversal worker.
# --------------------------------------------------------------------------
    def test_check_traversal_workers_recommends_one_for_single_cpu(self) -> None:
        REPO_ROOT = get_repo_root()
        SCRIPT_PATH = REPO_ROOT / "check-traversal-workers.sh"

        RESULT = subprocess.run(
            ["sh", str(SCRIPT_PATH), "1"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(RESULT.returncode, 0, msg=RESULT.stderr)
        self.assertEqual(
            RESULT.stdout,
            "Detected CPU count: 1\nRecommended SYNC_TRAVERSAL_WORKERS=1\n",
        )


if __name__ == "__main__":
    unittest.main()
