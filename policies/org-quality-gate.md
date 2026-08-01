# Organization quality gate契約

Organization Rulesetは`org-quality-gate.yml`を全対象リポジトリへ適用する。入口は常に起動し、実際に必要な
検証はcapability detectionが選ぶ。native required workflowが同じ責務を持つ場合は重複gateを省略するが、
final aggregateは必ず結果を返す。

Rulesetは`org-quality-gate.yml`を不変commit SHAで選択する。入口はconsumer repositoryの文脈で実行されるため、
nested reusable workflowを相対参照せず、`github-actions`のreview済みfull commit SHAを明示する。`@main`などの
可変refを再解決してはならない。source repository以外のPRでもRuleset workflowを起動するため、入口jobには
GitHub公式のtroubleshooting guidanceに従って明示的な`if: true`を置く。

repo名条件、opt-out input、workflow-level path filterを追加しない。例外が必要に見える場合は、まず検出契約か
native gateの所有境界を修正し、`tests/test_native_required_gates.py`と`test_workflow_wiring.py`で固定する。
