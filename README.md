# standup-notes

This tool whips up a draft for standup notes by pulling in data from the Jira project, based on the configuration file. It covers all the issues and a summary of activities, neatly sorted by engineer.

## Setup

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Create your team configuration:**
   ```bash
   cp example.yaml your_team.yaml
   ```

3. **Edit your configuration file** with your actual JIRA credentials and team details:
   - Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens
   - Find your board ID from your JIRA board URL
   - Update the engineer assignments and display names

## Usage

```bash
uv run ./main.py your_team.yaml
```

## Features

- **Recent Issues**: Fetches issues that are active or recently updated
- **Engineer Mapping**: Maps JIRA assignee identifiers to friendly display names  
- **Recent Comments**: Shows the latest comment on each issue if added recently:
  - If today is Monday: shows comments from Friday onwards
  - Other days: shows comments from yesterday onwards
  - GitLab merge request comments are formatted as "MR: <project> (branch: <branch>)"
- **Cross-Team Dependencies**: Tracks dependencies to other teams and shows recent changes:
  - Automatically detects issue links to other projects
  - Shows what changed (status, assignee, comments, etc.) since yesterday (or Friday if Monday)
  - Only displays dependencies with recent activity to reduce noise
- **Customizable Time Window**: Configure how many days back to look for issue updates

## Configuration

See `example.yaml` for a complete configuration template.
