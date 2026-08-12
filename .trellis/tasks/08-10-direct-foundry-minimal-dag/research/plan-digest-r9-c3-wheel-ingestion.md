# Direct R9-C3 plan digest

- Child plan revision: R9-C3 documented offline wheel ingestion
- Five-file aggregate SHA-256:
  `dec00ffe10140fb81258182347f658a0370dfdb5155f8344ed8fbc0b8751e372`
- Current parent plan digest:
  `d39632e88ff13a1b447e490beb379540fe22dcb839690cfdbf6138f114d1efe5`
- Predecessor Direct allow: `cross-layer-review-ca1c588d.md`
- Clean product baseline: `9562c058b61562c11f76d8127f56b68b0f5be2d9`

The five-file digest hashes raw bytes in the declared order, emits standard
newline-terminated `sha256sum` lines, then hashes their exact concatenation:

```text
743b0403360a8732f0554a6cb39379d80745da2e6a319d6dbfc7f45391e90ab7  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
99279bfa4cb038d3fc1db8e8677bdaaabd6d4c3afc6ed115a638ed2397f48121  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
ecf3990c5cca78bd5126ed22794f05f2e036e0c690546f01de3f642622bc11dc  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
ae5de1997f8b8ca72250a8883d9e0d0811c95554fea4e749887a5d16fe3d6bf1  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
8a8d324e833beee78b7cfb9ca6624e15315a6895e228b4eef584c00b06a8509e  docs/direct-rewrite-execution-map.zh.md
```

C3 changes only the trusted-wheel ingestion mechanism. Hash/size-verified
wheels are copied into one empty framework-owned flat directory and supplied
to tested `uv 0.11.29` through the documented fixed
`--no-index --find-links <verified-store>` boundary. uv's separate run-local
cache remains implementation-owned and is never directly modified. Candidate
configuration, ambient indexes, network, source builds and fallback remain
forbidden. This adds no package client, downloader, graph node, configuration
system or compatibility path.

The trigger was a pre-execution static plan contradiction, not a real proof
terminal. Official uv documentation defines `--find-links` as the local
distribution directory and warns that direct cache modification is unsafe.
No Observe scene or Diagnosis Record is applicable.

This record proves planning identity only. It does not authorize
implementation or prove Direct, Repair, Expand, Consumer or product completion.
