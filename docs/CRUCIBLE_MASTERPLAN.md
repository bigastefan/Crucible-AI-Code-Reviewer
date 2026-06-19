# CRUCIBLE — DELIVERY MASTERPLAN

**Two-Phase Product & Delivery Plan — V2**
The plan you drive your coding weekends from. Sits above the three working docs: Agent Spec (V4), Admin Spec (V4), Delivery Assurance (V2).
Owner: Stefan Biga · Org: Rationale (Azure DevOps + GitHub)
*V2 — Crucible is now **multi-provider** (Azure DevOps + GitHub via a `GitProvider` adapter); self-serve "add a repo + grant access" onboarding added as the **North Star** (a later phase). Phase 1 now includes a GitHub adapter weekend.*

---

## 1. What we're shipping

**Crucible** — a self-hosted, **LLM-agnostic and provider-agnostic** AI code reviewer. It reviews every pull request automatically (comments + summary, posted on the PR) on **Azure DevOps and GitHub**, and reports the value it's creating across all projects on a dashboard. You own every prompt, every rule, the choice of model, and the choice of git host.

**The outcome that matters:** faster, more consistent PR review across 10+ projects without adding a vendor or a headcount — and a credible, measurable story on time saved.

---

## 2. Locked decisions (don't re-litigate mid-build)

| Decision | Choice |
|---|---|
| Where review runs | **CI** — Azure DevOps pipeline *or* GitHub Actions — not a Marketplace plugin, not VS Code |
| Git host | **Provider-agnostic** — Azure DevOps + GitHub behind one `GitProvider` adapter (mirrors the LLM pattern) |
| Model | **LLM-agnostic via LiteLLM** — swap Claude/Gemini/GPT by config + key |
| Agent language | **Python** |
| Dashboard frontend | **Angular** (Angular CLI + ngx-charts) — matches the Rationale stack for dev-team ownership |
| Dashboard backend | **Thin Python/FastAPI + Postgres** — metrics only in the first build |
| Prompt/rule editing | **Git-native** (host web editor) first; in-app editor is deferred (Phase 2b) |
| Repo | **One monorepo** with a shared `core/` (Admin Spec §1 is the canonical layout) |
| Single source of truth | The **git repo** for prompts/rules; the **DB** for metrics only |
| Self-serve onboarding | **North Star** (later phase) — hosted webhook service + GitHub App / Azure OAuth |

**Why the architecture isn't over-built:** a multi-user dashboard of *persisted* metrics needs, at minimum, a UI + a store + a server to serve it. That floor is unavoidable. We removed the *optional* weight — the in-app editor and test-on-sample-PR — into Phase 2b, leaving three lean parts: the agent, a thin API + small DB, and the Angular dashboard.

---

## 3. The two phases at a glance

| | **Phase 1 — The Agent** | **Phase 2 — The Dashboard** |
|---|---|---|
| **Goal** | A reviewer that verifies a PR, comments, and exits — in CI, on Azure **and** GitHub | See review activity + value across all projects |
| **Ships** | Crucible live on the **Focus** pilot repo (+ GitHub-capable) | A deployed dashboard for the whole org |
| **Built from** | Agent Spec **V4** | Admin Spec **V4** (first-build phases 0–4) |
| **Definition of done** | Posts trustworthy, de-duplicated comments on both hosts; fails open; Tech Lead signs off quality on the pilot | Team logs in (SSO/RBAC) and sees real metrics per project + org-wide |
| **Rough effort** | **3 weekends** | **3 weekends** |
| **Explicitly deferred** | Org-wide rollout; self-serve onboarding (North Star) | **Phase 2b:** in-app prompt editor + test-on-sample-PR |

> **Build order is not optional:** Phase 1 ships first. The agent defines the canonical severity/category taxonomy and produces the data the dashboard consumes — so the dashboard has nothing to show until the agent is logging.

---

## 4. The weekend-by-weekend plan

Each session ends with something you can *see working*. Estimates assume Claude Code writes the code while you drive, review, and test. The discipline every session: drop the spec in the repo → paste the kickoff prompt → **approve `plan.md` before any code** → build phase-by-phase, running each acceptance test before moving on.

### PHASE 1 — The Agent

**Weekend 1 — "It reviews an Azure test PR."**
Agent Spec phases 0–3: scaffold + config + canonical enums + the **`GitProvider` interface**; the diff parser (+ edge cases); the review engine (dry-run); posting **with de-duplication and fail-open** via the **Azure adapter**.
🎯 *Demoable:* on a throwaway Azure test PR, Crucible posts real inline comments + a summary; a second push posts **no duplicates**; a forced error doesn't block the merge.
⏱ The diff parser and de-dup are the time sinks — if anything slips, it's these.

**Weekend 2 — "It's wired into CI and works on GitHub too."**
Agent Spec phases 4–5: Azure CI wiring (Branch Policy, Build Service permission, secret variable group) + the **GitHub adapter** (`providers/github.py`) and the **Actions workflow** (`on: pull_request`, `GITHUB_TOKEN`). The GitHub adapter reuses all of `core/` — only the adapter + workflow are new.
🎯 *Demoable:* opening a real PR on Azure *and* on a GitHub test repo both get the same review; flipping a repo's `provider:` changes behaviour, not code.

**Weekend 3 — "It's safe, trustworthy, and live on Focus."**
Agent Spec phases 6–7: hardening (**secret redaction, kill switch, token caps, retries, logging**) + the **calibration gate** — run on 15–20 historical Focus PRs, tune until signal:noise is good, get the **Tech Lead's sign-off**, then enable on the **Focus repo only**.
🎯 *Demoable:* a planted secret never reaches the model; `agent.enabled: false` silences it instantly; Crucible reviewing live PRs on Focus, quality vouched for. ⏱ Calibration is iterative — may run across more than one sitting. **No org-wide rollout until this passes.**

### PHASE 2 — The Dashboard

**Weekend 4 — "The dashboard exists (mock data)."**
Admin Spec phases 0–1: Angular scaffold + design tokens + shell (sidebar, project switcher, nav) + both dashboards (org + project) on mock data, charts via ngx-charts.
🎯 *Demoable:* a clickable dashboard matching your Claude Design prototype. **Milestone: eyeball it against the prototype and fix visuals now.**

**Weekend 5 — "It shows real data."**
Admin Spec phases 2–3: thin FastAPI + Postgres + the review-log schema; **add the agent's logging call** (`POST /reviews`) — the one small addition Phase 2 makes to the Phase-1 agent; wire the dashboards to the live API.
🎯 *Demoable:* the dashboard showing real review data flowing from the Focus pilot.

**Weekend 6 — "It's secured and shipped."**
Admin Spec phase 4: Entra SSO + **RBAC (Viewer/Admin)**; empty/loading/error states; PR deep links; DB backups; deploy internally.
🎯 *Demoable:* the team logs in and views dashboards; Viewers are read-only; it's deployed. **Phase 2 ships here.**

### Later — Phase 2b (only if the git-native editing flow proves clunky)
Separate sessions for the in-app Configuration editor (Admin Spec phase 5) and test-on-sample-PR (phase 6). These re-introduce a git-write path and the review engine into the backend — deferred on purpose.

### North Star — self-serve onboarding (the productization step)
The endgame: an admin **adds a repo and grants access** in the dashboard — no committed CI config. It needs a **hosted webhook service + GitHub App / Azure OAuth**, which reverses Phase 1's "no server" decision (hence: later, not now). The *same* `GitProvider` adapters power it — only the trigger changes from CI to webhooks. This is the path to Crucible being a product, not just internal tooling. Full detail in Agent Spec §14.

---

## 5. Risks & how the plan handles them

| Risk | Mitigation (already in the specs) |
|---|---|
| **Duplicate comments → team mutes it** (the #1 killer) | De-dup is a hard requirement + a Weekend-1 acceptance test |
| **Agent error blocks all merges** | Fail-open (`agent.on_error: pass`) + tested in Weekend 1 |
| **Noisy, low-quality reviews erode trust** | The Weekend-3 calibration gate — no rollout without Tech Lead sign-off |
| **Secrets / code sent to the LLM** | Provider zero-retention setting + secret redaction before the call |
| **Prompt injection via PR content** | System prompt treats the diff as untrusted data; injection fixture in the test set |
| **Dashboard vs agent data drift** | One canonical taxonomy in `core/` — Phase 1 defines it, Phase 2 consumes it |
| **Provider API differences** (esp. GitHub's stricter line-anchoring) | One `GitProvider` interface; the diff parser yields exact right-side lines; each adapter tested on its own test repo |
| **"Time saved" mistaken for exact ROI** | Labeled *estimated* in the UI with visible assumptions |

The full gap list + the Golden-PR regression set live in **Delivery Assurance (V2)** — use it to verify each phase.

---

## 6. Success metrics

**Value (the ROI story — track day-1 / day-30 / day-90):**
- PRs reviewed; issues caught (by severity); estimated time saved (hrs); API cost vs estimated value.

**Quality (the metric that decides rollout):**
- Signal:noise — % of comments the team finds useful. Target a level the Tech Lead will vouch for before going past the pilot.

**Adoption (the leading indicator of health):**
- The team leaves Crucible *on* and engages with its comments — the truest sign it's earning its place.

---

## 7. Artifact map

| Doc | Role | Version |
|---|---|---|
| **This Masterplan** | PM-level plan + weekend sequence | V2 |
| **Agent Spec** | How to build Phase 1 (the reviewer, multi-provider) | V4 |
| **Admin Spec** | How to build Phase 2 (the dashboard) | V4 |
| **Delivery Assurance** | Gap analysis + QA test plan + Golden PRs | V2 |

**Where to start this weekend:** set up the monorepo, drop the Agent Spec in `docs/`, paste its kickoff prompt to Claude Code, approve `plan.md`, and begin Weekend 1.

---

*This is V2. New content revisions increment: V3, V4, … Vn.*
