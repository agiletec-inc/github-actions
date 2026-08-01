# Agiletec GitHub Actions

組織共通のCI quality gate、required/reusable workflow、composite action、Ruleset policy brokerを所有する。
製品固有のdeploy topology、repository inventory、実行中の移行状態はここへ置かない。

このrepositoryの中心責務は「GitHub Actionsの部品置き場」ではなく、Organization Rulesetから参照される
品質gateの非弱化契約である。repository固有のnative gateを置換せず、検出して重複実行を避け、常にstableな
required statusを返す。Rulesetそのもののlive設定はGitHubが正本であり、ここではworkflowと安全なpin更新契約を
version管理する。

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
