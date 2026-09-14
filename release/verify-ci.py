#!/usr/bin/env python3
"""Require successful normal CI for the exact production release commit."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

WORKFLOW_PATH = '.github/workflows/ci.yml'
WORKFLOW_EVENT = 'push'
EXPECTED_JOB = 'test'
RESPONSE_LIMIT = 4 * 1024 * 1024


def integer(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(f'Invalid {label}')
    return value


def newest_run(response, expected_sha):
    if not isinstance(response, dict) or not isinstance(response.get('workflow_runs'), list):
        raise ValueError('Invalid CI workflow-runs response')
    candidates = [run for run in response['workflow_runs']
                  if isinstance(run, dict)
                  and run.get('head_sha') == expected_sha
                  and run.get('path') == WORKFLOW_PATH
                  and run.get('event') == WORKFLOW_EVENT]
    if not candidates:
        raise ValueError(f'No normal CI run exists for release commit {expected_sha}')
    for run in candidates:
        integer(run.get('id'), 'CI run id')
        integer(run.get('run_number'), 'CI run number')
        integer(run.get('run_attempt'), 'CI run attempt')
    return max(candidates,
               key=lambda run: (run['run_number'], run['run_attempt'], run['id']))


def require_success(response, jobs, expected_sha):
    run = newest_run(response, expected_sha)
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        state = run.get('conclusion') or run.get('status') or 'unknown'
        raise ValueError(f'Newest normal CI run for release commit is not successful: {state}')
    if not isinstance(jobs, dict) or not isinstance(jobs.get('jobs'), list):
        raise ValueError('Invalid CI jobs response')
    selected = [job for job in jobs['jobs']
                if isinstance(job, dict) and job.get('name') == EXPECTED_JOB]
    if len(selected) != 1:
        raise ValueError(f'Expected exactly one {EXPECTED_JOB!r} CI job')
    job = selected[0]
    if job.get('status') != 'completed' or job.get('conclusion') != 'success':
        state = job.get('conclusion') or job.get('status') or 'unknown'
        raise ValueError(f'Normal CI job {EXPECTED_JOB!r} is not successful: {state}')
    return run['id']


def fetch_json(url, token):
    request = Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urlopen(request, timeout=20) as response:
            content = response.read(RESPONSE_LIMIT + 1)
    except (HTTPError, URLError, TimeoutError) as error:
        raise ValueError(f'GitHub CI lookup failed: {error}') from error
    if len(content) > RESPONSE_LIMIT:
        raise ValueError('GitHub CI response exceeds limit')
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError('GitHub CI response is not valid JSON') from error


def verify(repository, expected_sha, token, api_url='https://api.github.com'):
    workflow = quote(WORKFLOW_PATH, safe='')
    query = urlencode({'event': WORKFLOW_EVENT, 'head_sha': expected_sha, 'per_page': 100})
    runs = fetch_json(f'{api_url}/repos/{repository}/actions/workflows/{workflow}/runs?{query}',
                      token)
    run = newest_run(runs, expected_sha)
    jobs = fetch_json(
        f'{api_url}/repos/{repository}/actions/runs/{run["id"]}/jobs?filter=latest&per_page=100',
        token)
    return require_success(runs, jobs, expected_sha)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--api-url', default='https://api.github.com')
    args = parser.parse_args()
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        parser.error('GITHUB_TOKEN is required')
    try:
        run_id = verify(args.repository, args.sha, token, args.api_url.rstrip('/'))
    except ValueError as error:
        print(f'Release requires green normal CI for the exact commit: {error}', file=sys.stderr)
        print('Rerun the release after CI / test succeeds.', file=sys.stderr)
        raise SystemExit(1) from error
    print(f'Accepted successful CI / test run {run_id} for {args.sha}')
