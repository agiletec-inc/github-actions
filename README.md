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

## Public repository boundary

このrepositoryは公開repositoryからも同じquality gateを再利用できるようpublicとする。GitHub Actionsでは
public callerからprivate reusable workflowを参照できないため、private化すると公開製品側にworkflowの複製が
必要になり、quality gateの正本が分裂する。

公開するのは汎用workflow、action、検証可能なpolicy contractだけとする。次は置かない。

- credential、token、key、account ID、実ARNなどのsecretまたはsecret locator
- private repository一覧、顧客名、案件固有のdeploy topology
- runnerのhost名、IP address、cluster inventory、障害対応中の状態
- environment固有値や手動運用の認証手順

Rulesetのworkflow pin更新実装はここでversion管理するが、credential値とproviderの実resource値はGitHub/AWS側で
管理する。公開境界を変更する場合は、全callerのvisibilityと参照可否を先に監査する。

## Security

- third-party actionは完全なcommit SHAへ固定する。
- GitHub Actions dependencyはDependabotで更新し、reviewとCIを通す。
- nested reusable workflowは同一repository内の相対参照を使い、Rulesetが選んだcommitを維持する。
- default workflow permissionはread-onlyとする。
- docs-onlyでもsecret scanを省略しない。
- changed-pathを比較できない場合はfail closedとする。

変更時は`python -m unittest discover -s tests -v`を実行する。運用判断は
[`policies/ci-cd-trigger-strategy.md`](policies/ci-cd-trigger-strategy.md)、Ruleset pin更新は
[`policy_broker/README.md`](policy_broker/README.md)を必要時に読む。
