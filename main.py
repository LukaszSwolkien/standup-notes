#!/usr/bin/env python3
import requests
from requests.auth import HTTPBasicAuth
import yaml
import sys
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

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

def get_issue_dependencies(issue_key, jira_base_url, auth, current_project_key):
    """
    Fetch dependencies (issue links) for a specific issue.
    Returns only links to other teams (different project keys).
    """
    url = f"{jira_base_url}/rest/api/3/issue/{issue_key}"
    params = {"fields": "issuelinks"}
    response = requests.get(url, params=params, auth=auth)
    response.raise_for_status()
    
    issue_data = response.json()
    issue_links = issue_data.get("fields", {}).get("issuelinks", [])
    
    dependencies = []
    for link in issue_links:
        # Check both inward and outward links
        linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
        if linked_issue:
            linked_key = linked_issue.get("key", "")
            linked_project = linked_key.split("-")[0] if "-" in linked_key else ""
            
            # Only include dependencies to other teams (different project keys)
            if linked_project and linked_project != current_project_key:
                link_type = link.get("type", {}).get("name", "Related")
                dependencies.append({
                    "key": linked_key,
                    "project": linked_project,
                    "link_type": link_type,
                    "summary": linked_issue.get("fields", {}).get("summary", ""),
                    "status": linked_issue.get("fields", {}).get("status", {}).get("name", "Unknown")
                })
    
    return dependencies

def get_dependency_changes(dependency_key, jira_base_url, auth, cutoff_date):
    """
    Check if a dependency issue was updated recently and what changed.
    Returns a summary of changes if any, None otherwise.
    """
    url = f"{jira_base_url}/rest/api/3/issue/{dependency_key}"
    params = {"fields": "updated,status,assignee,summary", "expand": "changelog"}
    
    try:
        response = requests.get(url, params=params, auth=auth)
        response.raise_for_status()
        issue_data = response.json()
        
        # Check if issue was updated recently
        updated_str = issue_data.get("fields", {}).get("updated", "")
        if updated_str:
            try:
                updated_date = datetime.fromisoformat(updated_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if updated_date < cutoff_date:
                    return None
            except ValueError:
                return None
        else:
            return None
        
        changes = []
        
        # Check changelog for recent changes
        changelog = issue_data.get("changelog", {})
        histories = changelog.get("histories", [])
        
        for history in histories:
            history_created = history.get("created", "")
            if history_created:
                try:
                    history_date = datetime.fromisoformat(history_created.replace("Z", "+00:00")).replace(tzinfo=None)
                    if history_date >= cutoff_date:
                        # Process items in this history entry
                        for item in history.get("items", []):
                            field = item.get("field", "")
                            from_value = item.get("fromString", "")
                            to_value = item.get("toString", "")
                            
                            if field == "status":
                                changes.append(f"Status: {from_value} → {to_value}")
                            elif field == "assignee":
                                changes.append(f"Assignee: {from_value or 'Unassigned'} → {to_value or 'Unassigned'}")
                            elif field == "summary":
                                changes.append(f"Summary updated")
                            elif field == "description":
                                changes.append(f"Description updated")
                            elif field in ["priority", "Priority"]:
                                changes.append(f"Priority: {from_value} → {to_value}")
                except ValueError:
                    continue
        
        # Check for recent comments
        comment_url = f"{jira_base_url}/rest/api/3/issue/{dependency_key}/comment"
        comment_response = requests.get(comment_url, auth=auth)
        if comment_response.status_code == 200:
            comments_data = comment_response.json()
            comments = comments_data.get("comments", [])
            
            recent_comments = 0
            for comment in comments:
                created_str = comment.get("created", "")
                if created_str:
                    try:
                        created_date = datetime.fromisoformat(created_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        if created_date >= cutoff_date:
                            recent_comments += 1
                    except ValueError:
                        continue
            
            if recent_comments > 0:
                changes.append(f"{recent_comments} new comment{'s' if recent_comments > 1 else ''}")
        
        return changes if changes else None
        
    except requests.exceptions.RequestException:
        return None

def format_gitlab_mr_comment(comment_text, author_name, gitlab_mr_url=None):
    """
    Format GitLab merge request comments to show as 'MR: <link>'
    Returns formatted text if it's a GitLab MR comment, None otherwise.
    """
    if "jira-gitlab" not in author_name.lower():
        return None
    
    if "merge request" not in comment_text.lower():
        return None
    
    # If we have the actual MR URL from ADF structure, use it
    if gitlab_mr_url:
        # Also try to extract project and branch for additional context
        project_match = re.search(r'merge request of ([^:]+?) on branch', comment_text)
        branch_match = re.search(r'on branch ([^:]+):', comment_text)
        
        if project_match and branch_match:
            project = project_match.group(1).strip()
            branch = branch_match.group(1).strip()
            return f"MR: {project} (branch: {branch}) - {gitlab_mr_url}"
        else:
            return f"MR: {gitlab_mr_url}"
    
    # Fallback: try to extract project and branch information only
    branch_match = re.search(r'on branch ([^:]+):', comment_text)
    project_match = re.search(r'merge request of ([^:]+?) on branch', comment_text)
    
    if branch_match and project_match:
        branch = branch_match.group(1).strip()
        project = project_match.group(1).strip()
        return f"MR: {project} (branch: {branch})"
    
    # If we can't parse the specific format, show a generic MR indicator
    if "merge request" in comment_text.lower():
        return "MR: GitLab merge request mentioned"
    
    return None

def extract_gitlab_mr_info(gitlab_url):
    """
    Extract project path and MR ID from GitLab URL.
    Example: https://cd.splunkdev.com/observability/shared/olly/-/merge_requests/14487
    Returns: (project_path, mr_id) or (None, None) if parsing fails
    """
    if not gitlab_url or "cd.splunkdev.com" not in gitlab_url:
        return None, None
    
    try:
        # Parse URL: https://cd.splunkdev.com/project/path/-/merge_requests/123
        parsed = urlparse(gitlab_url)
        path_parts = parsed.path.strip('/').split('/')
        
        # Find the merge_requests part and extract MR ID
        if 'merge_requests' in path_parts:
            mr_index = path_parts.index('merge_requests')
            if mr_index + 1 < len(path_parts):
                mr_id = path_parts[mr_index + 1]
                # Project path is everything before '/-/'
                project_parts = []
                for part in path_parts:
                    if part == '-':
                        break
                    project_parts.append(part)
                project_path = '/'.join(project_parts)
                return project_path, mr_id
    except Exception:
        pass
    
    return None, None

def get_gitlab_mr_stats(gitlab_url, gitlab_token=None):
    """
    Fetch merge request statistics from GitLab API.
    Returns dictionary with MR stats or None if failed.
    """
    project_path, mr_id = extract_gitlab_mr_info(gitlab_url)
    if not project_path or not mr_id:
        return None
    
    # GitLab API endpoint
    api_base = "https://cd.splunkdev.com/api/v4"
    project_encoded = requests.utils.quote(project_path, safe='')
    
    headers = {"Accept": "application/json"}
    if gitlab_token:
        headers["Authorization"] = f"Bearer {gitlab_token}"
    
    try:
        # Get MR basic info
        mr_url = f"{api_base}/projects/{project_encoded}/merge_requests/{mr_id}"
        mr_response = requests.get(mr_url, headers=headers, timeout=10)
        
        if mr_response.status_code == 401:
            # Authentication required but not provided or invalid
            return {"error": "GitLab API authentication required"}
        elif mr_response.status_code == 404:
            if not gitlab_token:
                return {"error": "GitLab token required for MR statistics"}
            else:
                return {"error": "MR not found"}
        elif mr_response.status_code != 200:
            return {"error": f"GitLab API error: {mr_response.status_code}"}
        
        mr_data = mr_response.json()
        
        # Get MR changes/diffs
        changes_url = f"{api_base}/projects/{project_encoded}/merge_requests/{mr_id}/changes"
        changes_response = requests.get(changes_url, headers=headers, timeout=10)
        
        stats = {
            "title": mr_data.get("title", ""),
            "state": mr_data.get("state", ""),
            "author": mr_data.get("author", {}).get("name", "Unknown"),
            "created_at": mr_data.get("created_at", ""),
            "updated_at": mr_data.get("updated_at", ""),
            "commits": mr_data.get("user_notes_count", 0),  # Approximation
            "upvotes": mr_data.get("upvotes", 0),
            "downvotes": mr_data.get("downvotes", 0),
        }
        
        if changes_response.status_code == 200:
            changes_data = changes_response.json()
            changes = changes_data.get("changes", [])
            
            files_changed = len(changes)
            additions = 0
            deletions = 0
            
            for change in changes:
                diff = change.get("diff", "")
                additions += diff.count("\n+") - diff.count("\n+++")
                deletions += diff.count("\n-") - diff.count("\n---")
            
            stats.update({
                "files_changed": files_changed,
                "additions": max(0, additions),
                "deletions": max(0, deletions),
            })
        
        return stats
        
    except requests.RequestException:
        return {"error": "Failed to connect to GitLab API"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

def format_gitlab_mr_with_stats(comment_text, author_name, gitlab_mr_url=None, gitlab_token=None):
    """
    Enhanced GitLab MR formatter that includes statistics from GitLab API.
    """
    basic_format = format_gitlab_mr_comment(comment_text, author_name, gitlab_mr_url)
    if not basic_format or not gitlab_mr_url:
        return basic_format
    
    # Get GitLab statistics
    stats = get_gitlab_mr_stats(gitlab_mr_url, gitlab_token)
    
    if not stats or "error" in stats:
        # Return basic format if stats unavailable
        return basic_format
    
    # Format with statistics
    state = stats.get("state", "unknown")
    files = stats.get("files_changed", 0)
    additions = stats.get("additions", 0)
    deletions = stats.get("deletions", 0)
    
    # Build enhanced format
    project_match = re.search(r'merge request of ([^:]+?) on branch', comment_text)
    branch_match = re.search(r'on branch ([^:]+):', comment_text)
    
    if project_match and branch_match:
        project = project_match.group(1).strip()
        branch = branch_match.group(1).strip()
        stats_info = f"({state}, {files} files, +{additions}/-{deletions})"
        return f"MR: {project} (branch: {branch}) {stats_info} - {gitlab_mr_url}"
    else:
        stats_info = f"({state}, {files} files, +{additions}/-{deletions})"
        return f"MR: {stats_info} - {gitlab_mr_url}"

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
    GITLAB_TOKEN = config.get("gitlab_token")  # Optional GitLab API token

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
                    gitlab_mr_url = None
                    
                    if isinstance(comment_body, dict):
                        # Handle Atlassian Document Format (ADF)
                        content = comment_body.get("content", [])
                        for block in content:
                            if block.get("type") == "paragraph":
                                paragraph_content = block.get("content", [])
                                for text_node in paragraph_content:
                                    if text_node.get("type") == "text":
                                        comment_text += text_node.get("text", "")
                                        
                                        # Extract GitLab MR URL from link marks
                                        marks = text_node.get("marks", [])
                                        for mark in marks:
                                            if mark.get("type") == "link":
                                                href = mark.get("attrs", {}).get("href", "")
                                                if "cd.splunkdev.com" in href and "merge_requests" in href:
                                                    gitlab_mr_url = href
                    else:
                        comment_text = str(comment_body)
                    
                    author_name = recent_comment.get("author", {}).get("displayName", "Unknown")
                    if comment_text.strip():
                        # Check if this is a GitLab merge request comment and format it differently
                        if "jira-gitlab" in author_name.lower() and "merge request" in comment_text.lower():
                            gitlab_mr_text = format_gitlab_mr_with_stats(comment_text, author_name, gitlab_mr_url, GITLAB_TOKEN)
                            if gitlab_mr_text:
                                print(f"  {gitlab_mr_text}")
                                # Show hint about GitLab token if no token is configured and no stats are shown
                                if not GITLAB_TOKEN and " files, +" not in gitlab_mr_text:  # No file stats means no token worked
                                    print(f"    ℹ️  Add 'gitlab_token' to config for MR statistics (state, files, changes)")
                            else:
                                print(f"  💬 {author_name}: {comment_text.strip()}")
                        else:
                            print(f"  💬 {author_name}: {comment_text.strip()}")
                
                # Check for dependencies to other teams
                dependencies = get_issue_dependencies(issue_key, JIRA_URL, auth, PROJECT_KEY)
                for dependency in dependencies:
                    changes = get_dependency_changes(dependency["key"], JIRA_URL, auth, comment_cutoff_date)
                    if changes:
                        print(f"  🔗 {dependency['key']} ({dependency['status']}): {', '.join(changes)}")
                    # Uncomment the line below to show all dependencies (including those without recent changes)
                    # else:
                    #     print(f"  🔗 {dependency['key']} ({dependency['status']}) - no recent changes")
        print("")

if __name__ == "__main__":
    main()