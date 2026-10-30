#!/usr/bin/env python3
"""Explain a bounded, explicitly scoped offline cache inventory. No service calls."""
from __future__ import annotations

import argparse
from datetime import date
from fractions import Fraction
import json
import math
import os
import re
import sys
import unicodedata

MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32
MAX_RECORDS = 10_000
MAX_ORDERED_ITEMS = 128
MAX_OPAQUE_LENGTH = 4096
MAX_TIMESTAMP_LENGTH = 128
TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]"
    r"([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?"
    r"([Zz]|[+-][0-9]{2}:[0-9]{2})\Z"
)


class InputError(Exception):
    """Only fixed, public reason codes may reach output."""


def fail(code: str) -> None:
    raise InputError(code)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            fail("DUPLICATE_JSON_MEMBER")
        result[name] = value
    return result


def reject_constant(_value: str) -> None:
    fail("NONFINITE_JSON_NUMBER")


def check_tree(value: object) -> None:
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_DEPTH:
            fail("JSON_DEPTH_LIMIT")
        if isinstance(item, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                fail("INVALID_UNICODE")
        elif isinstance(item, float) and not math.isfinite(item):
            fail("NONFINITE_JSON_NUMBER")
        elif isinstance(item, dict):
            stack.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif isinstance(item, list):
            stack.extend((part, depth + 1) for part in item)


def read_json(path: str) -> object:
    try:
        with open(path, "rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        fail("INPUT_IO_ERROR")
    if len(raw) > MAX_BYTES:
        fail("INPUT_BYTE_LIMIT")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
    except RecursionError:
        fail("JSON_DEPTH_LIMIT")
    except (UnicodeError, ValueError):
        fail("INVALID_JSON")
    check_tree(value)
    return value


def normal_string(value: object, maximum: int, code: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                   for char in value)):
        fail(code)
    return value


def key_string(value: object) -> str:
    return normal_string(value, 512, "INVALID_KEY")


def opaque_string(value: object) -> str:
    return normal_string(value, MAX_OPAQUE_LENGTH, "INVALID_OPAQUE_STRING")


def timestamp(value: object) -> Fraction:
    """Compare exact fractional seconds, including beyond datetime microseconds."""
    if not isinstance(value, str) or len(value) > MAX_TIMESTAMP_LENGTH:
        fail("INVALID_TIMESTAMP")
    match = TIMESTAMP.fullmatch(value)
    if match is None:
        fail("INVALID_TIMESTAMP")
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    fraction, zone = match.groups()[6:]
    if zone == "-00:00":
        fail("UNSUPPORTED_UNKNOWN_OFFSET")
    try:
        ordinal = date(year, month, day).toordinal()
    except ValueError:
        fail("INVALID_TIMESTAMP")
    if hour > 23 or minute > 59 or second > 59:
        fail("INVALID_TIMESTAMP")
    offset = 0
    if zone not in {"Z", "z"}:
        offset_hour, offset_minute = int(zone[1:3]), int(zone[4:6])
        if offset_hour > 23 or offset_minute > 59:
            fail("INVALID_TIMESTAMP")
        offset = (offset_hour * 60 + offset_minute) * 60
        if zone[0] == "-":
            offset = -offset
    seconds = ordinal * 86400 + hour * 3600 + minute * 60 + second - offset
    return Fraction(seconds) + (Fraction(int(fraction), 10 ** len(fraction))
                                if fraction else Fraction(0))


def validate_snapshot(value: object) -> list[dict]:
    if not isinstance(value, dict) or not {"total_count", "actions_caches"} <= value.keys():
        fail("INVALID_SNAPSHOT")
    total, records = value["total_count"], value["actions_caches"]
    if type(total) is not int or total < 0 or not isinstance(records, list):
        fail("INVALID_SNAPSHOT")
    if len(records) > MAX_RECORDS or total > MAX_RECORDS:
        fail("RECORD_LIMIT")
    if total != len(records):
        fail("INCOMPLETE_INVENTORY")
    seen_ids = set()
    validated = []
    for record in records:
        if not isinstance(record, dict):
            fail("INVALID_CACHE_RECORD")
        identifier = record.get("id")
        if type(identifier) is not int or identifier <= 0:
            fail("INVALID_CACHE_ID")
        if identifier in seen_ids:
            fail("DUPLICATE_CACHE_ID")
        seen_ids.add(identifier)
        validated.append({"id": identifier, "key": key_string(record.get("key")),
                          "version": opaque_string(record.get("version")),
                          "ref": opaque_string(record.get("ref")),
                          "instant": timestamp(record.get("created_at"))})
    return validated


def validate_request(value: object) -> dict:
    fields = {"key", "version", "restore_keys", "scopes"}
    if not isinstance(value, dict):
        fail("INVALID_REQUEST")
    if value.keys() - fields:
        fail("UNSUPPORTED_REQUEST_FIELD")
    if fields - value.keys():
        fail("INVALID_REQUEST")
    primary = key_string(value["key"])
    version = opaque_string(value["version"])
    restore = value["restore_keys"]
    if not isinstance(restore, list) or len(restore) > MAX_ORDERED_ITEMS:
        fail("INVALID_RESTORE_KEYS")
    restore = [key_string(item) for item in restore]
    scopes = value["scopes"]
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= MAX_ORDERED_ITEMS:
        fail("INVALID_SCOPES")
    scopes = [opaque_string(item) for item in scopes]
    if len(set(scopes)) != len(scopes):
        fail("INVALID_SCOPES")
    return dict(key=primary, version=version, restore_keys=restore, scopes=scopes)


def explain(records: list[dict], request: dict) -> dict:
    by_scope = {scope: [] for scope in request["scopes"]}
    rejected = {"scope_not_supplied": 0, "version_mismatch": 0}
    for record in records:
        # Exclusive rejection counts: scope takes precedence over version.
        if record["ref"] not in by_scope:
            rejected["scope_not_supplied"] += 1
        elif record["version"] != request["version"]:
            rejected["version_mismatch"] += 1
        else:
            by_scope[record["ref"]].append(record)
    output = dict(
        status="miss", coverage="complete_nonempty" if records else "complete_empty",
        inventory_count=len(records), eligible_count=sum(map(len, by_scope.values())),
        rejected_counts=rejected, selected_cache_id=None, scope_index=None,
        match_class="none", restore_index=None, cache_hit=False,
        rationale_codes=["OFFLINE_MODEL", "SUPPLIED_VERSION_AND_SCOPE_ORDER", "NO_MATCH"],
    )
    stages = [(request["key"], "primary_exact", None, False),
              (request["key"], "primary_prefix", None, True)]
    for index, restore in enumerate(request["restore_keys"]):
        stages.extend([(restore, "restore_exact", index, False),
                       (restore, "restore_prefix", index, True)])
    for scope_index, scope in enumerate(request["scopes"]):
        for search_key, match_class, restore_index, prefix in stages:
            candidates = [record for record in by_scope[scope]
                          if (record["key"].startswith(search_key) if prefix
                              else record["key"] == search_key)]
            if not candidates:
                continue
            selected = max(candidates, key=lambda record: (record["instant"], record["id"]))
            codes = ["OFFLINE_MODEL", "SUPPLIED_VERSION_AND_SCOPE_ORDER",
                     "FIRST_SCOPE_AND_MATCH_STAGE", "NEWEST_CREATED_AT"]
            if sum(record["instant"] == selected["instant"] for record in candidates) > 1:
                codes.append("TIMESTAMP_TIE_ID_DESC_LOCAL_POLICY")
            output.update(status="match", selected_cache_id=selected["id"],
                          scope_index=scope_index, match_class=match_class,
                          restore_index=restore_index, cache_hit=match_class == "primary_exact",
                          rationale_codes=codes)
            return output
    return output


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        fail("INVALID_ARGUMENTS")

    def exit(self, status: int = 0, message: str | None = None) -> None:
        # Help must flush inside the protected entry point, not at interpreter exit.
        sys.stdout.flush()
        raise SystemExit(status)


def emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    try:
        parser = PrivateArgumentParser(
            prog="cache-restore-explain", allow_abbrev=False,
            description="Explain an offline JSON inventory using supplied version and eligible scope order.")
        parser.add_argument("snapshot", help="complete REST-shaped inventory JSON file")
        parser.add_argument("request", help="explicit key, restore_keys, version and scopes JSON file")
        parser.add_argument("--require-exact", action="store_true",
                            help="exit 1 for any fallback as well as a miss")
        arguments = parser.parse_args(argv)
        records = validate_snapshot(read_json(arguments.snapshot))
        request = validate_request(read_json(arguments.request))
        output = explain(records, request)
        emit(output)
        return int(output["status"] == "miss" or (arguments.require_exact and not output["cache_hit"]))
    except InputError as error:
        emit({"status": "error", "rationale_codes": [str(error)]})
        return 2


def entry() -> int:
    try:
        return main()
    except OSError:
        # A closed output consumer is operational failure; avoid shutdown tracebacks.
        try:
            descriptor = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(descriptor, sys.stdout.fileno())
            finally:
                os.close(descriptor)
        except (OSError, ValueError):
            pass
        return 2


if __name__ == "__main__":
    sys.exit(entry())
