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
   - Get your JIRA API token from: https://id.atlassian.com/manage-profile/security/api-tokens
   - Get your GitLab API token from: https://cd.splunkdev.com/-/profile/personal_access_tokens (optional, for MR statistics)
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
  - GitLab merge request comments are formatted as "MR: <project> (branch: <branch>) (<state>, <files> files, +<additions>/-<deletions>) - <full_url>"
  - GitLab statistics require optional `gitlab_token` in configuration
- **Cross-Team Dependencies**: Tracks dependencies to other teams and shows recent changes:
  - Automatically detects issue links to other projects
  - Shows what changed (status, assignee, comments, etc.) since yesterday (or Friday if Monday)
  - Only displays dependencies with recent activity to reduce noise
- **Customizable Time Window**: Configure how many days back to look for issue updates

## Configuration

See `example.yaml` for a complete configuration template.

### GitLab Integration

The tool can fetch real-time statistics from GitLab merge requests:

- **Without GitLab token**: Shows basic MR info (project, branch, URL)
- **With GitLab token**: Shows enhanced stats (state, files changed, additions/deletions)

**Example output:**
```
Without token: MR: Observability / Shared / olly (branch: feature-branch) - https://cd.splunkdev.com/project/-/merge_requests/123
With token:    MR: Observability / Shared / olly (branch: feature-branch) (opened, 5 files, +42/-15) - https://cd.splunkdev.com/project/-/merge_requests/123
```

**To enable GitLab statistics:**
1. Visit https://cd.splunkdev.com/-/profile/personal_access_tokens
2. Create a token with `read_api` scope
3. Add `gitlab_token: "YOUR_TOKEN_HERE"` to your configuration file
