import json
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
CONFIG = {
    "global_subreddits": [
        "worldnews", "technology", "science", "economics", "space", 
        "gadgets", "futurology", "business", "dataisbeautiful", "investing",
        "news", "politics", "environment", "energy", "electricvehicles",
        "automotive", "stocks", "wallstreetbets", "softwareengineering", "ai"
    ],
    "au_subreddits": [
        "australia", "perth", "ausfinance", "auslegal", "australian", 
        "melbourne", "sydney", "brisbane", "adelaide", "canberra",
        "tasmania", "darwin", "goldcoast", "newcastle", "geelong",
        "wollongong", "sunshinecoast", "hobart", "townsville", "cairns"
    ],
    "output_path": "/root/.nanobot/workspace/reddit_feed.md"
}

def get_posts(subreddit):
    try:
        # Using the built-in reddit_search tool via the nanobot CLI or similar
        # For this script, we'll simulate the search for top posts in the last 24h
        cmd = ["nanobot", "tool", "reddit_search", "--query", "", "--subreddit", subreddit, "--sort", "top", "--time", "day", "--limit", "3"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
        return []
    except Exception as e:
        print(f"Error fetching r/{subreddit}: {e}")
        return []

def generate_feed():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = [f"# Daily Reddit Feed - {now}\n"]
    
    content.append("## 🌍 Global Trending")
    for sub in CONFIG["global_subreddits"]:
        posts = get_posts(sub)
        if posts:
            content.append(f"### r/{sub}")
            for p in posts:
                content.append(f"- [{p['title']}]({p['url']}) ({p['score']} ↑, {p['num_comments']} 💬)")
    
    content.append("\n## 🇦🇺 Australian Trending")
    for sub in CONFIG["au_subreddits"]:
        posts = get_posts(sub)
        if posts:
            content.append(f"### r/{sub}")
            for p in posts:
                content.append(f"- [{p['title']}]({p['url']}) ({p['score']} ↑, {p['num_comments']} 💬)")
                
    Path(CONFIG["output_path"]).write_text("\n".join(content))

if __name__ == "__main__":
    generate_feed()
