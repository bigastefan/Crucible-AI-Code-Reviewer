# Crucible — Phase 1 Build Plan (The Agent)

**Status:** Awaiting your approval. **No code has been written.**
**Authoritative source:** [CRUCIBLE_AGENT_SPEC.md](docs/CRUCIBLE_AGENT_SPEC.md) (V4, multi-provider).
**Sequenced by:** [CRUCIBLE_PHASE1_DELIVERY_PLAN.md](docs/CRUCIBLE_PHASE1_DELIVERY_PLAN.md) (3 weekends, gates A/B/C).
**Tested against:** [CRUCIBLE_DELIVERY_ASSURANCE.md](docs/CRUCIBLE_DELIVERY_ASSURANCE.md) (GP-01–10, T1-01–18).
**Scope:** Agent Spec §11 **phases 0–7**. Phase 8 (Streamlit admin) is **out** of Phase 1.

> This replaces the previous `plan.md`, which was written against spec **V3** (single-provider): it
> placed the host adapter at `core/azure_client.py` with no `providers/` layer. V4 makes
> provider-agnosticism non-negotiable, so the host code now lives behind `providers/base.py`.

---

## 0. Prerequisites the environment doesn't yet have (please confirm)

| # | Gap on disk | Needed by | Resolution |
|---|---|---|---|
| **E1** | Not a git repository | Phase 1 (`git diff`), and `git`-based diff acquisition everywhere | `git init` (or clone the Azure repo). Until then, Phase 1 tests run against **committed fixture diffs**, which is the right unit-test approach anyway. |
| **E2** | Python is **3.9.6**; spec requires **3.11+** | All phases (uses 3.11 typing, `tomllib`, etc.) | Create a 3.11+ venv before Phase 0. I'll target 3.11 syntax regardless. |
| **E3** | `frontend/` already exists (only a `design/` dir) | — | Phase 2. **Untouched** by this plan. |

---

## 1. Target layout (Agent Spec §5, verbatim)

I'm following **Agent Spec §5** exactly — it's the authoritative doc and it already contains the
`providers/` layer the multi-provider requirement needs. `core/` stays the shared engine that
Phase 2's backend will import; `frontend/` + `docs/` sit alongside untouched. (This differs from
the old plan's `core/`+`agent/` choice — see ambiguity **A1**.)

```
Crucible/
├── crucible.py                   # CLI entrypoint: crucible --pr <id> [--dry-run]
├── config.yaml                   # repo→rules, model, PROVIDER, thresholds, filters
├── requirements.txt              # litellm (PINNED), requests, pyyaml, unidiff
├── pyproject.toml                # console_scripts: crucible -> crucible:main  (so `crucible` works)
├── CHANGELOG-prompts.md          # every prompt/rule change + why
├── azure-pipelines-crucible.yml  # Azure CI runner            (Phase 4)
├── .github/workflows/crucible.yml# GitHub CI runner           (Phase 5)
│
├── core/                         # === provider- & model-NEUTRAL. Names no host, no vendor. ===
│   ├── __init__.py
│   ├── models.py                 # ★ canonical Severity/Category enums (§10, X-01) + Finding/ReviewResult/PRContext
│   ├── config.py                 # load + validate config.yaml (model, review, agent, repos, exclude_paths)
│   ├── diff.py                   # ★ unified-diff parser → files→hunks→right-side line numbers (Phase 1)
│   ├── prompt_builder.py         # stitch system+global+project+language+diff via review.md
│   ├── llm.py                    # ★ ONLY file that calls a model — LiteLLM, vendor from config string
│   ├── reviewer.py               # orchestrate call; validate+coerce JSON to enums; fail-safe on bad JSON
│   ├── dedup.py                  # finding-hash + <!-- crucible:{hash} --> marker (shared by ALL adapters)
│   ├── secrets.py                # secret scan + redaction          (Phase 6)
│   └── logging_setup.py          # structured logging + per-run cost line (Phase 6)
│
├── providers/                    # === the ONLY code that knows a git host ===
│   ├── __init__.py
│   ├── base.py                   # GitProvider Protocol (§8) + factory (provider string → adapter)
│   ├── azure.py                  # Azure DevOps REST adapter        (Phase 3)
│   └── github.py                 # GitHub REST adapter              (Phase 5)
│
├── prompts/  system.md · review.md · summary.md
├── rules/
│   ├── global.md
│   ├── projects/  focus-frontend.md · focus-backend.md
│   └── languages/ csharp.md · typescript.md · angular.md · sql.md
│
├── tests/
│   ├── fixtures/                 # one diff per edge case + an injection fixture + a malformed-JSON fixture
│   ├── test_diff_parser.py       # Phase 1 — the heaviest test file
│   ├── test_config.py            # Phase 0
│   ├── test_models.py            # Phase 0/2 — enum coercion
│   ├── test_dedup.py             # Phase 3 — hash stability + marker round-trip
│   ├── test_reviewer_contract.py # Phase 2 — JSON validate/coerce/fail-safe
│   └── test_secret_redaction.py  # Phase 6
│
├── frontend/   (exists — Phase 2, untouched)   └── docs/   (exists)
```

**Two swappable axes, never touching `core/`:** the **model** is a config string handled only by
`core/llm.py`; the **git host** is an adapter behind `providers/base.py`. `core/` names neither.

---

## 2. Weekend → phase map (Delivery Plan §5) and the gates

| Weekend | Phases | Outcome | Gate |
|---|---|---|---|
| **W1 — Engine + Azure posting** | 0, 1, 2, 3 | Real comments + summary on an **Azure** test PR; re-push = zero dupes; forced error doesn't block merge | **A — Foundation** |
| **W2 — CI + GitHub** | 4, 5 | Azure CI live; GitHub adapter gets the *same* review with no `core/` change (flex per D2) | **B — CI + multi-host** |
| **W3 — Hardening + pilot** | 6, 7 | Secret never reaches model; kill switch; calibrated; live on **Focus only**, advisory | **C — Trust** |

Discipline: **one phase at a time.** Each ends with an exact verify command; I stop and wait for
your "passes" before the next.

---

# WEEKEND 1 — phases 0–3 (→ Gate A)

### Phase 0 — Scaffold + config + content + interfaces
**Files:** full tree §1; `requirements.txt` (litellm **pinned**, requests, pyyaml, unidiff);
`pyproject.toml` (console script); all starter `prompts/` + `rules/` with `version:` headers (§6);
`CHANGELOG-prompts.md`; `crucible.py` (argparse: `--pr`, `--dry-run`, `--config`, `--provider`).
- **`core/models.py`** — the canonical contract, defined **once** (X-01):
  - `Severity = low | medium | high | critical` (with an ordering for gating/filtering).
  - `Category = bug | security | performance | test | maintainability | style`.
  - `Finding`, `ReviewResult` (summary, overall_risk, findings), `PRContext` (repo, pr_id, title,
    target_branch, source_branch, is_draft, head_sha) dataclasses.
- **`core/config.py`** — load + validate `config.yaml`: `model`, `review`, `agent`, `repos[]`
  (incl. per-repo `provider:` + optional `model:`), `exclude_paths`. Repo-match resolution
  (substring/exact on repo name) → project + language rule files + provider. Severity-order helper.
- **`providers/base.py`** — the `GitProvider` Protocol (§8) **+ a `get_provider(name)` factory**. No
  adapter bodies yet (they'd `raise NotImplementedError`).
- ✅ **Accept:** `python crucible.py --pr 123 --dry-run` loads config, resolves the rules **and the
  provider** for a matched repo, prints them. **No API calls.** Plus `pytest tests/test_config.py`.

### Phase 1 — Diff acquisition + parsing  ◀ HIGHEST RISK — detailed in §3
**Files:** `core/diff.py` + `tests/test_diff_parser.py` + `tests/fixtures/*.diff`.
- ✅ **Accept:** `pytest tests/test_diff_parser.py -v` — parser returns correct files and **exact
  right-side line numbers** for a sample diff including a **rename, a deletion, and a binary**
  (GP-07 combo); all edge-case tests pass (T1-01).

### Phase 2 — Review engine (dry-run)
**Files:** `core/prompt_builder.py`, `core/llm.py`, `core/reviewer.py`; finalize `prompts/system.md`
(injection hardening), `prompts/review.md` (`{output_schema}` from `models.py`).
- `prompt_builder.py` assembles `system.md` + global + project + language rules + redacted diff.
  Unmatched file types → **review with global rules only** (gap P1-13, ambiguity A8).
- `llm.py` — LiteLLM `completion()`, model string **from config**, `temperature=0`, never a vendor in
  code. The single choke point for the LLM-agnostic requirement.
- `reviewer.py` — parse the one JSON object (§10); **validate + coerce** severity/category to the
  canonical enums; **fail-safe**: malformed JSON → a `ReviewResult` carrying a single "review couldn't
  be parsed" note, **never** an exception.
- ✅ **Accept:** `crucible --pr <id> --dry-run` prints valid findings JSON for a real diff, posts
  nothing (T1-11); swapping `model:` Claude→Gemini (key set) still yields valid output, **no code
  change**; a diff containing "ignore previous instructions" is reviewed normally (GP-08).

### Phase 3 — Posting + de-dup + fail-open (Azure adapter)  ◀ HIGHEST RISK — detailed in §4
**Files:** `core/dedup.py`, `providers/azure.py`; wire the non-dry-run path in `crucible.py`.
- ✅ **Accept (T1-02/03/04/05, GP-09, GP-10) — this is Gate A:**
  1. First run posts correctly-anchored inline comments + one summary on an **Azure test PR**.
  2. A second push (new commit) posts **zero duplicates** and **updates** the summary in place.
  3. A forced LLM error → the check **passes** with a "review unavailable" note; **merge not blocked**.
  4. `pytest tests/test_dedup.py` (hash stability + marker round-trip, offline).

> **GATE A:** parser + dedup + fail-open must be solid here. If any of the three is shaky, we stop and
> fix before Weekend 2 — GitHub's stricter anchoring (W2) will only punish a weak parser harder.

---

# WEEKEND 2 — phases 4–5 (→ Gate B)

### Phase 4 — Azure CI wiring
**Files:** `azure-pipelines-crucible.yml` (checkout `fetchDepth: 0`, install deps, run crucible,
`env: SYSTEM_ACCESSTOKEN: $(System.AccessToken)`); a README runbook section: the variable group (LLM
key matching the `model:` string), the **Build Validation** branch policy, and the **Project Build
Service → Contribute to PRs** permission (without it, posting silently fails).
- ✅ **Accept:** opening a real Azure PR triggers the pipeline; a review appears within ~2–4 min.

### Phase 5 — GitHub adapter + Actions runner
**Files:** `providers/github.py` (second adapter behind the **same** interface);
`.github/workflows/crucible.yml` (`on: pull_request: [opened, synchronize, reopened]`,
`permissions: { pull-requests: write, contents: read }`, `GITHUB_TOKEN`). **Reuse all of `core/`
unchanged.** GitHub inline comments: `POST .../pulls/{n}/comments` with `path`, `line`, `side:RIGHT`,
`commit_id` (= `head_sha` from PRContext). Summary = a PR review or issue comment. **Same
`<!-- crucible:{hash} -->` dedup marker.**
- ✅ **Accept (T1-16/17/18) — Gate B:** a GitHub test PR gets the same review (anchored comments +
  summary + dedup + fail-open) with **no `core/` change**; GP-02's comment anchors to the exact diff
  line (GitHub rejects off-diff lines — proves the parser); `GITHUB_TOKEN` posts; a forced error on a
  *required* GitHub check still lets the PR merge. Flipping a repo's `provider:` changes behaviour,
  not code.

> **GATE B:** in CI on Azure; GitHub verified *or* consciously deferred (D2 — it's the flex item).
> A broken CI trigger is not acceptable; a deferred GitHub adapter is.

---

# WEEKEND 3 — phases 6–7 (→ Gate C)

### Phase 6 — Hardening & safety
**Files:** `core/secrets.py`, `core/logging_setup.py`; wire into `prompt_builder`/`reviewer`/`crucible.py`.
- **Secret redaction before the LLM call** (raise hits as **Critical** findings) — see ambiguity A7.
- `max_diff_tokens` + `max_diff_lines` "too large to auto-review" notice (GP-05, P1-12).
- **Master kill switch** `agent.enabled: false` → run, post nothing, exit clean (T1-12).
- **Draft-PR skip** `agent.skip_draft_prs` (T1-13). Retry/backoff on transient LLM/REST errors.
- Structured logging + a per-run cost line (T1-14, via `litellm.completion_cost`).
- ✅ **Accept (GP-03/05/06, T1-07/09/12/13):** a planted secret **never appears in the outbound
  request** (asserted in logs) and is flagged Critical; oversized PR → graceful notice; `enabled:
  false` posts nothing; draft PR skipped. `pytest tests/test_secret_redaction.py`.

### Phase 7 — Calibration & pilot (your gate, not a code phase)
**Deliverable:** a short **rollout runbook**. Then *you* run Crucible on **15–20 historical Focus
PRs**; we tune `prompts/` + `rules/` until signal:noise is acceptable.
- ✅ **Accept (T1-15) — Gate C:** Tech Lead signs off review quality; enable on **Focus pilot only**,
  **advisory** (`fail_check_on: none`). No blocking mode, no org-wide rollout before sign-off.

---

## 3. ★ THE DIFF PARSER (Phase 1) — the load-bearing piece

Wrong-line comments are worse than none, and **GitHub rejects any comment not anchored to a real
right-side diff line** — so this parser is what makes both adapters work. Detail per Delivery Plan §10.

### 3.1 Boundary: who does what
- **`providers/*.get_diff()`** produces the *raw unified diff string*. It owns the host-specific bits:
  ref normalization (`refs/heads/main` → `main`), reading `System.PullRequest.TargetBranch`
  (Azure) vs `github.base_ref` (GitHub), ensuring `fetchDepth/fetch-depth: 0`, running
  `git diff origin/<target>...HEAD`.
- **`core/diff.py`** is pure: *string in → structured model out.* It never runs git, never knows a host.
  This keeps the parser identically correct for both adapters (gap X-04).

### 3.2 Output model
```
FileDiff(old_path, new_path, change_type, hunks, is_binary)
  change_type ∈ {added, modified, deleted, renamed, copied, mode_changed}
Hunk(old_start, old_count, new_start, new_count, lines)
DiffLine(kind, content, right_line)   # kind ∈ {context, added, removed}; right_line set only for context/added
```
**Commentable** = `added` lines only (a changed line shows as removed+added; we anchor on the added
side). Context lines carry a right_line for range math but we do **not** anchor comments to them —
matches "only flag lines that actually changed" and stays inside GitHub's strict acceptance window.

### 3.3 Header math (the part that must be exact)
Parse `@@ -a,b +c,d @@`: `a`=old_start, `b`=old_count (**default 1 if omitted**), `c`=new_start,
`d`=new_count (default 1). Walk the body with two cursors initialized to `a` and `c`:
- ` ` (context): `right_line = c`; **c++**, a++.
- `+` (added):   `right_line = c`; **c++**. (commentable)
- `-` (removed):  no right_line; a++.
- `\ No newline at end of file`: metadata — attach to the prior line, **advance nothing**.

### 3.4 Edge cases — each gets a fixture + an explicit assertion
| Case | Detect | Behaviour |
|---|---|---|
| Modify (+/-/context) | hunks present | right-side line numbers exact |
| New file | `new file mode` / `--- /dev/null` | all body lines `added` |
| Deletion | `deleted file mode` / `+++ /dev/null` | **no commentable lines** (no right side) |
| Pure rename | `rename from/to`, no `@@` | record paths, **0 hunks**, no anchors |
| Rename + edit | `rename from/to` + hunks | anchors on new_path |
| **Binary** | `Binary files … differ` / `GIT binary patch` | `is_binary=True`, **skip**, never commentable |
| No-newline-at-EOF | `\ No newline…` | parsed as metadata; line counts stay correct |
| Mode-only change | `old mode`/`new mode`, no hunks | recorded, no anchors |
| Multiple hunks / files | repeated `@@` / `diff --git` | each tracked independently |
| Path with spaces / quoted | git quotes `"a/f x.txt"` | unquote; prefer `---`/`+++` for the authoritative path; strip `a/ b/` |
| Excluded path | matches `exclude_paths` glob | filtered out before the LLM (config-driven) |

### 3.5 Library choice — **hand-rolled, cross-checked against `unidiff`**
`unidiff` is listed as *optional* in §7. Because GitHub anchoring is load-bearing and I want full,
testable control over the right-line math and the no-EOL/rename/binary edges, I recommend a small
hand-rolled parser, with a test that **cross-checks** our line numbers against `unidiff` on the
fixtures (belt-and-suspenders, no behavioral dependency). *If you'd rather lean on `unidiff` as the
primary engine, say so — A2.*

### 3.6 Tests (`test_diff_parser.py`)
One fixture per row above; the headline assertion is always *"comment for file X lands on right-side
line N."* Plus the **GP-07 combined fixture** (binary + rename + deletion in one diff) asserting **no
crash** and **anchors only on valid added lines**.

---

## 4. ★ POSTING + DE-DUP + FAIL-OPEN (Phase 3) — the #1 adoption risk

### 4.1 The `GitProvider` interface (`providers/base.py`, §8)
```python
class GitProvider(Protocol):
    def get_pr_context(self) -> PRContext: ...
    def get_diff(self) -> str: ...
    def existing_finding_hashes(self) -> set[str]: ...
    def post_inline(self, finding: Finding) -> None: ...
    def upsert_summary(self, markdown: str) -> None: ...
    def set_status(self, state: str, note: str) -> None: ...
```
`core/` calls **only** this. The dedup marker + fail-open rule below are shared, not per-adapter.

### 4.2 De-duplication — the design that actually prevents spam
Every comment Crucible posts ends with a hidden HTML marker `<!-- crucible:{hash} -->`. The summary
uses a fixed `<!-- crucible:summary -->`. Marker logic lives in **`core/dedup.py`** so both adapters
share it identically (X-04).

**Hash basis — the single most important decision here.** §8 suggests `file+line+rule`, but I
**recommend against hashing on `line`**: a still-unfixed finding whose line *shifts* after an
unrelated commit (extremely common) would get a new hash and be **re-posted as a duplicate** —
defeating the whole requirement (P1-01/GP-09). Also there is **no `rule` field** in the §10 contract.

> **Recommended hash:** `sha1(file + "|" + category + "|" + normalize(title))` where `normalize`
> lowercases + collapses whitespace. **Stable across line drift.** The line is stored only in the
> marker for *anchoring*, never in the hash. `temperature=0` (Phase 2) keeps titles stable run-to-run;
> the residual risk is LLM title nondeterminism re-posting a finding — accepted + mitigated by
> aggressive normalization. *This is ambiguity A3 — flag if you want `line` in the hash.*

**Flow per run:**
1. `existing = provider.existing_finding_hashes()` — fetch threads, regex out
   `<!-- crucible:([0-9a-f]+) -->`.
2. For each finding compute the hash; **drop if in `existing`** (already posted).
3. Drop below `min_severity_to_post`; sort by severity desc; cap at `max_findings`.
4. `post_inline` each survivor with its marker appended.
5. **Summary:** find the thread containing `<!-- crucible:summary -->`. Exists → **PATCH in place**;
   absent → POST one. Exactly **one** summary thread, ever (P1-09/GP-09).

### 4.3 Azure adapter (`providers/azure.py`) REST specifics (api-version=7.1)
- **Context:** in-pipeline reads `System.*` env; CLI resolves PR id → repo/branches via REST.
- **Auth:** pipeline → `Authorization: Bearer $(System.AccessToken)`; CLI → PAT (Basic
  `:PAT` base64). Adapter picks based on env.
- **List threads:** `GET .../pullRequests/{prId}/threads`.
- **Inline thread:** `POST .../threads` with `threadContext.filePath` (`/`-prefixed, forward slashes),
  `rightFileStart/rightFileEnd: {line, offset:1}`, `comments:[{parentCommentId:0, commentType:1,
  content}]`, `status:"active"`.
- **Summary:** same POST **without** `threadContext`.
- **Edit summary:** `PATCH .../threads/{threadId}/comments/{commentId}` `{content}`.
- I'll confirm exact payload shapes against the live API in Phase 3 (§8 says treat as contract, not
  gospel field-by-field).

### 4.4 FAIL-OPEN — the rule that must never break (§8 CRITICAL, P1-02)
The pipeline is a *required* Build Validation policy; if the step throws, **every merge in the repo is
blocked.** So:
- The **entire** run in `crucible.py` is wrapped top-level. **Any** exception (config, diff, LLM, REST)
  → log it → *best-effort* upsert a "⚠️ Crucible review unavailable" summary (itself try/wrapped so even
  that failing can't crash) → **exit 0**.
- **The only path to a non-zero exit:** a successfully-produced review contains a finding whose
  severity ≥ `fail_check_on` **and** `fail_check_on != "none"`. Per the pilot constraint + D3, the
  default is `fail_check_on: none` → **always exit 0** during the pilot.
- Malformed model JSON is handled in `reviewer.py` (Phase 2), not here — it yields a parse-note review,
  not a crash.

**Gate mechanism — A4 (recommendation):** make the **pipeline step's exit code** the single gate.
It's the simplest thing that satisfies "fail-open with a required check," because even an uncaught
error path returns 0. Treat the Azure `POST .../statuses` call as **optional/cosmetic** (a visible
"Crucible: pass/block" check) and only wire it if you want the verdict surfaced separately — using
both risks double-gating.

### 4.5 Tests
- `test_dedup.py` (offline): same finding with a **shifted line → same hash**; changed title →
  different hash; marker round-trips through extract-regex; summary detection.
- Adapter REST is exercised **manually** on the Azure test PR (GP-09 zero-dupe, GP-10 fail-open) —
  unit tests mock `requests`, no live calls in CI.

---

## 5. Cross-cutting invariants held every phase (§12)
- All model calls go through `core/llm.py` via LiteLLM — never a provider SDK, never a hard-coded vendor.
- All git-host code behind `providers/base.py`; `core/` names no host. Azure first, GitHub second, **no
  `core/` change** between them.
- Prompts/rules live in `prompts/` + `rules/` — never inline in `.py`.
- Incremental: never re-post an existing finding; one summary, edited in place.
- Fail-open: any agent/LLM/REST error → step succeeds + "review unavailable"; only `fail_check_on`
  findings fail the check. **Pilot default `fail_check_on: none`.**
- Diff is untrusted: reviewed as code, never obeyed.
- Secrets redacted before the LLM call; raised as Critical.
- Canonical enums from `core/models.py` — validate + coerce; never invent values.
- Runs end-to-end in `--dry-run`; a malformed model response never crashes the run.

---

## 6. Ambiguities / things I'd do differently — reply "A1 yes, A3 no", etc.
Where I don't hear otherwise I proceed with the **Recommendation**.

- **A1 — Layout (Agent §5 vs the old plan's `core/`+`agent/`).** I'm following **Agent Spec §5**
  (root `crucible.py`, `core/`, `providers/`) because it's the authoritative doc and natively contains
  `providers/`. `core/` is still the shared engine Phase 2 imports, so the Masterplan's "shared core"
  intent is preserved. **Rec: §5.** *Needs ratification — it's expensive to move later.*
- **A2 — Hand-rolled diff parser, cross-checked vs `unidiff`** (§3.5). **Rec: hand-roll** for control
  over GitHub anchoring; keep `unidiff` as a test cross-check only.
- **A3 — Dedup hash basis** (§4.2). **Rec:** `sha1(file|category|normalized_title)`, **no line**, so
  line-drift doesn't re-post. Flag if you want `line` included.
- **A4 — Gate = exit code, not the statuses API** (§4.4). **Rec:** exit code is the single gate;
  statuses call optional/cosmetic.
- **A5 — One LLM call; what is `summary.md`?** §10 returns summary+findings in **one** call, so a
  second summary call is dead weight. **Rec:** single call; repurpose `summary.md` as the **render
  template** for the posted summary comment (formatting), not a second model call. Tell me to drop it
  entirely if you prefer.
- **A6 — Off-pipeline `--pr <id>` diff acquisition** (§13.3). On your laptop nothing is checked out.
  **Rec:** the adapter resolves PR id → source/target branch + repo via REST, then `git diff` locally
  if checked out, else `git fetch` the two refs. In-pipeline it reads `System.PullRequest.*` and skips
  the lookup. CLI `--pr` overrides env; I'll document precedence.
- **A7 — Secret patterns, no new dependency** (§7 caps deps). `detect-secrets` isn't allowed. **Rec:**
  hand-rolled regex set in `core/secrets.py` (AWS keys, PEM blocks, connection strings,
  `password=`/`Bearer ` assignments, high-entropy `KEY=…` lines), patterns listed in the file header
  for easy extension. Flag if you'd rather take the `detect-secrets` dep for coverage.
- **A8 — Unmatched file types (P1-13).** **Rec:** review with **global rules only** (don't skip) —
  global rules cover secrets/TODOs/broad-catch, which apply everywhere. Config toggle to skip can come
  later.
- **A9 — Enum coercion policy.** When the model returns an out-of-set severity/category. **Rec:**
  coerce to a safe default (unknown severity → `medium`, unknown category → `maintainability`) **with a
  log line**, rather than dropping — don't lose a possibly-real finding. Flag if you'd rather drop.
- **A10 — LiteLLM pin** (§7 supply-chain note). I can't verify versions offline. **Rec:** pin the
  latest stable at Phase 0, record the exact version in `requirements.txt` + `CHANGELOG-prompts.md`;
  you verify/bump. I will **never** float `latest`.
- **A11 — D4 (pilot repo `Focus.Api` vs `Focus.Web`)** is unanswered in the delivery plan. Doesn't
  block W1 (test repos only), but I need it before the Phase 7 runbook. Your call.

---

## 7. Explicitly NOT in Phase 1
`backend/`, `core/db.py`, `core/metrics.py`, the `POST /reviews` logging call, any DB, the Angular
dashboard, RBAC/SSO, in-app editing, test-on-sample-PR, the Streamlit admin (Phase 8), GitLab/Bitbucket,
slash-command interactivity, self-serve onboarding (North Star).

---

**Next step:** ratify **A1** (layout) and skim A2–A11, then approve. On approval I build **Phase 0
only** and hand you the verify command. I will not write code until you approve.
