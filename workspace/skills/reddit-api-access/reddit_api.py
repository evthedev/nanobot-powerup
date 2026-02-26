import praw
import sys

# Replace these with your Reddit app details
def reddit_instance():
    return praw.Reddit(
        client_id='your_client_id',
        client_secret='your_client_secret',
        user_agent='your_user_agent'
    )

def top_posts(subreddit_name, limit=5):
    reddit = reddit_instance()
    subreddit = reddit.subreddit(subreddit_name)
    posts = subreddit.top(limit=limit)
    return [(post.title, post.score, post.url) for post in posts]

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python reddit_api.py top_posts <subreddit_name> <limit>")
        sys.exit(1)
    action = sys.argv[1]
    subreddit_name = sys.argv[2]
    limit = int(sys.argv[3])
    if action == "top_posts":
        posts = top_posts(subreddit_name, limit)
        for title, score, url in posts:
            print(f"Title: {title}\nScore: {score}\nURL: {url}\n")