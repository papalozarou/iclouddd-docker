# ------------------------------------------------------------------------------
# This test module verifies JSON-backed runtime state and manifest helpers.
# ------------------------------------------------------------------------------

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from app.state import (
    AuthState,
    load_auth_state,
    load_manifest,
    now_iso,
    read_json,
    save_auth_state,
    save_manifest,
    write_json,
)


# ------------------------------------------------------------------------------
# These tests validate state IO defaults, persistence, and manifest filtering.
# ------------------------------------------------------------------------------
class TestState(unittest.TestCase):
# --------------------------------------------------------------------------
# This test confirms reading a missing JSON file returns an empty payload.
# --------------------------------------------------------------------------
    def test_read_json_missing_returns_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "missing.json"
            RESULT = read_json(PATH)

        self.assertEqual(RESULT, {})

# --------------------------------------------------------------------------
# This test confirms malformed JSON is quarantined and replaced with an
# empty payload.
# --------------------------------------------------------------------------
    def test_read_json_quarantines_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "broken.json"
            PATH.write_text("{not-valid", encoding="utf-8")

            with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                with patch("builtins.print") as PRINT:
                    RESULT = read_json(PATH)

            self.assertEqual(RESULT, {})
            self.assertFalse(PATH.exists())
            self.assertTrue((Path(TMPDIR) / "broken.json.corrupt").exists())
            self.assertTrue(any("Corrupt JSON state ignored" in CALL.args[0] for CALL in PRINT.call_args_list))

# --------------------------------------------------------------------------
# This test confirms corrupt JSON reads emit debug diagnostics without raw
# parser detail.
# --------------------------------------------------------------------------
    def test_read_json_logs_corrupt_json_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "broken.json"
            LOG_FILE = Path(TMPDIR) / "worker.log"
            PATH.write_text("{not-valid", encoding="utf-8")

            with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                with patch("builtins.print"):
                    with patch("app.state.log_line") as LOG_LINE:
                        RESULT = read_json(PATH, LOG_FILE)

        self.assertEqual(RESULT, {})
        DEBUG_LINES = [
            CALL.args[2]
            for CALL in LOG_LINE.call_args_list
            if CALL.args[1] == "debug"
        ]
        self.assertTrue(any("State read failed:" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(any("reason=corrupt_json" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(any("Corrupt state quarantined:" in LINE for LINE in DEBUG_LINES))
        self.assertFalse(any("Expecting" in LINE for LINE in DEBUG_LINES))

# --------------------------------------------------------------------------
# This test confirms read failures fall back safely to an empty payload.
# --------------------------------------------------------------------------
    def test_read_json_returns_empty_dict_when_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "broken.json"
            PATH.write_text("{}", encoding="utf-8")

            with patch.object(Path, "open", side_effect=OSError("permission denied")):
                with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                    with patch("builtins.print") as PRINT:
                        RESULT = read_json(PATH)

            self.assertEqual(RESULT, {})
            self.assertTrue(PATH.exists())
            self.assertTrue(any("State read failed" in CALL.args[0] for CALL in PRINT.call_args_list))

# --------------------------------------------------------------------------
# This test confirms JSON writes are persisted with the expected structure.
# --------------------------------------------------------------------------
    def test_write_json_persists_payload(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "data.json"
            PAYLOAD = {"a": 1, "b": {"c": 2}}
            write_json(PATH, PAYLOAD)

            self.assertTrue(PATH.exists())
            self.assertFalse((Path(TMPDIR) / "data.json.tmp").exists())
            WRITTEN = json.loads(PATH.read_text(encoding="utf-8"))

        self.assertEqual(WRITTEN, PAYLOAD)

# --------------------------------------------------------------------------
# This test confirms JSON writes emit debug diagnostics for successful
# persistence.
# --------------------------------------------------------------------------
    def test_write_json_logs_successful_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "data.json"
            LOG_FILE = Path(TMPDIR) / "worker.log"
            PAYLOAD = {"a": 1, "b": {"c": 2}}

            with patch("app.state.log_line") as LOG_LINE:
                write_json(PATH, PAYLOAD, LOG_FILE)

        DEBUG_LINES = [
            CALL.args[2]
            for CALL in LOG_LINE.call_args_list
            if CALL.args[1] == "debug"
        ]
        self.assertTrue(any("State write completed:" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(any("keys=2" in LINE for LINE in DEBUG_LINES))

# --------------------------------------------------------------------------
# This test confirms write failures warn and leave the destination untouched.
# --------------------------------------------------------------------------
    def test_write_json_warns_when_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "data.json"

            with patch.object(Path, "open", side_effect=OSError("disk full")):
                with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                    with patch("builtins.print") as PRINT:
                        write_json(PATH, {"a": 1})

            self.assertFalse(PATH.exists())
            self.assertTrue(any("State write failed" in CALL.args[0] for CALL in PRINT.call_args_list))

# --------------------------------------------------------------------------
# This test confirms write failures emit debug diagnostics without raw
# exception text.
# --------------------------------------------------------------------------
    def test_write_json_logs_failure_without_raw_exception_text(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "data.json"
            LOG_FILE = Path(TMPDIR) / "worker.log"

            with patch.object(Path, "open", side_effect=OSError("disk secret")):
                with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                    with patch("builtins.print"):
                        with patch("app.state.log_line") as LOG_LINE:
                            write_json(PATH, {"a": 1}, LOG_FILE)

        DEBUG_LINES = [
            CALL.args[2]
            for CALL in LOG_LINE.call_args_list
            if CALL.args[1] == "debug"
        ]
        self.assertTrue(any("State write failed:" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(any("reason=OSError" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(
            any("Temporary state cleanup skipped:" in LINE for LINE in DEBUG_LINES)
        )
        self.assertFalse(any("disk secret" in LINE for LINE in DEBUG_LINES))

# --------------------------------------------------------------------------
# This test confirms replace failures warn and remove the temporary file.
# --------------------------------------------------------------------------
    def test_write_json_warns_and_cleans_up_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "data.json"
            TEMP_PATH = Path(TMPDIR) / "data.json.tmp"

            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                    with patch("builtins.print") as PRINT:
                        write_json(PATH, {"a": 1})

            self.assertFalse(PATH.exists())
            self.assertFalse(TEMP_PATH.exists())
            self.assertTrue(any("State write failed" in CALL.args[0] for CALL in PRINT.call_args_list))

# --------------------------------------------------------------------------
# This test confirms temporary cleanup failures are warned and do not raise.
# --------------------------------------------------------------------------
    def test_write_json_warns_when_temporary_cleanup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "data.json"

            ORIGINAL_UNLINK = Path.unlink

            def fake_unlink(TARGET: Path, *ARGS, **KWARGS):
                if TARGET.name.endswith(".tmp"):
                    raise OSError("unlink failed")
                return ORIGINAL_UNLINK(TARGET, *ARGS, **KWARGS)

            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with patch.object(Path, "unlink", new=fake_unlink):
                    with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                        with patch("builtins.print") as PRINT:
                            write_json(PATH, {"a": 1})

            self.assertTrue(any("Temporary state cleanup failed" in CALL.args[0] for CALL in PRINT.call_args_list))

# --------------------------------------------------------------------------
# This test confirms auth-state loading uses safe defaults when missing.
# --------------------------------------------------------------------------
    def test_load_auth_state_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "auth_state.json"
            STATE = load_auth_state(PATH)

        self.assertEqual(STATE.last_auth_utc, "1970-01-01T00:00:00+00:00")
        self.assertFalse(STATE.auth_pending)
        self.assertFalse(STATE.reauth_pending)
        self.assertEqual(STATE.reminder_stage, "none")

# --------------------------------------------------------------------------
# This test confirms corrupt auth-state JSON falls back to safe defaults.
# --------------------------------------------------------------------------
    def test_load_auth_state_defaults_for_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "auth_state.json"
            PATH.write_text("{bad", encoding="utf-8")

            with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                with patch("builtins.print"):
                    STATE = load_auth_state(PATH)

        self.assertEqual(STATE.last_auth_utc, "1970-01-01T00:00:00+00:00")
        self.assertFalse(STATE.auth_pending)
        self.assertFalse(STATE.reauth_pending)
        self.assertEqual(STATE.reminder_stage, "none")

# --------------------------------------------------------------------------
# This test confirms valid non-dictionary auth-state JSON falls back to safe
# defaults.
# --------------------------------------------------------------------------
    def test_load_auth_state_defaults_for_non_dict_json(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "auth_state.json"
            PATH.write_text(json.dumps(["unexpected"]), encoding="utf-8")
            STATE = load_auth_state(PATH)

        self.assertEqual(STATE.last_auth_utc, "1970-01-01T00:00:00+00:00")
        self.assertFalse(STATE.auth_pending)
        self.assertFalse(STATE.reauth_pending)
        self.assertEqual(STATE.reminder_stage, "none")

# --------------------------------------------------------------------------
# This test confirms auth-state saving and loading round-trip correctly.
# --------------------------------------------------------------------------
    def test_save_auth_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "auth_state.json"
            INPUT_STATE = AuthState(
                last_auth_utc="2026-03-09T09:00:00+00:00",
                auth_pending=True,
                reauth_pending=False,
                reminder_stage="alert5",
            )
            IS_SAVED = save_auth_state(PATH, INPUT_STATE)
            OUTPUT_STATE = load_auth_state(PATH)

        self.assertTrue(IS_SAVED)
        self.assertEqual(OUTPUT_STATE, INPUT_STATE)

# --------------------------------------------------------------------------
# This test confirms auth-state load and save emit state-specific debug
# diagnostics.
# --------------------------------------------------------------------------
    def test_auth_state_logs_persistence_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "auth_state.json"
            LOG_FILE = Path(TMPDIR) / "worker.log"
            INPUT_STATE = AuthState(
                last_auth_utc="2026-03-09T09:00:00+00:00",
                auth_pending=True,
                reauth_pending=False,
                reminder_stage="alert5",
            )

            with patch("app.state.log_line") as LOG_LINE:
                save_auth_state(PATH, INPUT_STATE, LOG_FILE)
                OUTPUT_STATE = load_auth_state(PATH, LOG_FILE)

        self.assertEqual(OUTPUT_STATE, INPUT_STATE)
        DEBUG_LINES = [
            CALL.args[2]
            for CALL in LOG_LINE.call_args_list
            if CALL.args[1] == "debug"
        ]
        self.assertTrue(any("Auth state save requested:" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(
            any("Auth state loaded from persistence:" in LINE for LINE in DEBUG_LINES)
        )

# --------------------------------------------------------------------------
# This test confirms manifest loading keeps only dictionary entries.
# --------------------------------------------------------------------------
    def test_load_manifest_filters_invalid_payload_items(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "manifest.json"
            PATH.write_text(
                json.dumps(
                    {
                        "/valid": {"etag": "1"},
                        "/invalid": "not-a-dict",
                    }
                ),
                encoding="utf-8",
            )

            MANIFEST = load_manifest(PATH)

        self.assertEqual(MANIFEST, {"/valid": {"etag": "1"}})

# --------------------------------------------------------------------------
# This test confirms non-dictionary manifest payloads are rejected.
# --------------------------------------------------------------------------
    def test_load_manifest_rejects_non_dict_payload(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "manifest.json"
            PATH.write_text(json.dumps(["invalid"]), encoding="utf-8")
            MANIFEST = load_manifest(PATH)

        self.assertEqual(MANIFEST, {})

# --------------------------------------------------------------------------
# This test confirms corrupt manifest JSON falls back to an empty manifest.
# --------------------------------------------------------------------------
    def test_load_manifest_returns_empty_for_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "manifest.json"
            PATH.write_text("{bad", encoding="utf-8")

            with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                with patch("builtins.print"):
                    MANIFEST = load_manifest(PATH)

        self.assertEqual(MANIFEST, {})

# --------------------------------------------------------------------------
# This test confirms manifest save persists all provided manifest entries.
# --------------------------------------------------------------------------
    def test_save_manifest_persists_payload(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "manifest.json"
            PAYLOAD = {"/a": {"etag": "1"}, "/b": {"etag": "2"}}
            IS_SAVED = save_manifest(PATH, PAYLOAD)
            WRITTEN = json.loads(PATH.read_text(encoding="utf-8"))

        self.assertTrue(IS_SAVED)
        self.assertEqual(WRITTEN, PAYLOAD)

# --------------------------------------------------------------------------
# This test confirms manifest save reports failure when the destination
# parent path cannot behave as a directory.
# --------------------------------------------------------------------------
    def test_save_manifest_returns_false_when_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            ROOT_DIR = Path(TMPDIR)
            BLOCKING_PATH = ROOT_DIR / "manifest.json"
            BLOCKING_PATH.write_text("occupied", encoding="utf-8")
            PATH = BLOCKING_PATH / "child.json"

            with patch("app.state.get_timestamp", return_value="2026-03-14 16:30:00 UTC"):
                with patch("builtins.print"):
                    IS_SAVED = save_manifest(PATH, {"/a": {"etag": "1"}})

        self.assertFalse(IS_SAVED)
        self.assertFalse(PATH.exists())

# --------------------------------------------------------------------------
# This test confirms manifest load and save emit entry-count diagnostics.
# --------------------------------------------------------------------------
    def test_manifest_logs_persistence_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            PATH = Path(TMPDIR) / "manifest.json"
            LOG_FILE = Path(TMPDIR) / "worker.log"
            PAYLOAD = {"/a": {"etag": "1"}, "/bad": "ignored"}
            PATH.write_text(json.dumps(PAYLOAD), encoding="utf-8")

            with patch("app.state.log_line") as LOG_LINE:
                MANIFEST = load_manifest(PATH, LOG_FILE)
                save_manifest(PATH, MANIFEST, LOG_FILE)

        self.assertEqual(MANIFEST, {"/a": {"etag": "1"}})
        DEBUG_LINES = [
            CALL.args[2]
            for CALL in LOG_LINE.call_args_list
            if CALL.args[1] == "debug"
        ]
        self.assertTrue(
            any("Manifest loaded from persistence:" in LINE for LINE in DEBUG_LINES)
        )
        self.assertTrue(any("valid_entries=1" in LINE for LINE in DEBUG_LINES))
        self.assertTrue(any("Manifest save requested:" in LINE for LINE in DEBUG_LINES))

# --------------------------------------------------------------------------
# This test confirms now_iso delegates to now_local_iso.
# --------------------------------------------------------------------------
    def test_now_iso_uses_time_utils_delegate(self) -> None:
        with patch("app.state.now_local_iso", return_value="2026-03-09T12:00:00+00:00"):
            VALUE = now_iso()

        self.assertEqual(VALUE, "2026-03-09T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
