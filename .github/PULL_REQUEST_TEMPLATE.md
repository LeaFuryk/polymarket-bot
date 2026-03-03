## Summary

<!-- What does this PR do? 1-3 sentences. -->

## Changes

<!-- List the key changes. Group by category if needed. -->

-

## Delivery checklist

> Every PR must meet these standards before merge. The reviewer (human or bot) will verify each item.

### Code quality
- [ ] New code follows **SOLID principles** (single responsibility, open/closed, Liskov substitution, interface segregation, dependency inversion)
- [ ] Code is **readable** — clear naming, small functions, no clever tricks without comments
- [ ] Code is **documented** — public functions/classes have docstrings; complex logic has inline comments

### Testing
- [ ] New code has **>80% test coverage** (run `uv run pytest --cov` to verify)
- [ ] All new tests pass locally
- [ ] All existing tests still pass (no regressions)
- [ ] CI checks pass (lint + tests)

### Documentation
- [ ] `CHANGELOG.md` is updated under `[Unreleased]` with a summary of changes

## Test plan

<!-- How should a reviewer verify this works? Steps, commands, or screenshots. -->

## Related issues

<!-- Link any related issues: Fixes #123, Relates to #456 -->

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
