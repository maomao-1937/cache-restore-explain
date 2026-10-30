# Research and model boundary

Primary sources read on 2026-10-30:

- [GitHub dependency caching reference](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#cache-key-matching)
  describes primary exact, primary prefix, ordered restore fallbacks, and repeating
  the search on the default branch. Its restore-key section specifies exact before
  prefix and newest creation for multiple partial matches.
- [GitHub REST cache inventory](https://docs.github.com/en/rest/actions/cache#list-github-actions-caches-for-a-repository)
  supplies ID, key, ref, version, and creation time. It documents `page`, `per_page`,
  filters, and sorting. One page is not a complete inventory.
- [actions/cache](https://github.com/actions/cache#cache-version) documents the
  primary-key hit indicator and version's relation to cached paths/compression.

## Facts, choices, and unknowns

The hierarchy is grounded in those descriptions. Request version and already
eligible scope order are caller assumptions, not findings established by this
program. In particular, REST inventory visibility does not establish restore
permission for a workflow. PR merge refs, base/default scopes, tokens, trigger
modes, and policies must be resolved outside the model.

Local choices: exact string equality; newest creation in any multi-candidate
stage; highest positive ID for equal instants; strict JSON, resource limits,
rejection of unknown request fields, and a privacy-preserving result schema.
The official descriptions do not promise the ID tie policy. Count agreement is
only structural completeness validation and cannot establish snapshot freshness.
No online differential test against GitHub's cache service was performed. This
is an explanation of a specified offline model, not a compatible reimplementation
of a private service protocol. The source was independently written with the
Python standard library; no upstream implementation was copied.

## Alternatives and why this exists

- [actionlint](https://github.com/rhysd/actionlint) statically checks workflow YAML.
  Use it for workflow syntax and expressions; it serves a different input/output
  contract from selecting among exported cache records.
- [actions/cache and its restore action](https://github.com/actions/cache)
  perform actual cache lookup and restoration in an Actions environment. Use them
  when real runtime behavior is needed.
- The [REST cache endpoints](https://docs.github.com/en/rest/actions/cache) retrieve
  or manage inventory. They remain the data source, not an offline explanation
  that resolves supplied fallback order with fixed, non-echoing diagnostics.

This small tool fills the local review step: explain a proposed request against
a supplied inventory with no token or cache operation. It cannot assess eviction,
archive safety, artifact contents, permissions, current availability, or whether
the caller supplied the correct version and accessible refs.
