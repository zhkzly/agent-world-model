# Cross-layer review: curriculum feedback

- Decision: allow
- Plan digest: `77d5ec2da849fea1258dec535cd59b053fd4f6c4454cfad2ea681bae9f509b74`
- Plan revision: 1 (revision count: 1 of at most 2 for this diagnosis lineage)
- Scope: coordinated local Direct Curriculum proposal/validation transaction: the Curriculum compiler diagnostic plus the shared, declaration-driven Direct correction admission rule.  No committed Artifact, edge, package, Registry, or child-path contract changes.

## Product target

Turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe.  This repair advances only the uncommitted Curriculum portion of the Direct Design path; it does not make a node pass, a compiled Curriculum Artifact, or a green test a product-completion claim.

## Trigger and evidence

The diagnosed real Direct Curriculum leaf had passed its first actionable correction frontier and then reached a distinct semantic frontier.  The compiler currently merges the task-family identifier and actor-index validity checks into one parent-path diagnostic (`agent_world/design.py:1702-1714`), so the next correction would not identify the field to repair.  The graph currently permits a second correction only for `tool_semantics` (`agent_world/graph.py:55-61`, `agent_world/graph.py:699-725`), while the canonical rule permits a second correction when code proves strict progress and an allowed second correction exists (`docs/agent-world-environment-generation.zh.md:421-438`; task design `design.md:282-287`).

## Impact chain, ownership, and compatibility

`frozen Architecture + WorldRules + EvidenceGraph -> Curriculum compiler/Feedback -> compiled CurriculumPlan + frozen DifficultySchema -> TaskRequirement/Modeling/Candidate -> independent Judge -> Package/Registry/Observe`.

- The Curriculum compiler remains the sole owner of exact-field validation and accepts the same closed `CurriculumPlanSourceDraft` meaning specified by `node-contracts.md:426-459`; splitting its diagnostics changes neither accepted identifiers nor frozen actor-index semantics.
- `GraphRunner` remains the sole owner of correction authorization, strict no-progress comparison, attempt limits, commit, and terminal behavior.  The proposed declaration of two corrections for `curriculum_plan` is explicit code authority, not model authority; the Direct model receives only the existing safe field correction renderer (`agent_world/design.py:111-137`).
- TaskRequirement and all later Direct consumers remain compatible because they receive only a committed Curriculum Artifact, whose `DifficultySchema` is unchanged.  Expand and Consumer remain compatible and unmodified because they consume exact released parents/packages, not an uncommitted Curriculum proposal.
- Existing ToolSemantics behavior stays bounded by the same generic strict-progress predicates; nodes retaining zero or one declared correction cannot obtain a third proposal.

## Smallest permitted implementation, checks, and proof

1. Split the existing combined Curriculum condition into independent exact-path diagnostics for `task_family_id` and `actor_index`, retaining the present validators and accepted output contract.
2. Set only `curriculum_plan` to two declared local corrections.  Generalize the current ToolSemantics identity checks in `NodeSpec` and `_eligible_local_correction` to an explicitly two-correction Direct LLM declaration, preserving the existing requirements: first and second results are parsed semantic rejections, neither is format-only, the complete `code + path + violated_condition + expected_category` tuple changes, and proposal three is terminal.
3. Replace the ToolSemantics-only tests with declaration-driven coverage, and add Curriculum compiler exact-path checks plus the stated A-to-distinct-B-to-pass, repeat/no-progress, format, and third-failure/no-fourth-call cases.  Retain a regression that ToolSemantics behaves identically and that all undeclared nodes remain capped by their own declaration.
4. Run the focused deterministic tests, then the project quality checks listed in the plan.  For the true-boundary proof, replay only Curriculum using the exact frozen Architecture, WorldRules, and EvidenceGraph parents from the diagnosed leaf.  The sole acceptable proof result is one compiled Curriculum Artifact within three proposals or an honest leaf terminal with no fourth proposal; read Observe immediately.  Only a passed leaf permits a fresh public Direct E2E and its next terminal starts a new diagnosis.

## Non-claims and next permitted gate

This approval does not authorize validation relaxation, prompt/model/route changes, raw proposal persistence, a retry subsystem, changed Artifact ABI, Candidate/Judge/Registry/release work, or Expand/Consumer implementation.  It does not prove TaskRequirement, Candidate, Judge, Registry, E2E, or an EnvironmentPackage.  The next permitted gate is implementation exactly within the approved scope, followed by the frozen-parent leaf proof and Observe; any changed plan digest, trust boundary, or real scene requires a new review.
