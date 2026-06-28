# Goal 10: Packaged Generated Runtime Consumer

本文记录第十条修正：Goal 07-09 已经能生成并验证 `GeneratedEnvironmentBundle`，但用户指出“之后的环节是否可以调用”仍不清楚。问题在于之前 release 只引用 build workdir，后续 rollout/training/online consumer 缺少稳定 package 内入口。

## 目标

把 verified generated bundle 从临时 build/workspace 复制到 release package 内，并提供一个最小通用 consumer：

```text
envpkg/
  release/
    release-manifest.yaml
    generated-runtime-index.yaml
  runtime/
    generated/<bundle_id>/
      runtime.py
      seed_state.json
      verifier.py
      surface_descriptor.json
      check_replay.py
      build_manifest.yaml
  checks/
    generated-bundle-package-check.yaml
```

后续模块不应再依赖 `/tmp/.../agent-runs/.../generated` 这种临时路径，而应读取：

```text
envpkg/release/generated-runtime-index.yaml
```

## 已实现范围

- `PipelineRunner` 在成功完成 S11 后，如果存在 accepted `GeneratedEnvironmentBundle` 且提供了 `output_dir`，会自动写 `output_dir/envpkg`。
- package 内 generated files 保留 exact sha256 校验。
- package 写出 `release/generated-runtime-index.yaml`，记录 runtime dir、entrypoints、generated files、check/replay commands 和 consumer contract。
- 新增 `run_packaged_generated_bundle_check(package_dir)`，可从 package 内 runtime 执行 `check_replay.py`，验证正例和负例。Goal 11 之后，该 consumer 对 `project-board-lite` 还会运行框架侧 independent verifier，直接加载 package 内 runtime/verifier/seed 并覆盖所有 accepted tasks，不能只信任 generated check stdout。
- deterministic generated bundle 和 code-agent runner generated bundle 都覆盖测试。

## 仍不做

- 不实现真实 trainer loop。
- 不接入 Ray/vLLM/SGLang/GPU。
- 不把 support-desk 的 rollout/training consumer 泛化成所有环境。
- 不实现 MCP/HTTP/environment CLI 的通用发布。

## 下一步

下一步应基于 `generated-runtime-index.yaml` 做通用 rollout/online adapter：

- 读取 package runtime index。
- import runtime/verifier entrypoints。
- 根据 `TaskSet` 执行 policy 或外部 agent action。
- 产出 rollout/reward records。
- 再由 verl/LLaMA-Factory/OpenRLHF/TRL 等训练框架作为外部 consumer 消费。
