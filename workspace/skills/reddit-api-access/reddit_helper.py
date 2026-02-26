#!/usr/bin/env python3
"""
reddit_helper.py — Reddit API helper using PRAW (Python Reddit API Wrapper)

Usage:
    python reddit_helper.py --help
    python reddit_helper.py hot --subreddit python --limit 5
    python reddit_helper.py top --subreddit worldnews --limit 10 --time week
    python reddit_helper.py search --subreddit technology --query "AI" --limit 5
    python reddit_helper.py comments --post-id <post_id> --limit 5
    python reddit_helper.py user --username <username>

Credentials are read from:
    1. Environment variables: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
    2. ~/.nanobot/workspace/skills/reddit-api-access/credentials.env  (KEY=VALUE format)
    3. Passed directly via --client-id / --client-secret / --user-agent flags
"""

import argparse
import os
import sys
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).parent
CREDS_FILE = SKILL_DIR / "credentials.env"


def load_credentials():
    """Load Reddit API credentials from env file or environment variables."""
    creds = {}

    # 1. Try loading from credentials.env
    if CREDS_FILE.exists():
        with open(CREDS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    creds[key.strip()] = value.strip().strip('"').strip("'")

    # 2. Environment variables override file values
    for env_key, cred_key in [
        ("REDDIT_CLIENT_ID", "client_id"),
        ("REDDIT_CLIENT_SECRET", "client_secret"),
        ("REDDIT_USER_AGENT", "user_agent"),
        ("REDDIT_USERNAME", "username"),
        ("REDDIT_PASSWORD", "password"),
    ]:
        if os.environ.get(env_key):
            creds[cred_key] = os.environ[env_key]

    return creds


def build_reddit(args, creds):
    """Instantiate a praw.Reddit object from args + credentials."""
    try:
        import praw
    except ImportError:
        print("ERROR: praw is not installed. Run: pip install praw", file=sys.stderr)
        sys.exit(1)

    client_id = getattr(args, "client_id", None) or creds.get("client_id") or creds.get("REDDIT_CLIENT_ID")
    client_secret = getattr(args, "client_secret", None) or creds.get("client_secret") or creds.get("REDDIT_CLIENT_SECRET")
    user_agent = getattr(args, "user_agent", None) or creds.get("user_agent") or creds.get("REDDIT_USER_AGENT") or "nanobot-reddit-skill/1.0"
    username = creds.get("username") or creds.get("REDDIT_USERNAME")
    password = creds.get("password") or creds.get("REDDIT_PASSWORD")

    if not client_id or not client_secret:
        print(
            "ERROR: Reddit API credentials not found.\n"
            "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in the environment,\n"
            f"or create {CREDS_FILE} with those values.\n"
            "See SKILL.md for setup instructions.",
            file=sys.stderr,
        )
        sys.exit(1)

    kwargs = dict(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    # Add authenticated user credentials only if both are provided
    if username and password:
        kwargs["username"] = username
        kwargs["password"] = password

    return praw.Reddit(**kwargs)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def fmt_post(post, index=None):
    prefix = f"[{index}] " if index is not None else ""
    score = f"↑{post.score:,}"
    comments = f"💬{post.num_comments:,}"
    flair = f" [{post.link_flair_text}]" if post.link_flair_text else ""
    url_line = f"    URL     : {post.url}" if not post.is_self else ""
    lines = [
        f"{prefix}{post.title}{flair}",
        f"    {score}  {comments}  r/{post.subreddit.display_name}  by u/{post.author}",
        f"    Reddit  : https://reddit.com{post.permalink}",
    ]
    if url_line:
        lines.append(url_line)
    return "\n".join(lines)


def cmd_hot(reddit, args):
    """Fetch hot posts from a subreddit."""
    sub = reddit.subreddit(args.subreddit)
    print(f"🔥 Hot posts in r/{args.subreddit} (limit={args.limit})\n{'─'*60}")
    for i, post in enumerate(sub.hot(limit=args.limit), 1):
        print(fmt_post(post, i))
        print()


def cmd_top(reddit, args):
    """Fetch top posts from a subreddit."""
    sub = reddit.subreddit(args.subreddit)
    time_filter = getattr(args, "time", "all") or "all"
    print(f"🏆 Top posts in r/{args.subreddit} (time={time_filter}, limit={args.limit})\n{'─'*60}")
    for i, post in enumerate(sub.top(time_filter=time_filter, limit=args.limit), 1):
        print(fmt_post(post, i))
        print()


def cmd_new(reddit, args):
    """Fetch new posts from a subreddit."""
    sub = reddit.subreddit(args.subreddit)
    print(f"🆕 New posts in r/{args.subreddit} (limit={args.limit})\n{'─'*60}")
    for i, post in enumerate(sub.new(limit=args.limit), 1):
        print(fmt_post(post, i))
        print()


def cmd_search(reddit, args):
    """Search posts within a subreddit."""
    sub = reddit.subreddit(args.subreddit)
    sort = getattr(args, "sort", "relevance") or "relevance"
    print(f"🔍 Search '{args.query}' in r/{args.subreddit} (sort={sort}, limit={args.limit})\n{'─'*60}")
    for i, post in enumerate(sub.search(args.query, sort=sort, limit=args.limit), 1):
        print(fmt_post(post, i))
        print()


def cmd_comments(reddit, args):
    """Fetch top-level comments from a post."""
    submission = reddit.submission(id=args.post_id)
    submission.comments.replace_more(limit=0)
    limit = args.limit
    print(f"💬 Comments on: {submission.title}\n{'─'*60}")
    for i, comment in enumerate(submission.comments[:limit], 1):
        author = comment.author.name if comment.author else "[deleted]"
        body = comment.body.replace("\n", " ")
        if len(body) > 200:
            body = body[:200] + "…"
        print(f"[{i}] u/{author} ↑{comment.score:,}")
        print(f"    {body}")
        print()


def cmd_user(reddit, args):
    """Fetch public info about a Reddit user."""
    redditor = reddit.redditor(args.username)
    # Force load of data
    _ = redditor.id
    created = redditor.created_utc
    import datetime
    joined = datetime.datetime.utcfromtimestamp(created).strftime("%Y-%m-%d")
    print(f"👤 u/{redditor.name}")
    print(f"   Link karma   : {redditor.link_karma:,}")
    print(f"   Comment karma: {redditor.comment_karma:,}")
    print(f"   Joined (UTC) : {joined}")
    is_mod = getattr(redditor, "is_mod", False)
    is_gold = getattr(redditor, "is_gold", False)
    print(f"   Moderator    : {is_mod}")
    print(f"   Reddit Gold  : {is_gold}")
    print(f"\n   Recent posts:")
    for i, post in enumerate(redditor.submissions.new(limit=5), 1):
        print(f"   [{i}] {post.title[:80]} — r/{post.subreddit.display_name}")


def cmd_subreddit_info(reddit, args):
    """Show info about a subreddit."""
    sub = reddit.subreddit(args.subreddit)
    _ = sub.id  # trigger load
    print(f"📋 r/{sub.display_name}")
    print(f"   Title      : {sub.title}")
    print(f"   Subscribers: {sub.subscribers:,}")
    print(f"   Description: {sub.public_description[:300]}")
    print(f"   NSFW       : {sub.over18}")
    print(f"   URL        : https://reddit.com{sub.url}")


def cmd_json(reddit, args):
    """Output hot posts as JSON (useful for piping to other tools)."""
    sub = reddit.subreddit(args.subreddit)
    posts = []
    for post in sub.hot(limit=args.limit):
        posts.append({
            "id": post.id,
            "title": post.title,
            "score": post.score,
            "num_comments": post.num_comments,
            "url": post.url,
            "permalink": f"https://reddit.com{post.permalink}",
            "author": str(post.author),
            "subreddit": post.subreddit.display_name,
            "is_self": post.is_self,
            "selftext": post.selftext[:500] if post.is_self else "",
        })
    print(json.dumps(posts, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Reddit API helper using PRAW",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--client-id", help="Reddit app client ID (overrides credentials file)")
    parser.add_argument("--client-secret", help="Reddit app client secret (overrides credentials file)")
    parser.add_argument("--user-agent", help="User-agent string (default: nanobot-reddit-skill/1.0)")

    sub = parser.add_subparsers(dest="command", required=True)

    # hot
    p_hot = sub.add_parser("hot", help="Fetch hot posts from a subreddit")
    p_hot.add_argument("--subreddit", "-s", required=True, help="Subreddit name (without r/)")
    p_hot.add_argument("--limit", "-n", type=int, default=10, help="Number of posts (default: 10)")

    # top
    p_top = sub.add_parser("top", help="Fetch top posts from a subreddit")
    p_top.add_argument("--subreddit", "-s", required=True)
    p_top.add_argument("--limit", "-n", type=int, default=10)
    p_top.add_argument("--time", "-t", default="week",
                       choices=["hour", "day", "week", "month", "year", "all"],
                       help="Time filter (default: week)")

    # new
    p_new = sub.add_parser("new", help="Fetch new posts from a subreddit")
    p_new.add_argument("--subreddit", "-s", required=True)
    p_new.add_argument("--limit", "-n", type=int, default=10)

    # search
    p_search = sub.add_parser("search", help="Search posts in a subreddit")
    p_search.add_argument("--subreddit", "-s", required=True)
    p_search.add_argument("--query", "-q", required=True, help="Search query")
    p_search.add_argument("--limit", "-n", type=int, default=10)
    p_search.add_argument("--sort", default="relevance",
                          choices=["relevance", "hot", "top", "new", "comments"])

    # comments
    p_comments = sub.add_parser("comments", help="Fetch comments from a post")
    p_comments.add_argument("--post-id", required=True, help="Reddit post ID (e.g. 1abc23)")
    p_comments.add_argument("--limit", "-n", type=int, default=10)

    # user
    p_user = sub.add_parser("user", help="Fetch public info about a Reddit user")
    p_user.add_argument("--username", required=True, help="Reddit username (without u/)")

    # info
    p_info = sub.add_parser("info", help="Show info about a subreddit")
    p_info.add_argument("--subreddit", "-s", required=True)

    # json
    p_json = sub.add_parser("json", help="Output hot posts as JSON")
    p_json.add_argument("--subreddit", "-s", required=True)
    p_json.add_argument("--limit", "-n", type=int, default=10)

    args = parser.parse_args()
    creds = load_credentials()
    reddit = build_reddit(args, creds)

    dispatch = {
        "hot": cmd_hot,
        "top": cmd_top,
        "new": cmd_new,
        "search": cmd_search,
        "comments": cmd_comments,
        "user": cmd_user,
        "info": cmd_subreddit_info,
        "json": cmd_json,
    }
    dispatch[args.command](reddit, args)


if __name__ == "__main__":
    main()
