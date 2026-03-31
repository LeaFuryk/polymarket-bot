# Code Logic + AI Results Improvement Plan

## Goals
- Reduce AI latency by shrinking prompt size and removing duplicate rules.
- Improve decision quality by aligning model context with deterministic code logic.
- Make AI outputs easier to evaluate and iterate on with structured metrics.

## Scope
- Decision pipeline: AI prompts, screening, guards, and sizing.
- Feedback/knowledge context and reflection outputs.
- Documentation for Claude prompt/skill behavior.

## Constraints
- Keep deterministic rules in code, not in prompts.
- Preserve current risk checks and guard chain ordering.
- Avoid behavior regressions in live vs paper trading modes.

## Phase 0: Baseline + Instrumentation (1-2 days)
- Log prompt size, token usage, latency per call (screen + main).
- Log which guards modified decisions and what fields changed.
- Track screening pass rate and downstream trade rate.

Deliverables:
- Metrics in logs and dashboard fields for latency/token counts.
- Guard-change telemetry for analysis.

Targets:
- P50 latency < 5s (main call).
- Input tokens < 600 for main decision.

## Phase 1: Deterministic Rules -> Code (2-4 days)
- Move hard rules out of prompts and enforce in prefilter/guards.
- Centralize order_type policy (paper vs live) in code, not prompt.
- Ensure guard functions preserve decision fields (limit_price, ttl_seconds, hypothetical_direction, confidence_drivers).

Deliverables:
- Updated guards to preserve metadata.
- Reduced prompt text (remove rules that are already enforced).

## Phase 2: Prompt Compaction + Structured Context (3-5 days)
- Replace prose tables with compact JSON-like snapshots.
- Shorten system prompt to a glossary + decision framing.
- Slim screening prompt and inputs (no long indicators block).
- Pass velocity conflict details into prompt (severity/direction/rate).

Deliverables:
- New compact system prompt.
- New user context builder with structured fields.
- Updated screening prompt and context.

## Phase 3: Feedback Context Improvements (2-4 days)
- Limit feedback context to top-N active observations + short session summary.
- Ensure reflections are descriptive and not rewritten into hard rules.
- Include opposite-side price/RR in context to avoid expensive-side entries.

Deliverables:
- Trimmed feedback context generation.
- Clear separation between hard rules (code) and soft hints (prompt).

## Phase 4: Evaluation + Iteration (ongoing)
- Create offline replay/analysis using existing trade + resolution logs.
- Compare old vs new prompts on win rate, PnL, and wrong-side frequency.

Deliverables:
- Lightweight analysis script or notebook.
- A/B comparison report per iteration.

## Documentation
- Create /docs/skills/claude.md:
  - Prompt structure and schemas
  - Deterministic rule ownership (what code enforces)
  - Model selection, temperature, max tokens
  - Logging + evaluation expectations

## Risks / Mitigations
- Prompt changes can shift behavior unpredictably:
  - Mitigation: phased rollout + replay evaluation first.
- Guard changes could unintentionally drop metadata:
  - Mitigation: add unit tests for decision field preservation.
- Live vs paper mode divergence:
  - Mitigation: centralize order_type policy and log mode-specific decisions.

## Acceptance Criteria
- Prompt size reduced by >60%.
- Latency reduced to <5s (P50) for main decision.
- No regression in win rate or adverse selection rate.
- Clear documentation and reproducible evaluation reports.
