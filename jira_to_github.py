#!/usr/bin/env python
"""Jira to GitHub Issues migration tool

Migrates issues from Jira Cloud to GitHub Issues.  Attempts to convert Jira
conventions to GitHub conventions, such as sprints to milestones and project
board mapping.

Example:
  python main.py \
      --jira_server <Server URL> \
      --jira_username <Jira login ID> \
      --jira_token <Jira auth token> \
      --jira_search <JQL search [Optional, defaults to all issues]> \
      --github_token <GitHub CLI token> \
      --github_repo <GitHub repo where migrated issues should live>
"""
import re
import github
import jira

from absl import app
from absl import flags
from absl import logging
from dateutil import parser

# Define flags
FLAGS = flags.FLAGS
flags.DEFINE_string('jira_server',
                    None,
                    'Address of the Jira server to connect to.')
flags.DEFINE_string('jira_username',
                    None,
                    'Username to authenticate via Jira.')
flags.DEFINE_string('jira_token',
                    None,
                    'API token generated for the given username.')
flags.DEFINE_string('jira_search',
                    '',
                    'JQL search string to migrate.')
flags.DEFINE_string('github_repo',
                    None,
                    'Name of the GitHub repo issues should be migrated to.')
flags.DEFINE_string('github_token',
                    None,
                    'GitHub access token with repo scope.')
flags.mark_flag_as_required('jira_server')
flags.mark_flag_as_required('jira_username')
flags.mark_flag_as_required('jira_token')
flags.mark_flag_as_required('github_token')
flags.mark_flag_as_required('github_repo')

# Global variables
# TODO(mjcastner): Replace with CSV import, change to main scope
USER_MAPPING = {'jira_username': 'github_username'}


def create_github_issues(github_api: github.MainClass.Github,
                         github_issues: list,
                         milestone_mapping: dict,
                         project_mapping: dict):
  """Recreates provided Jira issues on GitHub Issues."""

  # Create all issues in GitHub
  repo = github_api.get_repo(FLAGS.github_repo)

  for issue in github_issues:
    jira_id = issue.get('jira_id')

    # Populate milestone info
    milestone_data = issue.get('milestone')
    milestone = github.GithubObject.NotSet
    if milestone_data:
      try:
        milestone_name = milestone_data.get('name')
        milestone = repo.get_milestone(milestone_mapping[milestone_name])
      except KeyError as e:
        logging.error('Unable to fetch milestone for Jira issue %s, skipping...',
                      jira_id)


    logging.info('Migrating issue %s from Jira to GitHub...', jira_id)

    try:
      # Populate initial information
      migrated_issue = repo.create_issue(title=issue.get('title'),
                                         body=issue.get('body'),
                                         assignee=issue.get('assignee'),
                                         labels=issue.get('labels'))

      # Add state / milestone
      migrated_issue.edit(state=issue.get('state'),
                          milestone=milestone)

      # Map issue to project board / columns
      project_name = issue.get('project').get('name')
      project_id = project_mapping[project_name]

      project = github_api.get_project(id=project_id)
      columns = project.get_columns()

      for column in columns:
        issue_column = issue.get('status')
        if issue_column == column.name:
          column.create_card(content_id=migrated_issue.id,
                             content_type='Issue')

      # Add comments to created issue
      for comment in issue.get('comments'):
        migrated_issue.create_comment(comment)

      logging.info('Successfully migrated Jira issue %s as GitHub issue %s',
                   jira_id,
                   migrated_issue.number)
    except github.GithubException as e:
      logging.error('Failed to migrate Jira issue %s: %s', jira_id, e)


def create_github_milestones(github_api: github.MainClass.Github,
                             github_milestones: list) -> dict:
  """Recreates provided Jira sprints as GitHub milestones."""

  # Create milestones via GitHub API
  logging.info('Populating %s Jira sprint(s) as GitHub milestones...',
               len(github_milestones))
  milestone_mapping = {}
  repo = github_api.get_repo(FLAGS.github_repo)

  for milestone in github_milestones:
    milestone_name = milestone[0]
    milestone_desc = milestone[1]
    milestone_due_date = parser.parse(milestone[2])

    try:
      migrated_milestone = repo.create_milestone(title=milestone_name,
                                                 description=milestone_desc,
                                                 due_on=milestone_due_date)
      milestone_mapping[migrated_milestone.title] = migrated_milestone.number
      logging.info('Created GitHub milestone %s.', migrated_milestone.title)
    except github.GithubException as e:
      logging.error('Failed to create milestone: %s', e)

  return milestone_mapping


def create_github_projects(github_api: github.MainClass.Github,
                           github_projects: list,
                           github_statuses: list) -> dict:
  """Recreates Jira projects as GitHub projects"""

  # Create projects via GitHub API
  logging.info('Populating %s Jira project(s) as GitHub projects...',
               len(github_projects))
  project_mapping = {}
  repo = github_api.get_repo(FLAGS.github_repo)

  for project in github_projects:
    description = 'Migrated from Jira project %s.' % project
    try:
      migrated_project = repo.create_project(name=project, body=description)
      logging.info('Created GitHub project %s.', project)

      migrated_columns = {}
      for column in github_statuses:
        migrated_column = migrated_project.create_column(column)
        migrated_columns[migrated_column.name] = migrated_column.id
        logging.info('Added column %s to project %s', column, project)

      project_mapping[project] = migrated_project.id

    except github.GithubException as e:
      logging.error('Failed to create project %s: %s', project, e)

  return project_mapping


def extract_milestones(github_issues: list) -> list:
  """Extracts milestone information from parsed issues."""

  # Extract individual milestone fields, dedupe
  deduped_milestone_names = {
      x.get('milestone').get('name') for x in github_issues}
  deduped_milestone_descriptions = {
      x.get('milestone').get('description') for x in github_issues}
  deduped_milestone_dates = {
      x.get('milestone').get('due_date') for x in github_issues}

  # Reconstruct deduped milestone list, remove null values
  github_milestones = list(zip(deduped_milestone_names,
                               deduped_milestone_descriptions,
                               deduped_milestone_dates))
  github_milestones.remove((None, None, None))

  return github_milestones


def extract_sprint_fields(sprint_data: list) -> dict:
  """Extracts USABLE sprint info from the horrific GreenHopper API string."""

  sprint_fields = {}

  # Extract sprint data from GreenHopper string
  sprint_regex = re.search(r'\[(.*)\]', sprint_data[0])
  sprint_raw_data = sprint_regex.group(1)
  sprint_raw_fields = sprint_raw_data.split(',')

  # Populate return dict with key value pairs
  for raw_field in sprint_raw_fields:
    key_value = raw_field.split('=')
    key = key_value[0]
    value = key_value[1]
    sprint_fields[key] = value

  return sprint_fields


def map_issue_fields(jira_api: jira.client.JIRA,
                     jira_issue: jira.resources.Issue) -> dict:
  """Maps Jira issue fields to GitHub issue fields."""

  # Grab comments
  comments = []
  raw_comments = jira_api.comments(jira_issue)
  for comment in raw_comments:
    parsed_body = 'Author: %s\nCreated: %s\n\n%s' % (comment.author,
                                                     comment.created,
                                                     comment.body)
    comments.append(parsed_body)

  # Grab issue state
  state_data = jira_issue.fields.status.statusCategory.key
  if state_data == 'done':
    state = 'closed'
  else:
    state = 'open'

  # Grab sprint info
  sprint_data = jira_issue.fields.customfield_10020
  if sprint_data:
    sprint_fields = extract_sprint_fields(sprint_data)

    milestone = {
        'name': sprint_fields.get('name'),
        'due_date': sprint_fields.get('endDate'),
        'description': sprint_fields.get('goal'),
    }
  else:
    milestone = {}

  # Grab assignee info
  assignee = github.GithubObject.NotSet
  if jira_issue.fields.assignee:
    assignee = USER_MAPPING[jira_issue.fields.assignee.key]

  # Append migration message to issue body
  migration_message = 'Migrated from Jira issue %s' % jira_issue.key

  if jira_issue.fields.description:
    body = migration_message + '\n' + jira_issue.fields.description
  else:
    body = migration_message

  github_issue = {
      'jira_id': jira_issue.key,
      'title': jira_issue.fields.summary,
      'body': body,
      'comments': comments,
      'assignee': assignee,
      'labels': jira_issue.fields.labels,
      'project': {
          'key': jira_issue.fields.project.key,
          'name': jira_issue.fields.project.name,
      },
      'milestone': milestone,
      'state': state,
      'status': jira_issue.fields.status.name,
  }

  return github_issue


def convert_issues(jira_api: jira.client.JIRA,
                   max_results: int) -> list:
  """Converts Jira issues into pre-parsed GitHub issue schema"""

  github_issues = []

  # Grab result dimensions from Jira
  jira_metadata = jira_api.search_issues(FLAGS.jira_search,
                                         maxResults=1)
  result_length = jira_metadata.total
  result_index = 0

  logging.info('Converting %s issue(s) from Jira into GitHub format...',
               result_length)

  while result_index < result_length:
    jira_issues = jira_api.search_issues(FLAGS.jira_search,
                                         maxResults=max_results)
    for jira_issue in jira_issues:
      github_issue = map_issue_fields(jira_api, jira_issue)
      github_issues.append(github_issue)

    result_index += max_results

  return github_issues


def main(argv):
  """Main migration function."""

  # Delete unused argv
  del argv

  # Instantiate Jira and GitHub APIs
  logging.info('Connecting to Jira server %s as %s...',
               FLAGS.jira_server,
               FLAGS.jira_username)
  jira_api = jira.JIRA(server=FLAGS.jira_server,
                       basic_auth=(FLAGS.jira_username, FLAGS.jira_token))

  logging.info('Connecting to GitHub via access token...')
  github_api = github.Github(FLAGS.github_token)

  # Grab Jira issues, sprints, and projects convert to GitHub schema
  github_issues = convert_issues(jira_api, max_results=500)
  github_milestones = extract_milestones(github_issues)
  github_statuses = {x.get('status') for x in github_issues}
  github_projects = {x.get('project').get('name') for x in github_issues}

  # Reconstruct data on GitHub Issues
  milestone_mapping = create_github_milestones(github_api, github_milestones)
  project_mapping = create_github_projects(github_api,
                                           github_projects,
                                           github_statuses)
  create_github_issues(github_api,
                       github_issues,
                       milestone_mapping,
                       project_mapping)

  logging.info('Migration from Jira to GitHub Issues complete!')


if __name__ == '__main__':
  app.run(main)
