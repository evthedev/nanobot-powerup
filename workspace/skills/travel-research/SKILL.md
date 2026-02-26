---
name: travel-research
description: Research travel plans — flights, accommodation, itineraries and screenshots for events, concerts, and trips anywhere in the world.
metadata: {"nanobot":{"always":true}}
---

# Travel Research Skill

## When to activate

**MANDATORY for ANY of the following — even if a draft plan is already provided:**

- Trip planning, flight/hotel/ticket search, itinerary requests
- Attending events (concerts, sports, festivals) in another city or country
- "Plan a trip to X", "get me to Y for Z event", "flights and hotels for [destination]"
- "Complete/update/improve this itinerary/plan/assignment" where content involves travel
- Any message containing: destination + event/activity + dates
- "I want to attend [event] in [city]" — always research even if user provides a draft

**⚠️ A user-provided draft plan does NOT mean research is done. It means they want live, verified data.**

---

## How to execute

### Step 0 — Get the plan (call this FIRST, alone)

```
plan_task(
  mode="plan",
  goal="<paste the full user request including all dates, budget, preferences>",
  task_type="travel_itinerary",
  available_tools="web_search, screenshot_pages, exec, read_file, plan_task"
)
```

**Do not call any other tool in this turn.** Wait for the plan to return, then proceed to Step 1.

### Step 1 — Execute the plan

**Follow the steps returned by `plan_task` exactly.**

The plan specifies which tools to call, with what arguments, in what order.
Execute each step's batch of tools simultaneously. Do not skip or add steps.

### Step 2 — Write a draft response

Using all the data gathered, write a complete draft itinerary that addresses all success criteria.
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

## Hard output rules (always apply, regardless of plan)

- **No generic food/activity descriptions** — every restaurant and activity must be a named place (e.g. "Ichiran Ramen Shinjuku" not "a ramen shop")
- **No placeholders** — banned: "TBD", "pending", "est. — see screenshot", "Next Steps", "prices arriving shortly"
- **Embed screenshots inline** — use the image URLs from `screenshot_pages` results directly in your response
- **Booking.com prices are TOTAL for the stay** — always divide by number of nights and label clearly (e.g. "AUD 22/night (AUD 110 total for 5 nights)")
