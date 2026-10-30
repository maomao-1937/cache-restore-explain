# Verification record

Local verification performed 2026-10-30 on Windows 10 build 26300,
CPython 3.11.15. No third-party packages were used.

```console
python -m unittest discover -s tests -v
```

Latest result: **48 tests passed**, 7.795 seconds. This includes 44 real CLI test
methods (additional adversarial subcases) and 4 direct unit methods. Subprocesses
use the active Python executable, a script basename, explicit repository `cwd`,
captured/managed pipes, and 15-second timeouts. The product itself starts no
subprocesses. Tests write only temporary input fixtures.

`checks.json` is a list of 12 source-script argument/expected-exit objects for a
shared Python-only runner. All 12 were executed locally; the example verification
also checked the independently specified selected ID and match class for every
match/miss fixture. No project-specific CI runner is required.

## Evidence and methodology

- Before product source existed, the initial 44 CLI methods were executed: 65
  expected behavioral assertion/subcase failures, exit 1, no test errors. This is
  the recorded RED phase: required successful behavior/output was absent.
- After implementation, those same 44 methods passed (8.264 seconds).
- Four unit methods were then added for independent verification. One uses a
  hand-constructed priority ladder, checking all 873 permutations of its six
  successively enlarged inventories; expected IDs are written explicitly, not
  derived through production ordering helpers.
- The final 48-method run and all 12 fixture checks passed. Builder handoff
  evidence retains raw RED/GREEN/final output, environment information, and full
  example results outside the publishable source tree.

## What was exercised

Primary exact and prefix priority; restore exact before prefix; specific restore
before broad; scope priority ahead of fallback quality/time; version filtering;
positive IDs, duplicate ID rejection, and legitimate repeated keys across versions;
newest creation rather than access time; offset-normalized instants; submicrosecond
precision; deterministic ID ties; empty inventory; miss and exact-required exit
policy; pagination-count disagreement; duplicate JSON fields; nonfinite and
overflowing floats; surrogates; key lengths and controls; schema errors; unsupported
request fields; byte, nesting, record, list-size limits; argument errors; missing
files; output privacy; help; and closed stdout for both help and JSON output.

The expected selection oracle is constructed from documented model requirements.
It is not a duplicate implementation of the selection algorithm, and it does not
ask the program to produce its own expected result.

## Verification limits

This record establishes local behavior for the specified bounded offline model.
No real cache was restored, saved, or deleted; no live GitHub cache service
comparison was performed. This record does not assert service conformance,
workflow access eligibility, snapshot provenance/freshness, eviction behavior,
archive compatibility, availability, or decompression safety. Hosted Ubuntu and
Windows CI evidence, if produced later, must be checked separately. No coverage
percentage or exhaustive correctness claim is made.
