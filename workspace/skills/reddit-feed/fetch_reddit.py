import os
import json
import feedparser
import time

# CONFIG: 60 Subreddits (20 AU, 20 AI, 20 Global)
SUBS = {
    "AU": ["australia", "perth", "ausfinance", "ausrenovation", "auselectricvehicles", "sydney", "melbourne", "brisbane", "adelaide", "canberra", "tasmania", "darwin", "goldcoast", "newcastle", "wollongong", "geelong", "auslegal", "australian", "straya", "westernaustralia"],
    "AI": ["artificial", "MachineLearning", "OpenAI", "LocalLLaMA", "Singularity", "ChatGPTCoding", "ClaudeAI", "Anthropic", "AutoGPT", "AIExplaining", "ArtificialInteligence", "StableDiffusion", "Midjourney", "SoraAI", "GenerativeAI", "LLM", "AI_Agents", "computervision", "nlp", "robotics"],
    "GLOBAL": ["worldnews", "news", "technology", "science", "economics", "futurology", "business", "politics", "gadgets", "space", "environment", "gaming", "movies", "music", "books", "history", "philosophy", "photography", "travel", "investing"]
}

def fetch_top_post(subreddit):
    # Use direct .rss with a custom User-Agent to avoid 429s from Reddit
    url = f"https://www.reddit.com/r/{subreddit}/hot/.rss"
    
    try:
        # Pass a standard browser User-Agent as Reddit blocks feedparser's default
        feed = feedparser.parse(url, agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        if not feed.entries:
            return None
            
        top = feed.entries[0]
        # Ensure we are getting the actual reddit link, not a direct media link if possible
        link = top.link
        if not link.startswith("https://www.reddit.com"):
            # Fallback to comments link if top.link points to an external site/image
            for detail in top.links:
                if "comments" in detail.href:
                    link = detail.href
                    break

        return {
            "title": top.title,
            "link": link,
            "sub": subreddit
        }
    except Exception as e:
        return None

def generate_report():
    report = "# 🚀 Reddit Daily Briefing\n\n"
    
    for category, sub_list in SUBS.items():
        report += f"### {category} Trending\n"
        for sub in sub_list:
            post = fetch_top_post(sub)
            if post:
                report += f"- **r/{post['sub']}**: [{post['title']}]({post['link']})\n"
            else:
                report += f"- **r/{sub}**: (No data found today)\n"
            time.sleep(0.5) # Rate limiting
        report += "\n"
        
    return report

if __name__ == "__main__":
    report_content = generate_report()
    # Save to workspace
    with open("/root/.nanobot/workspace/reddit_feed.md", "w") as f:
        f.write(report_content)
    print("SUCCESS: Reddit feed updated with real RSS links.")
