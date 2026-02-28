# Available Tools

This document describes the tools available to nanobot.

## File Operations

### read_file
Read the contents of a file.
```
read_file(path: str) -> str
```

### write_file
Write content to a file (creates parent directories if needed).
```
write_file(path: str, content: str) -> str
```

### edit_file
Edit a file by replacing specific text.
```
edit_file(path: str, old_text: str, new_text: str) -> str
```

### list_dir
List contents of a directory.
```
list_dir(path: str) -> str
```

## Shell Execution

### exec
Execute a shell command and return output.
```
exec(command: str, working_dir: str = None) -> str
```

**Safety Notes:**
- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- Optional `restrictToWorkspace` config to limit paths

## Web Access

### web_search
Search the web using Brave Search API.
```
web_search(query: str, count: int = 5) -> str
```

Returns search results with titles, URLs, and snippets. Requires `tools.web.search.apiKey` in config.

### web_fetch
Fetch and extract main content from a URL.
```
web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str
```

**Notes:**
- Content is extracted using readability
- Supports markdown or plain text extraction
- Output is truncated at 50,000 characters by default

## Communication

### message
Send a message to the user (used internally).
```
message(content: str, channel: str = None, chat_id: str = None) -> str
```

## Background Tasks

### spawn
Spawn a subagent to handle a task in the background.
```
spawn(task: str, label: str = None) -> str
```

Use for complex or time-consuming tasks that can run independently. The subagent will complete the task and report back when done.

## Scheduled Reminders (Cron)

Use the `exec` tool to create scheduled reminders with `nanobot cron add`:

### Set a recurring reminder
```bash
# Every day at 9am
nanobot cron add --name "morning" --message "Good morning! ☀️" --cron "0 9 * * *"

# Every 2 hours
nanobot cron add --name "water" --message "Drink water! 💧" --every 7200
```

### Set a one-time reminder
```bash
# At a specific time (ISO format)
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"
```

### Manage reminders
```bash
nanobot cron list              # List all jobs
nanobot cron remove <job_id>   # Remove a job
```

## Heartbeat Task Management

The `HEARTBEAT.md` file in the workspace is checked every 30 minutes.
Use file operations to manage periodic tasks:

### Add a heartbeat task
```python
# Append a new task
edit_file(
    path="HEARTBEAT.md",
    old_text="## Example Tasks",
    new_text="- [ ] New periodic task here\n\n## Example Tasks"
)
```

### Remove a heartbeat task
```python
# Remove a specific task
edit_file(
    path="HEARTBEAT.md",
    old_text="- [ ] Task to remove\n",
    new_text=""
)
```

### Rewrite all tasks
```python
# Replace the entire file
write_file(
    path="HEARTBEAT.md",
    content="# Heartbeat Tasks\n\n- [ ] Task 1\n- [ ] Task 2\n"
)
```

---

## reddit_search
Search Reddit posts using the public Reddit JSON API (no API key needed).
```
reddit_search(query: str, subreddit: str = None, sort: str = "relevance",
              time: str = "all", limit: int = 10) -> str
```

**Parameters:**
- `query` — search terms
- `subreddit` — restrict to a subreddit (e.g. "sydney", "personalfinance")
- `sort` — relevance | hot | new | top | comments
- `time` — hour | day | week | month | year | all (used with top/relevance)
- `limit` — 1–25 results

Returns post titles, scores, comment counts, subreddit, permalinks, and body snippets.

---

## trustpilot_search
Search Trustpilot for businesses and optionally pull recent reviews (no API key needed).
```
trustpilot_search(query: str, include_reviews: bool = False,
                  review_count: int = 5, limit: int = 5) -> str
```

**Parameters:**
- `query` — business name or domain (e.g. "airbnb" or "airbnb.com")
- `include_reviews` — if true, also fetch recent English reviews for top result
- `review_count` — how many reviews (1–10)
- `limit` — number of business results (1–10)

Returns trust scores, review counts, categories, and review text/ratings.

---

## yelp_search
Search for local businesses via the Yelp Fusion API. Requires a Yelp API key.
```
yelp_search(term: str, location: str = None, latitude: float = None,
            longitude: float = None, categories: str = None,
            sort_by: str = "best_match", price: str = None,
            open_now: bool = False, radius: int = 5000, limit: int = 10) -> str
```

**Parameters:**
- `term` — what to search for (e.g. "sushi", "plumber", "yoga studio")
- `location` — city or address (e.g. "Sydney NSW", "Surry Hills 2010")
- `latitude` / `longitude` — alternative to `location`
- `categories` — Yelp category filter (e.g. "restaurants", "bars")
- `sort_by` — best_match | rating | review_count | distance
- `price` — "1"–"4" for $–$$$$ (comma-separated for multiple)
- `open_now` — only show currently open businesses
- `radius` — search radius in metres (max 40,000)
- `limit` — 1–20 results

Returns ratings, review counts, price tier, address, opening status, and Yelp URL.

**Setup:** Add your Yelp API key to `~/.nanobot/config.json`:
```json
"tools": { "yelp": { "api_key": "YOUR_KEY_HERE" } }
```
Get a free key at https://docs.developer.yelp.com/docs/fusion-intro

---

---

## review_screenshots
Capture browser screenshots of a product's Reddit discussion, Trustpilot page, and top editorial review, then post all three as inline images. Call this **before** writing the review text (it spawns a background subagent).
```
review_screenshots(
  company_slug: str,    # e.g. "notion", "monday-com", "linear-app"
  reddit_url: str,      # top Reddit post permalink, or https://www.reddit.com/search/?q=<company>+review
  trustpilot_url: str,  # e.g. "https://www.trustpilot.com/review/notion.so"
  editorial_url: str    # top editorial review URL from web_search results
) -> str
```

Used exclusively during the **review workflow** (Step 4). Do not call `spawn` manually for screenshots — use this tool instead.

---

## travel_screenshots
Capture browser screenshots of travel research pages (flights, hotels, event info) and post them as inline images. Call this **before** writing the itinerary text (spawns a background subagent).
```
travel_screenshots(
  trip_slug: str,     # e.g. "bts-busan-jun26", "paris-trip", "tokyo-2026"
  flights_url: str,   # e.g. "https://www.skyscanner.com.au/routes/syd/pus/"
  hotels_url: str,    # e.g. "https://www.booking.com/searchresults.en-gb.html?ss=Busan"
  event_url: str      # top event/venue URL from research (Weverse, Ticketmaster, etc.)
) -> str
```

Used exclusively during the **travel-research workflow** (Step 4). Do not call `spawn` manually for screenshots — use this tool instead.

---

## screenshot_pages

Navigates to URLs using a real browser, captures screenshots, and returns text content + image URLs. Use this for any visual proof that a fact came from a real source.

```
screenshot_pages(
  slug: str,    # Lowercase hyphenated identifier, e.g. "hooters-la-menu", "coldplay-tokyo"
  pages: list   # Up to 5 pages. Each: {"url": str, "label": str, "wait_seconds": int (default 4)}
) -> str
```

**Two screenshot types:**
- **TYPE A** (prices/availability): DuckDuckGo or Booking.com search results — price cards appear inline. Use for flights, hotels, ticket prices.
- **TYPE B** (factual claims): The ACTUAL SOURCE PAGE — Wikipedia, TripAdvisor, official site, Reddit thread. A search results page does NOT verify a claim about a place or product.

**Reading the output:**
- Lines marked `✅ USABLE` contain valid image URLs — embed these in your response as `![Label](url)`
- Lines marked `❌ FAILED` — the file was not saved, do NOT embed these
- Each page also returns extracted page text for you to summarise

**Rules:**
- Max 5 pages per call. Split into multiple calls with different slugs if needed.
- Never use google.com — it serves a CAPTCHA to headless browsers (auto-redirected to DuckDuckGo)
- Never use DuckDuckGo/Bing for factual claims — use the actual source page

**Do NOT use `spawn` for screenshots** — spawn subagents are async and their messages arrive after your response is sent, so the image never appears inline. `screenshot_pages` is synchronous.

---

## Adding Custom Tools

To add custom tools:
1. Create a class that extends `Tool` in `nanobot/agent/tools/`
2. Implement `name`, `description`, `parameters`, and `execute`
3. Register it in `AgentLoop._register_default_tools()`
