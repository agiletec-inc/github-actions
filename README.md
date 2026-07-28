# Agiletec GitHub Actions

組織共通のrequired/reusable workflow、composite action、CI/CD policy、Ruleset policy brokerを所有する。
製品固有のdeploy topology、repository inventory、実行中の移行状態はここへ置かない。

reusable workflowは可能な限り不変commit SHAで参照する。

```yaml
jobs:
  quality:
    uses: agiletec-inc/github-actions/.github/workflows/quality-gate.yml@<commit-sha>
```

## Security

- third-party actionは完全なcommit SHAへ固定する。
- default workflow permissionはread-onlyとする。
- docs-onlyでもsecret scanを省略しない。
- changed-pathを比較できない場合はfail closedとする。

変更時は`python -m unittest discover -s tests -v`を実行する。運用判断は
[`policies/ci-cd-trigger-strategy.md`](policies/ci-cd-trigger-strategy.md)、Ruleset pin更新は
[`policy_broker/README.md`](policy_broker/README.md)を必要時に読む。
