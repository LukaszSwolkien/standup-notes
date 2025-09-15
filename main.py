#!/usr/bin/env python3
import requests
from requests.auth import HTTPBasicAuth
import yaml
import sys
from datetime import datetime, timedelta

def load_config(config_path):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def get_comment_cutoff_date():
    """
    Calculate the cutoff date for checking comments:
    - If today is Monday (0), check since Friday (3 days ago)
    - For any other day, check since yesterday (1 day ago)
    """
    today = datetime.now()
    if today.weekday() == 0:  # Monday
        cutoff_date = today - timedelta(days=3)  # Friday
    else:
        cutoff_date = today - timedelta(days=1)  # Yesterday
    return cutoff_date

def get_issue_comments(issue_key, jira_base_url, auth, cutoff_date):
    """
    Fetch comments for a specific issue that were added after the cutoff date.
    Returns the most recent comment if it meets the criteria, None otherwise.
    """
    url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/comment"
    response = requests.get(url, auth=auth)
    response.raise_for_status()
    
    comments_data = response.json()
    comments = comments_data.get("comments", [])
    
    # Filter comments by date and get the most recent one
    recent_comments = []
    for comment in comments:
        # Parse comment creation date (format: 2024-01-15T10:30:45.123+0000)
        created_str = comment.get("created", "")
        if created_str:
            try:
                # Remove timezone info for simple comparison
                created_date = datetime.fromisoformat(created_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if created_date >= cutoff_date:
                    recent_comments.append(comment)
            except ValueError:
                continue
    
    # Return the most recent comment if any
    if recent_comments:
        # Sort by creation date and return the latest
        recent_comments.sort(key=lambda x: x.get("created", ""), reverse=True)
        return recent_comments[0]
    
    return None





def main():
    if len(sys.argv) < 2:
        print("Usage: uv run main.py <config.yaml>")
        sys.exit(1)

    config_path = sys.argv[1]
    config = load_config(config_path)

    JIRA_URL = config["jira_base_url"]
    PROJECT_KEY = config["project_key"]
    BOARD_ID = str(config["board_id"])
    UPDATED_DAYS = config.get("recent_days", 1)
    engineers = config["engineers"]

    auth = HTTPBasicAuth(config["email"], config["api_token"])
    headers = {"Accept": "application/json"}

    def get_number_of_sprints(board_id, jira_base_url, auth):
        url = f"{jira_base_url}/rest/agile/1.0/board/{board_id}/sprint"
        params = {"maxResults": 1}
        response = requests.get(url, params=params, auth=auth)
        response.raise_for_status()
        data = response.json()
        return data.get("total", 0)

    def get_active_sprint(board_id):
        max_results = 50
        url = f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint"
        no_sprints = get_number_of_sprints(board_id, JIRA_URL, auth)
        params = {"startAt": max(0, no_sprints - max_results), "maxResults": max_results}
        response = requests.get(url, params=params, headers=headers, auth=auth)
        response.raise_for_status()
        sprints = response.json().get("values", [])
        for sprint in sprints:
            if sprint.get("state") == "active":
                return sprint
        return None

    def get_issues_for_engineer(engineer, sprint_id):
        jql = (
            f'project = {PROJECT_KEY} AND '
            f'sprint = {sprint_id} AND '
            f'assignee = "{engineer}" AND '
            f'(status in ("Blocked", "In Progress", "In Review") or updated >= -{UPDATED_DAYS}d )'
        )
        url = f"{JIRA_URL}/rest/api/3/search/jql"
        params = {"jql": jql, "fields": "key,summary,assignee,status"}
        response = requests.get(url, headers=headers, params=params, auth=auth)
        response.raise_for_status()
        return response.json().get("issues", [])

    active_sprint = get_active_sprint(BOARD_ID)
    if not active_sprint or not active_sprint.get("id"):
        print("No active sprint found.")
        return

    # Get the cutoff date for checking recent comments
    comment_cutoff_date = get_comment_cutoff_date()
    
    print(f"Sprint: {active_sprint['name']}")
    for engineer in engineers:
        assignee = engineer["assignee"]
        display_name = engineer["display_name"]
        issues = get_issues_for_engineer(assignee, active_sprint["id"])
        print(f"{display_name}")
        for issue in issues:
            issue_key = issue.get("key")
            if issue_key:
                print(f"{JIRA_URL}/browse/{issue_key}")
                
                # Check for recent comments
                recent_comment = get_issue_comments(issue_key, JIRA_URL, auth, comment_cutoff_date)
                if recent_comment:
                    # Extract comment text and author
                    comment_body = recent_comment.get("body", {})
                    comment_text = ""
                    if isinstance(comment_body, dict):
                        # Handle Atlassian Document Format (ADF)
                        content = comment_body.get("content", [])
                        for block in content:
                            if block.get("type") == "paragraph":
                                paragraph_content = block.get("content", [])
                                for text_node in paragraph_content:
                                    if text_node.get("type") == "text":
                                        comment_text += text_node.get("text", "")
                    else:
                        comment_text = str(comment_body)
                    
                    author_name = recent_comment.get("author", {}).get("displayName", "Unknown")
                    if comment_text.strip():
                        print(f"  💬 {author_name}: {comment_text.strip()}")
        print("")

if __name__ == "__main__":
    main()