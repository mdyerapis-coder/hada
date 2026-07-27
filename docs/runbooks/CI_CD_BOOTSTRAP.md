# CI/CD Bootstrap Runbook

## Install this patch

Copy the package contents into the repository root on a new branch.

```bash
git switch -c agent/hada-governed-pipeline
cp -a /path/to/HADA_GITHUB_PIPELINE_PATCH/. .
git add .github scripts policies docs tests
bash tests/ci/test_pipeline_scripts.sh
git commit -m "add governed HADA release pipeline"
git push -u origin agent/hada-governed-pipeline
```

Open a draft pull request. Do not merge until `Verify` and `Self-contained E2E` pass.

## GitHub settings

Create environments:

- `staging`
- `production`

For `production`, require manual approval and prevent self-review where the account plan supports it.

Protect `main` with:

- pull requests required
- required status checks: `repository-verification`, `clean-room-e2e`
- conversation resolution required
- force pushes and deletion disabled

## First correction target

The first pipeline-backed release correction must remove the v4 E2E dependency on:

```text
/home/bobthabuilda/hada-deployment/evidence/phase-b0/preflight-run-20260726230557/evidence-sha256.txt
```

Production may retain its authenticated Phase B0 lock, but tests must use a packaged, explicitly test-only fixture that production code rejects.
