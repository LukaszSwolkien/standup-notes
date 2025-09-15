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

## Configuration

See `example.yaml` for a complete configuration template. The configuration supports:

- **Engineer mapping**: Map JIRA assignee identifiers to friendly display names
- **Customizable time window**: Configure how many days back to look for updates
