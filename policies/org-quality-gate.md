# Organization quality gate契約

Organization Rulesetは`org-quality-gate.yml`を全対象リポジトリへ適用する。入口は常に起動し、実際に必要な
検証はcapability detectionが選ぶ。native required workflowが同じ責務を持つ場合は重複gateを省略するが、
final aggregateは必ず結果を返す。

repo名条件、opt-out input、workflow-level path filterを追加しない。例外が必要に見える場合は、まず検出契約か
native gateの所有境界を修正し、`tests/test_native_required_gates.py`と`test_workflow_wiring.py`で固定する。
