---
name: review
description: Aggregate product and service reviews from multiple sources with verbatim quotes and screenshots.
metadata: {"nanobot":{"always":true}}
---

# Review Skill

## When to activate

**MANDATORY for ANY review, recommendation, or trust-assessment request:**

- "Is X worth it?" / "Should I buy/use X?" / "Reviews for X"
- "What do people think of Y?" / "X vs Y — which is better?"
- "Is X trustworthy / legit / reliable?"
- Any product, app, service, company, restaurant, or brand assessment
- "Complete/summarise/update this review" — still requires full research workflow

**⚠️ Never answer review questions directly from training data. Always execute the full workflow.**

---

## How to execute

### Step 0 — Get the plan (call this FIRST, alone)

```
plan_task(
  mode="plan",
  goal="<full user request>",
  task_type="product_review",
  available_tools="web_search, web_fetch, reddit_search, trustpilot_search, screenshot_pages, plan_task"
)
```

**Do not call any other tool in this turn.** Wait for the plan, then execute its steps.

### Step 1 — Execute the plan

**Follow the steps returned by `plan_task` exactly.**

The plan specifies which tools to call with what arguments. Execute each step's
batch of tools simultaneously.

### Step 2 — Write a draft response

Using all the data gathered, write a complete review draft addressing all success criteria.
Do NOT send it yet.

### Step 3 — Evaluate the draft (call this ALONE, before sending)

```
plan_task(
  mode="evaluate",
  criteria_list="<copy the CRITERIA_JSON from the plan output>",
  draft_response="<your full draft>"
)
```

Wait for the evaluation result.

### Step 4 — Retry any failed criteria

If the evaluation returns `verdict: RETRY`, execute EVERY retry tool call it specifies.
Update the draft with the new data. Then proceed to Step 5.

If the evaluation returns `verdict: PASS`, proceed directly to Step 5.

### Step 5 — Send the final response

Send your final, complete response with all criteria satisfied and all screenshots embedded.

---

## Hard output rules (always apply)

- **Lead with verdict** — aggregate summary first, evidence after
- **Quote verbatim with citation** — follow the global Citation Rules in SOUL.md exactly: `>` blockquote + hyperlinked attribution on every quote
- **Flag low scores loudly** — Trustpilot below 2.5 with 100+ reviews gets ⚠️ in verdict
- **No Yelp** — do not use `yelp_search`
- **Embed screenshots inline** — use image URLs from `screenshot_pages` results
- **If a source returns nothing** — say "No results found on [Source] for this query" — don't skip it
