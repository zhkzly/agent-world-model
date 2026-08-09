# Agent World Foundry — Direct rewrite

This branch is a clean-break rewrite of the environment-generation product.

The target is:

```text
EnvironmentRequest -> evidence -> executable candidate -> independent Judge
-> Registry EnvironmentPackage -> safe Observe
```

The current D0 commit intentionally contains only an import-safe package shell and a legacy
firewall. It does not implement generation, Observe, Expand, providers, Agents, Runtime, Judge,
package release, or Registry.

The product contract is `docs/agent-world-environment-generation.zh.md`. The execution index is
`docs/direct-rewrite-execution-map.zh.md` once the current task documentation is migrated here.
