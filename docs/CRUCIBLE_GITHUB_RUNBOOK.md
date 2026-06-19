# Crucible — GitHub Runbook (Phase 5)

How to stand up the **private** Golden-PR test repo and verify the GitHub adapter
(T1-16 host swap · T1-17 line-anchoring · T1-18 auth + fail-open). Keep deliberately-buggy
test branches **off** the public source repo; that repo gets at most one smoke-test PR.

---

## A. The two repos

| Repo | Role | Workflow |
|---|---|---|
| `bigastefan/Crucible-AI-Code-Reviewer` (public) | Crucible source | `.github/workflows/crucible.yml` (already committed) — self-review smoke test, code runs in place. |
| `bigastefan/<private-test-repo>` (**private**) | Golden PRs GP-01–10 | the **dual-checkout** workflow below — checks out the test repo's PR *and* Crucible, then runs it. |

Private removes the public-fork-secret risk entirely.

---

## B. Stand up the private test repo

1. **Create it private** and seed a `main` with a few small source files (e.g. a `.ts` and a `.sql`)
   so PRs have something to diff against.
2. **Add the secret:**
   ```bash
   gh secret set ANTHROPIC_API_KEY --repo bigastefan/<private-test-repo>
   # paste the sk-ant-... key when prompted (never commit/echo it)
   ```
3. **Tell Crucible about the repo:** in this source repo's `config.yaml`, uncomment the
   "Crucible Test Repo" block and set `match:` to `bigastefan/<private-test-repo>`
   (language_rules to match the seeded files). Commit + push.
4. **Commit the dual-checkout workflow** (below) to the test repo at `.github/workflows/crucible.yml`.
5. **Make it a required check:** Settings → Branches → branch protection on `main` →
   require the `review` status check. (This is what proves fail-open: a forced error must
   still let the PR merge.)

### Dual-checkout workflow (commit to the PRIVATE test repo)
```yaml
name: Crucible review
on:
  pull_request:                 # NEVER pull_request_target
    types: [opened, synchronize, reopened]
permissions:
  pull-requests: write
  contents: read
concurrency:
  group: crucible-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4          # the test repo (the PR code) → cwd
        with: { fetch-depth: 0 }
      - uses: actions/checkout@v4          # Crucible (the tool) → ./.crucible
        with:
          repository: bigastefan/Crucible-AI-Code-Reviewer
          path: .crucible
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r .crucible/requirements.txt
      - name: Run Crucible
        env:
          GITHUB_TOKEN: ${{ github.token }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python .crucible/crucible.py \
            --config .crucible/config.yaml \
            --pr "${{ github.event.pull_request.number }}" \
            --repo "${{ github.repository }}"
```
`git diff` runs in cwd (the test repo); prompts/rules/config come from `.crucible`. No PR code is
ever installed or executed — only the diff is read.

---

## C. Golden PRs (build once, reuse forever)

| GP | The PR | Expected |
|---|---|---|
| GP-01 | clean change | no findings (or only low); summary "looks good" |
| GP-02 | obvious bug (null deref / off-by-one) | high/critical finding **on the exact line** (T1-17) |
| GP-03 | hardcoded secret | secret redacted from the LLM call + Critical finding |
| GP-04 | SQL via string concatenation | high security finding citing parameterization |
| GP-05 | very large PR (> max_diff_lines) | "too large" notice, no crash |
| GP-06 | only excluded paths | "nothing to review" |
| GP-07 | binary + renamed + deleted together | no crash; comments only on valid changed lines |
| GP-08 | prompt-injection text in a comment | ignored; reviewed normally |
| GP-09 | re-push to an already-reviewed PR | **zero duplicate comments**; summary updated in place |
| GP-10 | forced LLM failure (bad/empty key) | check **passes** (fail-open) + "review unavailable" note |

---

## D. Gate B acceptance
- **T1-16:** GP-01–10 behave the same as Azure; `git log`/diff of the change shows only
  `providers/github.py`, the workflow, `config.yaml`, and `providers/base.py` touched — **no `core/`**.
- **T1-17:** GP-02's comment lands on the exact diff line; an off-diff line is rejected (422).
- **T1-18:** comments post with `GITHUB_TOKEN`; GP-10 (empty/bad `ANTHROPIC_API_KEY`) → PR still
  mergeable despite the required check (exit 0).
