#!/usr/bin/env python3
import requests
from requests.auth import HTTPBasicAuth
import yaml
import sys

def load_config(config_path):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

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
        print("")

if __name__ == "__main__":
    main()