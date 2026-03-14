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
            save_auth_state(PATH, INPUT_STATE)
            OUTPUT_STATE = load_auth_state(PATH)

        self.assertEqual(OUTPUT_STATE, INPUT_STATE)

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
            save_manifest(PATH, PAYLOAD)
            WRITTEN = json.loads(PATH.read_text(encoding="utf-8"))

        self.assertEqual(WRITTEN, PAYLOAD)

# --------------------------------------------------------------------------
# This test confirms now_iso delegates to now_local_iso.
# --------------------------------------------------------------------------
    def test_now_iso_uses_time_utils_delegate(self) -> None:
        with patch("app.state.now_local_iso", return_value="2026-03-09T12:00:00+00:00"):
            VALUE = now_iso()

        self.assertEqual(VALUE, "2026-03-09T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
