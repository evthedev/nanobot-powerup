# Reddit API Access Skill

Access Reddit programmatically using [PRAW](https://praw.readthedocs.io/) (Python Reddit API Wrapper).
Fetch posts, comments, user info, and subreddit data — all from the command line or from Python code.

---

## Files

| File | Purpose |
|---|---|
| `reddit_helper.py` | Main CLI helper script |
| `credentials.env.example` | Template for API credentials |
| `credentials.env` | Your actual credentials (**do not commit**) |
| `SKILL.md` | This file |

---

## Installation

### 1. Install PRAW

```bash
/opt/anaconda3/bin/pip install praw
```

Requires Python 3.8+. PRAW version ≥ 7.8 is recommended.

### 2. Create a Reddit App

1. Log in to Reddit and go to **https://www.reddit.com/prefs/apps**
2. Scroll to the bottom and click **"create another app…"**
3. Fill in:
   - **Name**: anything descriptive (e.g. `nanobot-script`)
   - **Type**: ✅ **script** ← important
   - **Redirect URI**: `http://localhost:8080` (required field, unused for scripts)
4. Click **"create app"**
5. Note down:
   - **client_id** — shown in small text directly under the app name
   - **client_secret** — shown next to the "secret" label

### 3. Configure Credentials

```bash
cd ~/.nanobot/workspace/skills/reddit-api-access
cp credentials.env.example credentials.env
# Edit credentials.env and fill in your values
```

**credentials.env format:**
```env
REDDIT_CLIENT_ID=abc123XYZ
REDDIT_CLIENT_SECRET=supersecretvalue
REDDIT_USER_AGENT=nanobot-reddit-skill/1.0 by u/your_reddit_username

# Optional — only needed for posting/voting
# REDDIT_USERNAME=your_username
# REDDIT_PASSWORD=your_password
```

Alternatively, export environment variables:
```bash
export REDDIT_CLIENT_ID=abc123XYZ
export REDDIT_CLIENT_SECRET=supersecretvalue
export REDDIT_USER_AGENT="nanobot-reddit-skill/1.0 by u/yourname"
```

---

## CLI Usage

All commands use:
```
/opt/anaconda3/bin/python ~/.nanobot/workspace/skills/reddit-api-access/reddit_helper.py <command> [options]
```

### Commands

#### `hot` — Hot posts from a subreddit
```bash
python reddit_helper.py hot --subreddit python --limit 5
python reddit_helper.py hot -s worldnews -n 10
```

#### `top` — Top posts by time period
```bash
python reddit_helper.py top --subreddit technology --limit 5 --time week
python reddit_helper.py top -s science -n 10 --time month
# time options: hour | day | week | month | year | all
```

#### `new` — Newest posts
```bash
python reddit_helper.py new --subreddit MachineLearning --limit 5
```

#### `search` — Search within a subreddit
```bash
python reddit_helper.py search --subreddit technology --query "artificial intelligence" --limit 5
python reddit_helper.py search -s python -q "asyncio" --sort top
# sort options: relevance | hot | top | new | comments
```

#### `comments` — Comments on a specific post
```bash
# Post ID is the alphanumeric code in the Reddit URL
# e.g. https://reddit.com/r/python/comments/1abc23/... → ID is 1abc23
python reddit_helper.py comments --post-id 1abc23 --limit 10
```

#### `user` — Public profile info
```bash
python reddit_helper.py user --username spez
```

#### `info` — Subreddit metadata
```bash
python reddit_helper.py info --subreddit Python
```

#### `json` — Output as JSON (for piping/scripting)
```bash
python reddit_helper.py json --subreddit Python --limit 5
python reddit_helper.py json -s worldnews -n 20 | jq '.[].title'
```

---

## Python API Usage

Use `reddit_helper.py` as a module, or use PRAW directly:

### Read-only (no login required)
```python
import praw

reddit = praw.Reddit(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    user_agent="my-script/1.0 by u/your_username",
)

# Fetch hot posts
for post in reddit.subreddit("python").hot(limit=5):
    print(post.title, post.score)

# Search
for post in reddit.subreddit("technology").search("AI", limit=5):
    print(post.title)

# Get comments
submission = reddit.submission(id="1abc23")
submission.comments.replace_more(limit=0)
for comment in submission.comments[:5]:
    print(comment.author, comment.body[:100])

# Subreddit info
sub = reddit.subreddit("Python")
print(sub.title, sub.subscribers)
```

### Authenticated (posting, voting — requires username + password)
```python
reddit = praw.Reddit(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    user_agent="my-script/1.0 by u/your_username",
    username="your_username",
    password="your_password",
)

# Submit a text post
reddit.subreddit("test").submit("My Title", selftext="Hello world!")

# Submit a link post
reddit.subreddit("test").submit("My Link Post", url="https://example.com")

# Comment on a post
submission = reddit.submission(id="1abc23")
submission.reply("Great post!")

# Upvote a post
submission.upvote()
```

### Async (for Discord bots, asyncio)
```bash
pip install asyncpraw
```
```python
import asyncpraw

async def main():
    reddit = asyncpraw.Reddit(
        client_id="...",
        client_secret="...",
        user_agent="...",
    )
    sub = await reddit.subreddit("python")
    async for post in sub.hot(limit=5):
        print(post.title)
    await reddit.close()
```

---

## Nanobot Integration

Ask the agent things like:

- *"Show me the top 5 posts from r/MachineLearning this week"*
- *"Search r/Python for asyncio tutorials"*
- *"What are the hot posts on r/worldnews right now?"*
- *"Get the comments on this Reddit post: https://reddit.com/r/python/comments/1abc23/..."*
- *"What's u/spez's karma?"*

The agent will invoke `reddit_helper.py` to fulfil the request.

---

## Rate Limits & Rules

- Reddit's API allows **60 requests per minute** for OAuth apps
- PRAW handles rate limiting automatically — no need for `time.sleep()`
- Always use a descriptive `user_agent` that includes your Reddit username
- Read [Reddit's API rules](https://www.reddit.com/wiki/api) before building bots
- Do **not** use the API for scraping at scale or violating Reddit's ToS

---

## Troubleshooting

| Error | Fix |
|---|---|
| `ResponseException: 401` | Wrong client_id or client_secret |
| `OAuthException: invalid_grant` | Wrong username/password |
| `prawcore.exceptions.Forbidden` | Subreddit is private or quarantined |
| `prawcore.exceptions.NotFound` | Subreddit or post doesn't exist |
| `RateLimitExceeded` | Too many requests — wait and retry |
| `praw not found` | Run `pip install praw` |

---

## Dependencies

- `praw>=7.8` — Reddit API wrapper
- `prawcore>=2.4` — HTTP layer (installed automatically with praw)
- Python 3.8+

---

*Skill created: 2026-02-24 — Reddit API access via PRAW with CLI and Python API support*
