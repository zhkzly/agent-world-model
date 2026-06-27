# Agent World, Harness Engineering, and Loop Engineering

Boundary: this note is research background, not the repository implementation plan. The current task source is `docs/agent-world-environment-generation.zh.md`. AWM is useful evidence and example material, but it is not the target architecture or default schema.

## Bottom line
“Agent world” is not just environment modeling.

It is a stack:
1. environment synthesis
2. tool and database interface design
3. verification and reward design
4. training and evaluation loops
5. continual task expansion and diagnostics

## Paper 1: Agent World Model
`2602.10090` is best read as an environment-generation and training-infrastructure paper.

Key points:
- It synthesizes 1,000 executable, SQL-backed tool-use environments.
- It uses a pipeline that goes from scenario generation to task generation, database construction, tool spec generation, environment code generation, and verifier generation.
- It exposes environments through MCP, which makes the environments usable by tool-using agents.
- It is not only “world modeling”; it also includes reward design and RL training on top of the environments.

Interpretation:
- The world model is the substrate.
- The real contribution is the full agent-training system around that substrate.

## Paper 2: Agent-World
`2604.18292` pushes the idea further.

Key points:
- It discovers real-world environment themes and then synthesizes executable environments and verifiable tasks.
- It couples environment synthesis with continuous self-evolving training.
- It is explicitly a co-evolution loop between agent policy and environment/task generation.

Interpretation:
- This is closer to a general agent training arena than a pure environment model.
- Environment modeling is only one stage inside a larger self-improvement system.

## Harness engineering
Harness engineering is the work of building the runtime substrate around the model.

What it usually includes:
- prompt and context assembly
- tool routing and function dispatch
- memory and state handling
- sandboxing and permission boundaries
- logging, replay, and observability
- retries, validators, and evaluators

Why it matters:
- A good model with a bad harness is still a weak agent.
- For agentic systems, the harness often determines reliability more than the model alone.

## Loop engineering
Loop engineering is the work of designing the agent control loop itself.

What it usually includes:
- the plan-act-observe cycle
- branching and recovery paths
- checkpoints and retries
- decomposition into subloops or subagents
- termination conditions and budget control

Why it matters:
- Many agent failures are loop failures, not model failures.
- A linear loop is often too crude; structured graphs can be a better execution model.

## Relation to agent world
If you want to think about the stack cleanly:

- Environment modeling answers: what world does the agent act in?
- Harness engineering answers: what runtime makes that world usable?
- Loop engineering answers: how does the agent repeatedly act, observe, recover, and finish?

My take:
- “Agent world” is a system problem, not only a world-modeling problem.
- The strongest work in this area combines all three layers.

## References
- AWM: https://arxiv.org/abs/2602.10090
- Agent-World: https://arxiv.org/abs/2604.18292
- Harness engineering: https://arxiv.org/abs/2604.25850
- Loop engineering: https://arxiv.org/abs/2604.11378

## Expanded reading list

### Environment synthesis and task generation

- `2512.22857` AutoForge: Automated Environment Synthesis for Agentic Reinforcement Learning. Good for comparing automation level against AWM.
- `2512.01311` CuES: A Curiosity-driven and Environment-grounded Synthesis Framework for Agentic RL. Useful for the "how do we generate tasks when none are given?" problem.
- `2603.06739` ResearchEnvBench: Benchmarking Agents on Environment Synthesis for Research Code Execution. Good for judging whether synthesized environments are actually executable and useful.
- `2605.18703` EnvFactory: Scaling Tool-Use Agents via Executable Environments Synthesis and Robust RL. Strong evidence that environment synthesis is becoming a family of methods, not a one-off idea.

### Harness engineering

- `2605.12239` Harness Engineering as Categorical Architecture. A formalization of harness design as an architecture problem.
- `2605.13357` AI Harness Engineering: A Runtime Substrate for Foundation-Model Software Agents. Treats the harness as the runtime substrate around the model.
- `2606.10106` What makes a harness a harness: necessary and sufficient conditions for an agent harness. Helpful for pinning down the concept before overusing it.
- `2606.11926` Toward Generalist Autonomous Research via Hypothesis-Tree Refinement. An autonomous research system that explicitly combines model training, harness engineering, and data synthesis.

### Loop engineering and execution graphs

- `2604.14228` Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems. Shows that a lot of the system is a while-loop plus surrounding infrastructure.
- `2604.11378` From Agent Loops to Structured Graphs: A Scheduler-Theoretic Framework for LLM Agent Execution. Argues for moving beyond a linear loop into explicit graphs.
- `2605.06365` From Agent Loops to Deterministic Graphs: Execution Lineage for Reproducible AI-Native Work. Pushes the same idea toward reproducibility and control.

### Autonomous research and long-horizon agents

- `2506.11425` Agent-RLVR: Training Software Engineering Agents via Guidance and Environment Rewards. Good for understanding reward shaping in long-running agent loops.
- `2605.02092` NORA: A Harness-Engineered Autonomous Research Agent for End-to-End Spatial Data Science. Useful for thinking about long-running loops, tool use, and experiment orchestration.
- `2606.11926` Arbor: Toward Generalist Autonomous Research via Hypothesis-Tree Refinement. Relevant if you want to study autonomous research loops rather than just coding agents.

## What this means

If you compress the whole literature into one sentence, the direction is moving from:

`environment modeling` -> `executable environment synthesis` -> `task synthesis + verification` -> `harness design` -> `loop design` -> `self-evolving agent systems`

So the short answer to your intuition is:

- `agent world` is not just environment modeling.
- Environment modeling is only one layer.
- The real research problem is the full system around it: tasks, verifiers, harness, loops, and continuous improvement.
