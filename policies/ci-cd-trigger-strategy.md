# CI/CD trigger契約

このリポジトリは組織共通のrequired/reusable workflowと、その非弱化ポリシーを所有する。個別製品の
deploy/release契約は各リポジトリが所有し、ここへinventoryや環境別手順を複製しない。

## 品質ゲート

- Organization Rulesetは`.github/workflows/org-quality-gate.yml`をrequired workflowとして参照する。
- required workflowは`pull_request`と`merge_group`で常にstatusを返す。workflow-level path filterを付けない。
- `detect`がmanifest、lockfile、native required workflow、変更範囲から必要なgateを決める。repository名の例外表を作らない。
- native required workflowが同じ責務を所有する場合、generic language/secret/feature-flag jobは重複実行しない。
- 比較SHAを解決できない場合はfail closed。docs-onlyは重いgateだけを省略し、secret scanとaggregateを省略しない。
- private Linux jobは`org-shared-ci-light`、public Linux jobはGitHub Hostedを使う。private Swiftは利用可能な
  self-hosted macOS runnerがない間、generic gateで起動しない。
- final `quality-gate`は選択されたjobのfailure、cancelled、想定外skipを失敗として集約する。

実装契約はworkflow、composite action、`tests/`が正本である。この文書へjob名や対応stack一覧を再掲しない。

## deployとrelease

CI成功はdeployまたはrelease成功を意味しない。deploy trigger、smoke、rollback、kill switchは各製品の
deployment runbookとworkflowが所有する。ユーザー可視化を伴うreleaseは、各製品のrelease契約に従う。

## 変更手順

1. source workflowまたはactionを変更する。
2. `python -m unittest discover -s tests -v`で契約を検証する。
3. consumerを不変SHAへ更新する場合は、対象リポジトリのPRとrequired checksで確認する。
4. Rulesetのworkflow SHA更新は`policy_broker`の署名、CAS、canary、read-back契約を使う。直接弱化しない。
