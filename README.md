# Jira to GitHub Issues
A proof of concept migration tool from Jira Cloud to GitHub Issues.

Migrates issues from Jira Cloud to GitHub Issues.  Attempts to convert Jira
conventions to GitHub conventions, such as sprints to milestones and project
board mapping.

An example of migrated issues can be seen in this GitHub repo!  Check out the
issues tab to see how labels, milestones, projects are handled.

## Prerequisites
* [GitHub CLI token](https://help.github.com/en/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line)
* [Jira authentication token](https://confluence.atlassian.com/cloud/api-tokens-938839638.html)
* You will need to manually specify a username mapping from Jira usernames to GitHub usernames.

## Usage
    pip install -r requirements.txt

    python jira_to_github.py \
    --jira_server <Server URL> \  
    --jira_username <Jira login ID> \  
    --jira_token <Jira auth token> \  
    --jira_search <JQL search [Optional, defaults to all issues]> \  
    --github_token <GitHub CLI token> \  
    --github_repo <GitHub repo where migrated issues should live>
