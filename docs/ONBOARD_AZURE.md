# Onboard an Azure DevOps repo to Crucible

Crucible reviews PRs via a central **extends-template** in the Crucible repo
(`azure-pipelines-crucible.yml`). A new repo onboards by committing one tiny stub — no
agent code, no rules edit. Mirrors the GitHub reusable-workflow pattern.

> Azure floor: these are portal steps until the OAuth-app North Star removes per-repo
> wiring. Org/project context here is `dev.azure.com/rationaletech`, project `Crucible`.

---

## 1. Add the stub pipeline to your repo

Commit `azure-pipelines-crucible.yml` to the repo you want reviewed:

```yaml
trigger: none
pr: none                              # Azure Repos ignores YAML pr triggers — the Branch Policy is the trigger
resources:
  repositories:
    - repository: crucible
      type: git
      name: Crucible/Crucible         # <project>/<repo> holding the template + agent
      ref: refs/tags/v1               # pinned — insulated from in-progress changes
extends:
  template: azure-pipelines-crucible.yml@crucible
  parameters:
    repoName: $(Build.Repository.Name)
```

That's the whole integration. A repo **not** listed in the central `config.yaml` is still
reviewed — with **default (global) rules**. Add a `config.yaml` entry only for custom rules.

## 2. Create the pipeline

Pipelines → **New pipeline** → Azure Repos Git → pick your repo → **Existing Azure Pipelines
YAML file** → select `/azure-pipelines-crucible.yml` (the stub) → Save (don't run).

Authorize the **`crucible-secrets`** variable group for this pipeline the first time it runs
(Pipelines → the pipeline → Edit → it will prompt, or Library → `crucible-secrets` → Pipeline
permissions → add the pipeline). This group holds `ANTHROPIC_API_KEY` — set once, shared by
every onboarded pipeline in the project (the Azure equivalent of an org secret).

## 3. Grant the Build Service "Contribute to pull requests"  ⚠️ the silent-failure gotcha

Project Settings → Repositories → your repo → **Security** → select
**`<Project> Build Service (<org>)`** → set **Contribute to pull requests = Allow**.

> Without this, the agent runs and *appears* to succeed but **posting silently fails** — no
> comments, no error. This is the #1 Azure onboarding gotcha.

## 4. Add the Branch Policy (Build Validation), set OPTIONAL

Project Settings → Repositories → your repo → Branches → the target branch (e.g. `main`) →
**Branch policies** → **Build Validation** → **+** → select the Crucible pipeline →
**Policy requirement: Optional** → Save.

> Azure Repos doesn't honor YAML `pr:` triggers, so this Build Validation policy is what
> actually triggers Crucible on a PR. **Optional** keeps it advisory — it never blocks a
> merge (matches `fail_check_on: none`). Make it Required later only after calibration.

**Done.** Open a PR → Crucible reviews it (default rules unless you added a config entry).

---

## One-time project setup (admin, once per project)
- **Variable group:** Pipelines → Library → **+ Variable group** → name `crucible-secrets` →
  add `ANTHROPIC_API_KEY` (mark it secret) → Save.
- The **Crucible repo** (`Crucible/Crucible`) must hold the agent code + this template, and be
  tagged **`v1`** (the stub pins `refs/tags/v1`). Re-point `v1` for compatible fixes; cut `v2`
  for breaking changes.

## Safety (always on)
- `trigger: none` / `pr: none` — triggered only by the Build Validation policy.
- The agent never builds or executes the PR's code — it reads the diff (secrets redacted
  before the LLM call) and posts comments via the build-service identity.
- Any agent/LLM/REST error → the step still succeeds + a "review unavailable" note (fail-open);
  only a `fail_check_on` finding can fail the check, and the pilot default is `none`.
