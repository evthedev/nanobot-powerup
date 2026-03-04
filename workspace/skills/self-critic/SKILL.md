# Skill: Self-Critic (Evaluation Loop)

## Purpose
Enhance the existing `plan_task(mode="evaluate")` by making it a mandatory system-level middleware for all high-stakes responses (Verbatim requests, financial data, or multi-step research).

## Overlap Merge
- **Existing:** `travel-research` and `review` have manual `evaluate` steps.
- **New Capability:** Automatically intercepts a draft response and runs it against a "Critic" sub-agent using `spawn`.

## Instructions
1. Before sending a final response for a task with specific constraints (e.g., "verbatim"), call `plan_task(mode="evaluate")`.
2. If the verdict is `RETRY`, you MUST execute the suggested tool calls and update the draft.
3. Only send the message once the `PASS` verdict is achieved.

## Verification
- Check for "paraphrasing" vs "verbatim" compliance.
- Check for "Perth/AWST" timezone accuracy.
- Check for "No Placeholders" rule.
