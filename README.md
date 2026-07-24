# Agiletec GitHub Actions

Reusable GitHub Actions workflows shared by Agiletec repositories.

This repository contains generic CI implementation only. Organization-specific deployment
topology, runner infrastructure, repository inventory, and internal operating policy are kept in
private governance repositories.

Call reusable workflows by an immutable commit SHA whenever possible:

```yaml
jobs:
  quality:
    uses: agiletec-inc/github-actions/.github/workflows/quality-gate.yml@<commit-sha>
```

## Security

- Third-party actions are pinned to full commit SHAs.
- The default workflow permission is read-only.
- Secret scanning remains mandatory for documentation-only changes.
- Changed-path detection fails closed: an unknown comparison runs the applicable heavy gates.

