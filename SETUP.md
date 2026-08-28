# FakeryData setup and later activation

The source repository and validation workflow need no user-provided secret. GitHub supplies the workflow-scoped `GITHUB_TOKEN`; no token value is stored in repository files.

Publication must remain inactive until an authorized maintainer completes all of these GitHub settings:

1. Protect branch `main`: require pull requests, at least one approval, dismissal of stale approvals, required status check `Validate / data`, conversation resolution, and no force pushes or deletions.
2. Create the GitHub Actions environment named `publication` and configure required reviewers. Do not add an environment secret.
3. Create the repository Actions variable named `FAKERY_DATA_PUBLICATION_ENABLED` with the exact non-secret value `reviewed-main-only`. The workflow intentionally fails while this variable is absent or differs.
4. Review and merge a data change through the protected `main` branch and confirm the `Validate / data` check passed for that exact commit.
5. Only then, as a later explicit release action, manually dispatch `Publish reviewed locale bundle` on `main` and select the registered locale.

Step 3 is configuration, and step 5 is an explicit release command. Neither is performed by repository bootstrap. No user-provided secret is required by any step.

Release tags and asset names are immutable. If the intended tag or release already exists, the publication workflow exits without replacing it.
