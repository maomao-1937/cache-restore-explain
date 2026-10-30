# cache-restore-explain

[![tests](https://github.com/maomao-1937/cache-restore-explain/actions/workflows/tests.yml/badge.svg)](https://github.com/maomao-1937/cache-restore-explain/actions/workflows/tests.yml)

Explain why an offline GitHub Actions cache inventory would select a cache,
fall back, or miss under an explicitly supplied matching model. Get a stable
JSON result suitable for local troubleshooting without printing keys, versions,
refs, input paths, or argument values.

## Install and run

Python 3.11+; standard library only. Download the source or clone this repository,
then run from its directory. No package installation, token, YAML configuration,
network connection, or GitHub login is needed.

```console
python cache_restore_explain.py examples/inventory.json examples/request-exact.json
python cache_restore_explain.py examples/inventory.json examples/request-restore.json --require-exact
python -m unittest discover -s tests -v
```

The first command exits 0 and selects ID 101 as `primary_exact`. The second
selects ID 102 as `restore_prefix`, sets `cache_hit` to false, and exits 1
because `--require-exact` rejects fallback for its exit policy.

## Input contract

Snapshot JSON is REST-shaped:

```json
{"total_count":1,"actions_caches":[{"id":101,"key":"npm-lock","version":"v1","ref":"refs/heads/work","created_at":"2026-10-20T00:00:00Z"}]}
```

Request JSON contains exactly these four fields:

```json
{"key":"npm-lock","restore_keys":["npm-"],"version":"v1","scopes":["refs/heads/work","refs/heads/main"]}
```

`scopes` must be a nonempty, unique, ordered list of **already eligible** refs.
The caller supplies the version too. Neither value is inferred from workflow
events, permissions, default branches, expressions, paths, archive formats, or
runner platforms. Strings compare literally and case sensitively, with no Unicode
normalization. `restore_keys` may be empty; repeated entries are allowed.
Unknown request fields are rejected. Extra snapshot/record metadata is ignored
after the entire JSON tree passes safety validation.

The [REST list endpoint](https://docs.github.com/en/rest/actions/cache#list-github-actions-caches-for-a-repository)
is paginated. Before using this tool, combine every relevant page into one object
and preserve the applicable `total_count`. Count disagreement exits 2. Agreement
is a necessary check, **not proof** that the export was complete, unfiltered, or
current; this tool cannot verify its provenance. A filtered or changing export can
omit a winning candidate. `{ "total_count": 0, "actions_caches": [] }` is accepted
only as an explicitly empty inventory and returns a miss, never a successful match.

## Model and output

For each supplied scope, version-compatible candidates are considered in this
order: primary exact, primary prefix, then each restore key's exact and prefix
stages. The first nonempty stage wins. Newest `created_at` wins within that stage.
An earlier scope's fallback beats a later scope's exact match. Only primary exact
sets `cache_hit: true`. This follows the documented hierarchy;
see [research and boundaries](RESEARCH.md).

Equal creation instants use **highest numeric ID** as a deterministic local
policy. GitHub does not promise this tie behavior. Fractions and timezone offsets
compare as exact rational instants, without microsecond truncation.

Example result (abbreviated only here):

```json
{"status":"match","selected_cache_id":101,"scope_index":0,"match_class":"primary_exact","restore_index":null,"cache_hit":true,"eligible_count":3,"rejected_counts":{"scope_not_supplied":1,"version_mismatch":1}}
```

Every actual match/miss also includes `coverage`, `inventory_count`, and fixed
`rationale_codes`. Indices are zero based. `eligible_count` counts all records with
a supplied scope and equal version, even if their keys do not match. Rejection
counts partition the remainder: unsupplied scope first, otherwise version mismatch.
A miss uses null ID/indices and `match_class: "none"`. Error output contains only
`status: "error"` and a fixed rationale code; no exception text is printed.

| Exit | Meaning |
| --- | --- |
| 0 | Any selected cache; with `--require-exact`, only primary exact |
| 1 | Miss, or selected fallback with `--require-exact` |
| 2 | Invalid/unsupported input, incomplete export, input I/O, or output failure |

The product reads two local files and writes one JSON line to stdout. It never
executes input, opens a network connection, restores files, writes a cache, or
changes a repository. The boolean `cache_hit` is this model's output; it does not
reproduce the action's string-valued output protocol. No live-service conformance,
cache availability, eviction, permissions, or decompressibility claim is made.

## Supported bounds

Each UTF-8 file: at most 8 MiB; JSON nesting: at most 32 levels (root is level 1);
inventory: at most 10,000 records; restore keys: at most 128; scopes: 1–128.
Keys: 1–512 Unicode characters. Opaque versions/refs: 1–4096 characters.
Strings in these fields reject control, format, surrogate, and line/paragraph
separator characters. No implicit trimming is performed.

IDs must be unique positive JSON integers (booleans and floats rejected).
Duplicate JSON object member names, lone surrogates anywhere, NaN, Infinity, and
overflowing float literals are rejected. Identical cache keys across records are
allowed, since versions/scopes can differ.

Creation times use a bounded RFC3339 profile: four-digit years 0001–9999, actual
calendar dates, `T`/`t`, seconds 00–59, optional exact fractional seconds, and
`Z`/`z` or a valid numeric offset; maximum 128 characters. Leap seconds and
unknown `-00:00` offsets are unsupported and exit 2. UTC offset arithmetic handles
day/year boundaries without datetime overflow. Files cannot be read from stdin.

Verified locally on Windows, Python 3.11.15. Cross-platform verification status
is recorded in [TESTING.md](TESTING.md); local results do not establish hosted CI
or live GitHub cache behavior.

## 中文说明

这是一个离线缓存选择解释器。直接下载源码，用 Python 3.11 或更高版本运行，
无需第三方依赖、令牌或登录。上方命令可以直接试用，不需要额外配置文件。

输入分别是完整库存快照和请求 JSON。请求必须提供已经展开的主键、按顺序排列的
恢复键、版本及已经确认有读取资格的引用范围。程序不会推断分支访问权限、表达式、
归档格式或实际工作流环境。快照需要合并分页；数量不符返回 2。数量一致也无法证明
导出没有遗漏或已经过时。

各范围按输入顺序搜索，范围内依次尝试主键精确、主键前缀、每个恢复键的精确和前缀
匹配。同一候选组选择创建时间最新项。仅主键精确匹配的 `cache_hit` 为 true。
同一时间取最大 ID 是本工具的本地约定，不代表 GitHub 服务保证。

默认选到任意缓存返回 0，完全未匹配返回 1；`--require-exact` 使回退匹配也返回 1。
输入无效、不支持、库存不完整或读写错误返回 2。输出只含缓存 ID、索引、数量和固定
判定代码，不回显主键、版本、引用、命令参数值或输入路径。空库存明确返回未匹配。

每个输入最多 8 MiB、嵌套最多 32 层、库存最多 10,000 项；恢复键和范围最多 128 项，
范围至少 1 项。主键最长 512 字符；版本和引用最长 4096 字符。重复 JSON 字段、重复
缓存 ID、非有限数及孤立代理字符被拒绝。时间字符串最长 128 字符，支持精确小数和
时区偏移；闰秒及未知偏移 `-00:00` 不支持。程序不会联网、启动产品子进程或改写缓存。

本地验证环境是 Windows / Python 3.11.15。测试验证的是这个明确受限的模型，不能
据此断言真实缓存一定可恢复；完整证据和限制见 [TESTING.md](TESTING.md)。
