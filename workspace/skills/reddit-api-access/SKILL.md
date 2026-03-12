# Reddit API Access Skill

Fetch posts, comments, user info, and subreddit data via the CLI helper script.

---

## Always use the CLI — never write inline PRAW code

**Do NOT write a new script using PRAW from scratch.** Use `reddit_helper.py` directly:

```bash
python3 ~/.nanobot/workspace/skills/reddit-api-access/reddit_helper.py <command> [options]
```

Credentials are loaded automatically from `credentials.env` in the skill directory.

---

## Commands

### `hot` — Hot posts from a subreddit
```bash
python3 reddit_helper.py hot --subreddit python --limit 5
python3 reddit_helper.py hot -s worldnews -n 10
```

### `top` — Top posts by time period
```bash
python3 reddit_helper.py top --subreddit technology --limit 5 --time week
python3 reddit_helper.py top -s science -n 10 --time month
# time options: hour | day | week | month | year | all
```

### `new` — Newest posts
```bash
python3 reddit_helper.py new --subreddit MachineLearning --limit 5
```

### `search` — Search within a subreddit
```bash
python3 reddit_helper.py search --subreddit technology --query "artificial intelligence" --limit 5
python3 reddit_helper.py search -s python -q "asyncio" --sort top
# sort options: relevance | hot | top | new | comments
```

### `comments` — Comments on a specific post
```bash
# Post ID is the alphanumeric code in the Reddit URL
# e.g. https://reddit.com/r/python/comments/1abc23/... → ID is 1abc23
python3 reddit_helper.py comments --post-id 1abc23 --limit 10
```

### `user` — Public profile info
```bash
python3 reddit_helper.py user --username spez
```

### `info` — Subreddit metadata
```bash
python3 reddit_helper.py info --subreddit Python
```

### `json` — Output as JSON (for piping/scripting)
```bash
python3 reddit_helper.py json --subreddit Python --limit 5
python3 reddit_helper.py json -s worldnews -n 20 | jq '.[].title'
```

---

## Credentials

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
```

---

## Rate Limits

- 60 requests/minute for OAuth apps — PRAW handles rate limiting automatically
- Do not use the API for scraping at scale or violating Reddit's ToS

---

## Troubleshooting

| Error | Fix |
|---|---|
| `ResponseException: 401` | Wrong client_id or client_secret |
| `prawcore.exceptions.Forbidden` | Subreddit is private or quarantined |
| `prawcore.exceptions.NotFound` | Subreddit or post doesn't exist |
| `praw not found` | Run `/opt/anaconda3/bin/pip install praw` |
