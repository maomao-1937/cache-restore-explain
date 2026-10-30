"""Behavioral checks use constructed expectations, not production ranking helpers."""
import json
import itertools
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cache_restore_explain as model

ROOT = Path(__file__).resolve().parents[1]


def cache(identifier=1, key="npm-lock", version="v1", ref="refs/heads/work",
          created="2026-10-20T00:00:00Z", **metadata):
    return dict(id=identifier, key=key, version=version, ref=ref,
                created_at=created, **metadata)


def request(**changes):
    return dict(key="npm-lock", version="v1", restore_keys=["npm-"],
                scopes=["refs/heads/work", "refs/heads/main"], **changes)


class CLITest(unittest.TestCase):
    def run_cli(self, records=None, req=None, snapshot_text=None, request_text=None,
                options=(), total=None):
        records = records if records is not None else [cache()]
        snapshot = dict(total_count=len(records) if total is None else total,
                        actions_caches=records)
        with tempfile.TemporaryDirectory(prefix="cache-explain-") as directory:
            snap = Path(directory) / "private-snapshot.json"
            ask = Path(directory) / "private-request.json"
            snap.write_text(snapshot_text if snapshot_text is not None else json.dumps(snapshot),
                            encoding="utf-8")
            ask.write_text(request_text if request_text is not None else json.dumps(req or request()),
                           encoding="utf-8")
            result = subprocess.run([sys.executable, "cache_restore_explain.py", str(snap),
                                     str(ask), *options], cwd=ROOT, capture_output=True,
                                    text=True, timeout=15)
        return result

    def assert_result(self, result, code, identifier, kind, hit):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stderr, "")
        value = json.loads(result.stdout)
        self.assertEqual(value["selected_cache_id"], identifier)
        self.assertEqual(value["match_class"], kind)
        self.assertIs(value["cache_hit"], hit)
        return value

    def assert_invalid(self, result, rationale=None):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "error")
        if rationale:
            self.assertEqual(output["rationale_codes"], [rationale])
        return output

    def test_exact_primary_is_hit(self):
        value = self.assert_result(self.run_cli(), 0, 1, "primary_exact", True)
        self.assertEqual(value["scope_index"], 0)
        self.assertIsNone(value["restore_index"])

    def test_primary_prefix_beats_restore_exact(self):
        self.assert_result(self.run_cli([cache(1, "npm-lock-extra"), cache(2, "npm-")]),
                           0, 1, "primary_prefix", False)

    def test_exact_primary_beats_newer_prefix(self):
        self.assert_result(self.run_cli([cache(), cache(2, "npm-lock-new", created="2026-10-29T00:00:00Z")]),
                           0, 1, "primary_exact", True)

    def test_specific_restore_prefix_beats_broad_restore_exact(self):
        req = request()
        req["restore_keys"] = ["npm-feature-", "npm-"]
        self.assert_result(self.run_cli([cache(1, "npm-feature-old"), cache(2, "npm-")], req),
                           0, 1, "restore_prefix", False)

    def test_restore_exact_beats_newer_same_restore_prefix(self):
        self.assert_result(self.run_cli([cache(1, "npm-"), cache(2, "npm-new", created="2026-10-29T00:00:00Z")]),
                           0, 1, "restore_exact", False)

    def test_restore_index_is_zero_based(self):
        req = request()
        req["restore_keys"] = ["absent-", "npm-"]
        value = self.assert_result(self.run_cli([cache(1, "npm-older")], req),
                                   0, 1, "restore_prefix", False)
        self.assertEqual(value["restore_index"], 1)

    def test_earlier_scope_fallback_beats_later_exact(self):
        self.assert_result(self.run_cli([cache(1, "npm-old"),
                           cache(2, ref="refs/heads/main", created="2026-10-29T00:00:00Z")]),
                           0, 1, "restore_prefix", False)

    def test_later_scope_is_used_after_earlier_exhausted(self):
        value = self.assert_result(self.run_cli([cache(ref="refs/heads/main")]),
                                   0, 1, "primary_exact", True)
        self.assertEqual(value["scope_index"], 1)

    def test_version_filter_happens_before_matching(self):
        value = self.assert_result(self.run_cli([cache(version="other"), cache(2, "npm-old"),
                                   cache(3, ref="refs/heads/unlisted")]),
                                   0, 2, "restore_prefix", False)
        self.assertEqual(value["eligible_count"], 1)
        self.assertEqual(value["rejected_counts"], {"scope_not_supplied": 1, "version_mismatch": 1})

    def test_newest_created_at_not_last_accessed_at(self):
        self.assert_result(self.run_cli([cache(1, "npm-a", last_accessed_at="2099-01-01T00:00:00Z"),
                           cache(2, "npm-b", created="2026-10-21T00:00:00Z")]),
                           0, 2, "restore_prefix", False)

    def test_offset_comparison_uses_instants(self):
        self.assert_result(self.run_cli([cache(1, "npm-a", created="2026-10-21T01:00:00+08:00"),
                           cache(2, "npm-b", created="2026-10-20T18:00:00Z")]),
                           0, 2, "restore_prefix", False)

    def test_submicrosecond_precision_is_not_lost(self):
        self.assert_result(self.run_cli([cache(99, "npm-a", created="2026-10-20T00:00:00.1234567Z"),
                           cache(2, "npm-b", created="2026-10-20T00:00:00.1234568Z")]),
                           0, 2, "restore_prefix", False)

    def test_same_instant_ties_use_highest_id_local_policy(self):
        value = self.assert_result(self.run_cli([cache(8, "npm-a", created="2026-10-20T08:00:00+08:00"),
                                   cache(9, "npm-b")]), 0, 9, "restore_prefix", False)
        self.assertIn("TIMESTAMP_TIE_ID_DESC_LOCAL_POLICY", value["rationale_codes"])

    def test_identical_cache_key_across_versions_is_allowed(self):
        self.assert_result(self.run_cli([cache(version="v2"), cache(2)]),
                           0, 2, "primary_exact", True)

    def test_empty_inventory_is_explicit_miss(self):
        value = self.assert_result(self.run_cli([]), 1, None, "none", False)
        self.assertEqual(value["coverage"], "complete_empty")

    def test_no_matching_key_is_miss(self):
        self.assert_result(self.run_cli([cache(key="pip-")]), 1, None, "none", False)

    def test_empty_restore_list_is_allowed(self):
        req = request()
        req["restore_keys"] = []
        self.assert_result(self.run_cli([cache(key="npm-other")], req), 1, None, "none", False)

    def test_require_exact_rejects_fallback_exit_only(self):
        self.assert_result(self.run_cli([cache(key="npm-old")], options=["--require-exact"]),
                           1, 1, "restore_prefix", False)

    def test_require_exact_accepts_primary_hit(self):
        self.assert_result(self.run_cli(options=["--require-exact"]), 0, 1, "primary_exact", True)

    def test_incomplete_inventory_does_not_claim_match(self):
        self.assert_invalid(self.run_cli(total=2), "INCOMPLETE_INVENTORY")

    def test_total_count_lower_than_records_is_invalid(self):
        self.assert_invalid(self.run_cli(total=0), "INCOMPLETE_INVENTORY")

    def test_duplicate_ids_are_rejected(self):
        self.assert_invalid(self.run_cli([cache(), cache()]), "DUPLICATE_CACHE_ID")

    def test_boolean_and_nonpositive_ids_are_rejected(self):
        for value in (True, False, 0, -1, 1.0, "1"):
            with self.subTest(value=value):
                self.assert_invalid(self.run_cli([cache(value)]), "INVALID_CACHE_ID")

    def test_duplicate_json_members_are_rejected(self):
        self.assert_invalid(self.run_cli(snapshot_text='{"total_count":0,"total_count":0,"actions_caches":[]}'),
                            "DUPLICATE_JSON_MEMBER")

    def test_nonfinite_values_are_rejected_even_in_metadata(self):
        for token in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(token=token):
                self.assert_invalid(self.run_cli(snapshot_text='{"total_count":0,"actions_caches":[],"extra":'+token+'}'),
                                    "NONFINITE_JSON_NUMBER")

    def test_surrogates_are_rejected_even_in_unknown_fields(self):
        self.assert_invalid(self.run_cli(snapshot_text='{"total_count":0,"actions_caches":[],"extra":"\\ud800"}'),
                            "INVALID_UNICODE")

    def test_key_length_bound_is_in_characters(self):
        req = request()
        req["key"] = "汉" * 512
        self.assert_result(self.run_cli([cache(key=req["key"])], req), 0, 1, "primary_exact", True)
        req["key"] += "汉"
        self.assert_invalid(self.run_cli([], req), "INVALID_KEY")

    def test_keys_cannot_be_empty_or_controls(self):
        for key in ("", "npm\n", "npm\x00", "npm\u202e"):
            with self.subTest(key=repr(key)):
                self.assert_invalid(self.run_cli([cache(key=key)]), "INVALID_KEY")

    def test_opaque_version_and_scope_must_be_nonempty(self):
        for field in ("version", "ref"):
            with self.subTest(field=field):
                record = cache()
                record[field] = ""
                self.assert_invalid(self.run_cli([record]), "INVALID_OPAQUE_STRING")

    def test_strict_timestamp_validation(self):
        for stamp in ("2026-10-20", "2026-10-20 00:00:00Z", "2026-10-20T00:00:00",
                      "2026-02-30T00:00:00Z", "2026-10-20T00:00:00+24:00", "2026-10-20T00:00:60Z"):
            with self.subTest(stamp=stamp):
                self.assert_invalid(self.run_cli([cache(created=stamp)]), "INVALID_TIMESTAMP")

    def test_unknown_offset_timestamp_is_explicitly_unsupported(self):
        self.assert_invalid(self.run_cli([cache(created="2026-10-20T00:00:00-00:00")]),
                            "UNSUPPORTED_UNKNOWN_OFFSET")

    def test_duplicate_or_empty_scopes_are_rejected(self):
        for scopes in ([], ["same", "same"]):
            req = request()
            req["scopes"] = scopes
            self.assert_invalid(self.run_cli([], req), "INVALID_SCOPES")

    def test_unknown_request_field_is_unsupported(self):
        req = request()
        req["workflow"] = "private.yaml"
        self.assert_invalid(self.run_cli([], req), "UNSUPPORTED_REQUEST_FIELD")

    def test_input_schema_type_errors(self):
        for text in ('[]', '{}', '{"total_count":true,"actions_caches":[]}',
                     '{"total_count":0,"actions_caches":{}}'):
            with self.subTest(text=text):
                self.assert_invalid(self.run_cli(snapshot_text=text))

    def test_nested_input_depth_limit(self):
        text = '{"total_count":0,"actions_caches":[],"metadata":' + '['*33 + '0' + ']'*33 + '}'
        self.assert_invalid(self.run_cli(snapshot_text=text), "JSON_DEPTH_LIMIT")

    def test_input_byte_limit(self):
        self.assert_invalid(self.run_cli(snapshot_text=' ' * (8 * 1024 * 1024 + 1)), "INPUT_BYTE_LIMIT")

    def test_record_count_limit(self):
        self.assert_invalid(self.run_cli([cache(i+1) for i in range(10001)]), "RECORD_LIMIT")

    def test_restore_key_and_scope_count_limits(self):
        for field in ("restore_keys", "scopes"):
            req = request()
            req[field] = [str(i) for i in range(129)]
            self.assert_invalid(self.run_cli([], req))

    def test_success_output_does_not_echo_untrusted_values(self):
        marker = "sensitive-PRIVATE-opaque"
        req = dict(key=marker, version=marker, restore_keys=[], scopes=[marker])
        result = self.run_cli([cache(key=marker, ref=marker, version=marker)], req)
        self.assert_result(result, 0, 1, "primary_exact", True)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertNotIn("private-snapshot", result.stdout + result.stderr)

    def test_argument_error_does_not_echo_argument_or_path(self):
        result = self.run_cli(options=["--SECRET-private-option"])
        self.assert_invalid(result, "INVALID_ARGUMENTS")
        self.assertNotIn("SECRET", result.stdout + result.stderr)
        self.assertNotIn("private-snapshot", result.stdout + result.stderr)

    def test_invalid_json_does_not_echo_input(self):
        result = self.run_cli(snapshot_text='SECRET-invalid-json')
        self.assert_invalid(result, "INVALID_JSON")
        self.assertNotIn("SECRET", result.stdout + result.stderr)

    def test_missing_input_is_operational_error_without_path(self):
        result = subprocess.run([sys.executable, "cache_restore_explain.py", "SECRET-missing", "SECRET-request"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assert_invalid(result, "INPUT_IO_ERROR")
        self.assertNotIn("SECRET", result.stdout + result.stderr)

    def test_help_is_available_without_files(self):
        result = subprocess.run([sys.executable, "cache_restore_explain.py", "--help"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--require-exact", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_output_and_help_broken_pipe_are_handled(self):
        for args in (["--help"], ["SECRET-missing", "SECRET-request"]):
            with self.subTest(args=args):
                process = subprocess.Popen([sys.executable, "cache_restore_explain.py", *args],
                                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.stdout.close()
                try:
                    error = process.stderr.read()
                    self.assertEqual(process.wait(timeout=15), 2)
                    self.assertEqual(error, b"")
                finally:
                    process.stderr.close()
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=15)


class UnitTest(unittest.TestCase):
    def test_hand_constructed_ordering_oracle_survives_inventory_permutations(self):
        # Each row adds a higher-priority stage. Expected IDs are independently
        # specified from the documented rule, not calculated by a second ranker.
        inventory = [cache(1, "npm-other", ref="refs/heads/main"),
                     cache(2, "npm-lock", ref="refs/heads/main"),
                     cache(3, "npm-a"), cache(4, "npm-"),
                     cache(5, "npm-lock-extra"), cache(6)]
        expected_ids = [1, 2, 3, 4, 5, 6]
        for length, expected in enumerate(expected_ids, 1):
            for permutation in itertools.permutations(inventory[:length]):
                result = model.explain(model.validate_snapshot(dict(
                    total_count=length, actions_caches=list(permutation))),
                    model.validate_request(request()))
                self.assertEqual(result["selected_cache_id"], expected)

    def test_negative_offsets_and_lowercase_rfc3339_are_exact(self):
        self.assertEqual(model.timestamp("2026-10-20t00:00:00.250z"),
                         model.timestamp("2026-10-19T19:00:00.25-05:00"))

    def test_rejections_partition_inventory_even_when_both_scope_and_version_differ(self):
        records = [cache(), cache(2, ref="unlisted", version="other"),
                   cache(3, version="other"), cache(4, key="unrelated")]
        result = model.explain(model.validate_snapshot(dict(total_count=4, actions_caches=records)),
                               model.validate_request(request()))
        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(sum(result["rejected_counts"].values()), 2)

    def test_normalization_is_not_silently_applied_to_keys(self):
        req = request()
        req.update(key="café", restore_keys=[])
        result = model.explain(model.validate_snapshot(dict(total_count=1,
            actions_caches=[cache(key="cafe\u0301")])), model.validate_request(req))
        self.assertEqual(result["status"], "miss")


if __name__ == "__main__":
    unittest.main()
