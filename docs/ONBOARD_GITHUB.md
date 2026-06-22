# Onboard a GitHub repo to Crucible

Crucible reviews PRs via a **reusable workflow** hosted in this repo
(`.github/workflows/crucible-reusable.yml`). A new repo onboards by dropping one tiny
stub — no agent code, no config edit, no per-repo secret (with an org secret).

---

## 1. Commit the stub workflow

Add `.github/workflows/crucible.yml` to the repo you want reviewed:

```yaml
name: Crucible review
on: pull_request                              # never pull_request_target
permissions:
  pull-requests: write
  contents: read
jobs:
  review:
    uses: bigastefan/Crucible-AI-Code-Reviewer/.github/workflows/crucible-reusable.yml@v1
    secrets: inherit
```

That's the whole integration. It is **pinned to `@v1`**, so in-progress changes to the
agent never affect your repo until you bump the tag.

## 2. Make the API key available

Crucible needs `ANTHROPIC_API_KEY`. `secrets: inherit` forwards it from whatever the repo
can see:

- **Organization (recommended, zero per-repo setup):** set `ANTHROPIC_API_KEY` as an
  **org secret** scoped to selected repos
  (Org → Settings → Secrets and variables → Actions → New organization secret → repository
  access: *Selected repositories*). Then **step 1 is the entire onboarding** — no per-repo
  secret.
- **Personal account / single repo:** set it as a repo secret once:
  ```bash
  gh secret set ANTHROPIC_API_KEY --repo <owner>/<repo>
  ```

> Fork PRs on a **public** repo get no secret (by GitHub design) — Crucible then **fails
> open** (posts "review unavailable", the check still passes). Use a **private** repo to
> avoid that path entirely.

**Done.** Open a PR — Crucible reviews it with the **default (global) rules**.

---

## 3. (Optional) Repo-specific rules

Only if you want rules beyond the global set, add a block to **this repo's** central
`config.yaml` (the caller repo stays a stub):

```yaml
repos:
  - name: "My Service"
    provider: "github"
    match: "<owner>/<repo>"          # == github.repository
    project_rules: "my-service"      # create rules/projects/my-service.md
    language_rules: ["typescript", "sql"]
```

A repo **not** listed here is reviewed with global rules — that's the intended default.

## 4. (Optional) Make the check required

To block merges on Crucible's status, mark the **`Crucible review`** check required in
branch protection (Settings → Branches). Note: branch protection on **private** repos
needs a paid plan (GitHub Pro/Team). The agent runs in **advisory** mode by default
(`fail_check_on: none`) regardless, so this only changes whether the check can block.

---

## Safety (always on)
- Trigger is `on: pull_request` — never `pull_request_target`.
- Least-privilege permissions: `pull-requests: write`, `contents: read`.
- The key is referenced only as a secret; never logged, printed, or echoed.
- The agent never checks out, builds, or executes the PR's code — it only reads the diff
  (secrets redacted before the LLM call) and posts comments.
