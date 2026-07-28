# Feature flag品質gate

organizationの`quality-gate`は全repoでfeature flagを検証する。`.airis/flags.toml`がないrepoはこのcheckをskipして
成功する。flagを宣言するrepoがmetadataとoff/on test commandを所有する。

organization rulesetは`.github/workflows/org-quality-gate.yml`を必須化する。workflowは`pull_request`と
`merge_group`からreusable quality gateを呼び、caller側でpath filterを加えない。対応language manifestがない
repoでもsecret/flag gateは実行し、language固有jobだけをskipする。

```toml
[[flags]]
key = "checkout.v2"
kind = "release"
type = "boolean"
owner = "team:billing"
expires = "2026-12-31"
cleanup_issue = "https://github.com/agiletec-inc/example/issues/123"

[flags.tests.off]
command = "pnpm test:checkout-v2-off"
environment = { CHECKOUT_V2 = "false" }

[flags.tests.on]
command = "pnpm test:checkout-v2-on"
environment = { CHECKOUT_V2 = "true" }
```

`release`と`experiment`は一時flagなのでowner、未来の`expires`、cleanup Issue、off/on testを必須とする。
`ops`、`permission`、`kill_switch`はownerを必須とするが、expiryとtest pairは必須にしない。
