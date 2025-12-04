#!/usr/bin/env python3
import requests
from requests.auth import HTTPBasicAuth
import yaml
import sys
import csv
from datetime import datetime, timedelta
from collections import Counter

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
        print("Usage: uv run main.py <config.yaml> [--list] [--csv]")
        print("  --list  List all sprint issues sorted by assignee")
        print("  --csv   Output all sprint issues in CSV format")
        sys.exit(1)

    config_path = sys.argv[1]
    list_mode = "--list" in sys.argv
    csv_mode = "--csv" in sys.argv
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

    # Common custom field names for story points (varies by Jira instance)
    # Can be overridden via story_points_field in config
    DEFAULT_STORY_POINTS_FIELDS = [
        "customfield_10303",  # Story Points (common in Splunk Jira)
        "customfield_23102",  # Story point estimate
        "customfield_10016", "customfield_10026", "customfield_10004",
        "customfield_10002", "customfield_10005", "customfield_10008",
        "customfield_10014", "customfield_10028", "customfield_10034"
    ]
    
    # Use configured field if specified, otherwise try common fields
    configured_sp_field = config.get("story_points_field")
    STORY_POINTS_FIELDS = [configured_sp_field] if configured_sp_field else DEFAULT_STORY_POINTS_FIELDS
    
    def get_story_points(issue):
        """Extract story points from issue fields."""
        fields = issue.get("fields", {})
        for field_name in STORY_POINTS_FIELDS:
            points = fields.get(field_name)
            if points is not None:
                # Story points can be int or float
                return int(points) if isinstance(points, (int, float)) else points
        return None

    def get_issues_for_engineer(engineer, sprint_id):
        jql = (
            f'project = {PROJECT_KEY} AND '
            f'sprint = {sprint_id} AND '
            f'assignee = "{engineer}" AND '
            f'(status in ("Blocked", "In Progress", "In Review") or updated >= -{UPDATED_DAYS}d )'
        )
        url = f"{JIRA_URL}/rest/api/3/search/jql"
        fields = "key,summary,assignee,status," + ",".join(STORY_POINTS_FIELDS)
        params = {"jql": jql, "fields": fields}
        response = requests.get(url, headers=headers, params=params, auth=auth)
        response.raise_for_status()
        return response.json().get("issues", [])

    def get_all_sprint_issues(sprint_id):
        """Get all issues from the sprint for the team."""
        jql = f'project = {PROJECT_KEY} AND sprint = {sprint_id}'
        url = f"{JIRA_URL}/rest/api/3/search/jql"
        fields = "key,summary,assignee,status," + ",".join(STORY_POINTS_FIELDS)
        params = {"jql": jql, "fields": fields, "maxResults": 200}
        response = requests.get(url, headers=headers, params=params, auth=auth)
        response.raise_for_status()
        return response.json().get("issues", [])

    def print_statistics(issues):
        """Print statistics: total count, story points, and count per status."""
        if not issues:
            print("Statistics: No issues found")
            return
        
        # Count by status and sum story points
        status_counts = Counter()
        total_points = 0
        for issue in issues:
            status = issue.get("fields", {}).get("status", {}).get("name", "Unknown")
            status_counts[status] += 1
            points = get_story_points(issue)
            if points is not None:
                total_points += points
        
        print("---")
        print(f"Total: {len(issues)} issues | {total_points} SP")
        # Sort by count descending
        for status, count in sorted(status_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {status}: {count}")

    active_sprint = get_active_sprint(BOARD_ID)
    if not active_sprint or not active_sprint.get("id"):
        print("No active sprint found.")
        return

    # Handle --csv mode: output all sprint issues in CSV format
    if csv_mode:
        issues = get_all_sprint_issues(active_sprint["id"])
        
        # Sort by assignee display name (unassigned issues go last)
        def get_assignee_name(issue):
            assignee = issue.get("fields", {}).get("assignee")
            if assignee:
                return assignee.get("displayName", "Unassigned")
            return "zzz_Unassigned"  # Sort unassigned last
        
        issues.sort(key=get_assignee_name)
        
        # Write CSV to stdout
        writer = csv.writer(sys.stdout)
        writer.writerow(["Assignee", "Issue", "Story Points"])
        
        for issue in issues:
            assignee = issue.get("fields", {}).get("assignee")
            assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
            issue_key = issue.get("key", "")
            summary = issue.get("fields", {}).get("summary", "")
            issue_with_summary = f"{issue_key} {summary}"
            story_points = get_story_points(issue)
            points_str = str(story_points) if story_points is not None else ""
            
            writer.writerow([assignee_name, issue_with_summary, points_str])
        return

    print(f"Sprint: {active_sprint['name']}")

    # Handle --list mode: show all sprint issues sorted by assignee
    if list_mode:
        issues = get_all_sprint_issues(active_sprint["id"])
        
        # Sort by assignee display name (unassigned issues go last)
        def get_assignee_name(issue):
            assignee = issue.get("fields", {}).get("assignee")
            if assignee:
                return assignee.get("displayName", "Unassigned")
            return "zzz_Unassigned"  # Sort unassigned last
        
        issues.sort(key=get_assignee_name)
        
        current_assignee = None
        for issue in issues:
            assignee = issue.get("fields", {}).get("assignee")
            assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
            
            # Print assignee header when it changes
            if assignee_name != current_assignee:
                if current_assignee is not None:
                    print("")  # Blank line between assignees
                print(f"{assignee_name}")
                current_assignee = assignee_name
            
            issue_key = issue.get("key", "")
            summary = issue.get("fields", {}).get("summary", "")
            story_points = get_story_points(issue)
            points_str = f" | {story_points} SP" if story_points is not None else ""
            print(f"  {issue_key} {summary}{points_str}")
        print("")
        print_statistics(issues)
        return

    # Get the cutoff date for checking recent comments
    comment_cutoff_date = get_comment_cutoff_date()
    
    all_issues = []  # Collect all issues for statistics
    for engineer in engineers:
        assignee = engineer["assignee"]
        display_name = engineer["display_name"]
        issues = get_issues_for_engineer(assignee, active_sprint["id"])
        all_issues.extend(issues)
        print(f"{display_name}")
        for issue in issues:
            issue_key = issue.get("key")
            if issue_key:
                summary = issue.get("fields", {}).get("summary", "")
                story_points = get_story_points(issue)
                points_str = f" | {story_points} SP" if story_points is not None else ""
                print(f"{JIRA_URL}/browse/{issue_key} {summary}{points_str}")
                
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
    
    print_statistics(all_issues)

if __name__ == "__main__":
    main()