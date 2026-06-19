# CRUCIBLE — PHASE 1 DELIVERY PLAN

**The Agent · Execution & Sign-off Plan — V1**
The delivery view of Phase 1 (the build spec is Agent Spec V4; the gaps + tests are Delivery Assurance V2; this is how it ships).
Owner: Stefan Biga · Pilot: Focus (Azure DevOps) · Also delivering: GitHub adapter

---

## 1. Objective & Definition of Done

**Objective:** ship a trustworthy, multi-provider PR-review agent — it verifies a PR, posts comments, and exits, running in CI — live on the **Focus pilot repo**.

**Phase 1 is DONE when:**
- Reviews PRs on **Azure DevOps**, with the **GitHub adapter built and verified** on a GitHub test repo.
- **De-dupes** across pushes · **fails open** on errors · **redacts secrets** · **ignores injected instructions**.
- **Golden PRs GP-01–10 pass on both** test repos; the **git-host swap** (azure↔github) works with no `core/` change.
- **Calibration signed off by the Tech Lead** (signal:noise is trustworthy).
- Running on the **Focus pilot only** — not org-wide.

---

## 2. Scope

| ✅ In Phase 1 | ❌ Deferred |
|---|---|
| The agent: review → comment → exit, in CI | The dashboard + data layer (Phase 2) |
| Azure DevOps + GitHub (one `GitProvider` adapter) | Org-wide rollout (after the pilot proves out) |
| Dedup · fail-open · secret redaction · injection resistance | Self-serve "add repo + grant access" (North Star) |
| Kill switch · cost guards · dry-run | Slash-command interactivity |
| Calibration + pilot go-live | More git hosts (GitLab/Bitbucket) |

---

## 3. Prerequisites (have these before kickoff)

- [ ] `crucible` monorepo created in Azure DevOps Repos, cloned locally
- [ ] `docs/` populated with all four specs (Agent V4, Admin V4, Masterplan V2, Delivery Assurance V2)
- [ ] **LLM API key** (Anthropic) ready for the CI secret store
- [ ] A **sacrificial Azure test repo** *and* a **sacrificial GitHub test repo** (never live ones)
- [ ] Able to grant the **Build Service "Contribute to PRs"** permission (Azure) and add a **workflow + branch protection** (GitHub)
- [ ] **15–20 historical Focus PRs** identified for calibration (needed Weekend 3)
- [ ] **Tech Lead booked** for the calibration sign-off

---

## 4. Decisions to confirm before we start  ← *your review*

| # | Decision | My recommendation | Your call |
|---|---|---|---|
| **D1** | Starting LLM/model | `anthropic/claude-sonnet-4-6` — best quality/cost for review | |
| **D2** | When to build the GitHub adapter | **Weekend 2** as planned — but it's the flex item: if Weekend 1 overruns, push it to *after* the pilot. It never blocks the Azure pilot. | |
| **D3** | Pilot gate mode | **Start advisory** (`fail_check_on: none`) so Crucible *never blocks a merge* while the team is learning to trust it → flip to block-on-`critical` only **after** calibration sign-off | |
| **D4** | The pilot repo | Which exact Focus repo first — `Focus.Api` or `Focus.Web`? | |
| **D5** | Calibration owner + data | Tech Lead signs off, against the 15–20 historical PRs (D-prereq) | |
| **D6** | Provider order | **Azure first** (matches the pilot), GitHub second — the abstraction makes order cheap | |

> The one I'd flag hardest: **D3**. Shipping in advisory mode for the pilot is the single best trust-protector — a false positive can't block anyone's merge, so the team stays receptive while you calibrate.

---

## 5. Delivery sequence — 3 weekends

> Discipline every session: drop the spec → paste the kickoff → **approve `plan.md` before any code** → build one phase at a time, run the acceptance test, then proceed.

### Weekend 1 — Engine + Azure posting  *(Agent Spec phases 0–3)*
- **Build:** scaffold + config + canonical enums + the `GitProvider` interface; the **diff parser** (+ edge cases); the review engine (dry-run); **posting + dedup + fail-open via the Azure adapter**.
- **Outcome:** Crucible posts real comments + a summary on an **Azure test PR**; a second push posts **no duplicates**; a forced error doesn't block the merge.
- **Acceptance:** GP-01–10 behaviours on the Azure test repo; re-push = zero dupes; forced LLM error = check passes.
- **Watch:** the **diff parser and dedup are the time sinks**. If anything slips, it's here.

### Weekend 2 — CI wiring + GitHub adapter  *(phases 4–5)*
- **Build:** Azure CI pipeline (Branch Policy, Build Service permission, secret variable group) + the **GitHub adapter** (`providers/github.py`) and **Actions workflow** (`on: pull_request`, `GITHUB_TOKEN`).
- **Outcome:** a real PR on Azure *and* on a GitHub test repo both get the same review; flipping `provider:` changes behaviour, not code.
- **Acceptance:** T1-16 (host swap), T1-17 (GitHub line-anchoring), T1-18 (GitHub auth + fail-open).
- **Watch:** GitHub rejects comments not anchored to a real diff line — this re-tests the Weekend-1 parser. *(Flex per D2.)*

### Weekend 3 — Hardening + calibration + pilot  *(phases 6–7)*
- **Build:** secret redaction · kill switch · token caps · retries · logging → then the **calibration gate**.
- **Outcome:** a planted secret never reaches the model; `enabled:false` silences it; Crucible live on **Focus**, quality vouched for.
- **Acceptance:** **Tech Lead signs off** signal:noise on 15–20 historical PRs; pilot enabled in advisory mode.
- **Watch:** calibration is iterative — may span more than one sitting. **No pilot-live and no blocking mode before sign-off.**

---

## 6. Go / No-Go gates

| Gate | When | Pass condition | If it fails |
|---|---|---|---|
| **A — Foundation** | End W1 | Parser + dedup + fail-open solid on an Azure PR | **Stop and fix the parser/dedup.** Don't build on a shaky foundation — everything depends on correct line-anchoring. |
| **B — CI + multi-host** | End W2 | In CI on Azure; GitHub adapter verified *or* consciously deferred (D2) | Deferring GitHub is acceptable; a broken CI trigger is not — fix before W3. |
| **C — Trust** | End W3 | **Tech Lead signs off calibration** | No pilot, no blocking mode, no org-wide rollout. This gate is non-negotiable. |

---

## 7. Phase 1 risk register (build-time)

| Risk | Impact | Mitigation |
|---|---|---|
| Diff parser / wrong-line comments | High | Edge-case unit tests (W1); GitHub re-tests it (W2); Gate A blocks progress until solid |
| Duplicate comments across pushes | High (adoption killer) | Dedup marker + zero-dupe acceptance test (W1) |
| Required check blocks merges on error | High | Fail-open (`on_error: pass`) + **advisory mode for the pilot** (D3) |
| Noisy reviews erode trust | High | Calibration gate + Tech Lead sign-off (Gate C) |
| Secrets / code sent to the LLM | Med | Redaction before the call + provider zero-retention setting |
| GitHub's stricter anchoring | Med | Shared parser must be exact; tested on the GitHub repo (W2) |
| Scope creep — GitHub before pilot value | Med | GitHub is the flex item (D2); protect the Azure→pilot critical path |
| Cost overrun | Low | Per-run cost log + `max_diff_lines/tokens` guards |

---

## 8. Test & acceptance approach

- **Golden PRs (GP-01–10)** built once in *each* test repo (Azure + GitHub) — the reusable regression set (Delivery Assurance V2 §B1).
- Each weekend has explicit acceptance tests (above); run them before moving on.
- **Advisory mode during the pilot** means a wrong review can't block a real merge — the safety net while calibrating.
- These same Golden PRs become the regression gate for every future prompt/rule change.

---

## 9. Effort & assumptions

- **~3 weekends**, assuming Claude Code writes the code while you drive, review, and test.
- Weekend 1 carries the hardest work (parser + dedup); Weekend 3 (calibration) is iterative and may bleed.
- GitHub adds modest time (a second adapter behind a shared interface), and can flex out of the critical path.

---

## 10. Working agreement with Claude Code

- **`plan.md` gate:** Claude Code produces a plan and **stops for your approval before any code**.
- **One phase at a time;** run the acceptance test before the next.
- When reviewing `plan.md`, **pressure-test the diff-parser and dedup phases hardest** — thin detail there is the #1 sign to push back before approving.

---

## 11. Sign-off (before kickoff)

- [ ] Scope (§2) approved
- [ ] Decisions **D1–D6** (§4) locked
- [ ] Prerequisites (§3) met
- [ ] → Kick off **Weekend 1**

---

*This is V1. New content revisions increment: V2, V3, … Vn.*
