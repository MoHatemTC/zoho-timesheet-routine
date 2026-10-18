#!/usr/bin/env python
"""
Zoho OAuth helper for Zoho People (write target) + Zoho Projects (read source).
Ported from ../claude tiemsheets/zoho_auth.py.

One-time setup (local machine): paste a fresh grant code into ZOHO_GRANT_CODE in .env, then
IMMEDIATELY run
    python zoho_auth.py
It exchanges the code for a refresh token, writes it back into .env (clearing the used
code), drops the cached access token, and smoke-tests both APIs read-only.
Secrets are never printed.

Cloud routines have no .env file: set the same keys (see .env.example) as environment
variables and `python zoho_auth.py` just runs the smoke tests.

Other scripts import `people_get`, `people_get_all`, `projects_get` and `load_env` from here.
"""

import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, '.env')
TOKEN_CACHE = os.path.join(HERE, 'data', '.access_token.json')  # data/ is gitignored

# Self Client -> Generate Code -> paste this whole string as the scope
SCOPES = ('ZOHOPEOPLE.timetracker.ALL,'
          'ZohoProjects.portals.READ,ZohoProjects.projects.READ,ZohoProjects.tasklists.READ,'
          'ZohoProjects.tasks.READ,ZohoProjects.users.READ,ZohoProjects.timesheets.READ')

# ✓/✘ must survive cp1252 consoles and piped output on Windows
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding='utf-8')


# ──────────────────────────────────────────────────────────────────────────────
# .env handling (no python-dotenv dependency)
# ──────────────────────────────────────────────────────────────────────────────
ENV_KEYS = ('ZOHO_DC', 'ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET', 'ZOHO_GRANT_CODE', 'ZOHO_REFRESH_TOKEN',
            'ZOHO_USER_EMAIL', 'ZOHO_PROJECTS_PORTAL_ID', 'GOOGLE_CALENDAR_ICS_URL')


def load_env():
    """.env values (local runs), overridden by real environment variables (cloud routines)."""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding='utf-8') as f:
            for line in f:
                m = re.match(r'\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$', line)
                if m:
                    env[m.group(1)] = m.group(2).strip('"').strip("'")
    # real environment variables win
    for k in set(env) | set(ENV_KEYS):
        if os.getenv(k) is not None:
            env[k] = os.getenv(k)
    return env


def set_env_value(key, value):
    with open(ENV_PATH, encoding='utf-8') as f:
        text = f.read()
    pattern = re.compile(rf'^{key}\s*=.*$', re.MULTILINE)
    line = f'{key}={value}'
    text = pattern.sub(lambda _: line, text) if pattern.search(text) else text.rstrip('\n') + f'\n{line}\n'
    with open(ENV_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def _dc(env):
    return env.get('ZOHO_DC') or 'com'


def accounts_url(env):
    return f"https://accounts.zoho.{_dc(env)}"


def people_url(env=None):
    env = env or load_env()
    return f"https://people.zoho.{_dc(env)}/people/api"


def projects_url(env=None):
    env = env or load_env()
    portal = env.get('ZOHO_PROJECTS_PORTAL_ID')
    if not portal:
        sys.exit("✘ ZOHO_PROJECTS_PORTAL_ID missing in .env / the environment.")
    return f"https://projectsapi.zoho.{_dc(env)}/api/v3/portal/{portal}"


# ──────────────────────────────────────────────────────────────────────────────
# OAuth
# ──────────────────────────────────────────────────────────────────────────────
def _token_request(env, **params):
    r = requests.post(f"{accounts_url(env)}/oauth/v2/token", timeout=30, params={
        'client_id': env.get('ZOHO_CLIENT_ID'),
        'client_secret': env.get('ZOHO_CLIENT_SECRET'),
        **params,
    })
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"✘ Token endpoint returned HTTP {r.status_code}, non-JSON body — check ZOHO_DC.")
    if 'error' in data:
        hints = {
            'invalid_code': "grant code expired or already used — generate a new one and rerun right away.",
            'invalid_client': "client id/secret wrong, OR ZOHO_DC doesn't match the console you created the client in.",
            'invalid_client_secret': "client secret is wrong.",
            'Access Denied': "too many token refreshes (~10 per 10 min) — wait 10 minutes.",
        }
        sys.exit(f"✘ Zoho OAuth error: {data['error']}\n  {hints.get(data['error'], '')}")
    return data


def exchange_grant_code(env):
    data = _token_request(env, grant_type='authorization_code', code=env['ZOHO_GRANT_CODE'])
    if 'refresh_token' not in data:
        sys.exit("✘ No refresh_token in the response (Zoho returns it only on the first exchange "
                 "of a fresh code). Generate a new grant code and rerun.")
    set_env_value('ZOHO_REFRESH_TOKEN', data['refresh_token'])
    set_env_value('ZOHO_GRANT_CODE', '')
    # the cached access token carries the OLD scopes — drop it
    if os.path.exists(TOKEN_CACHE):
        os.remove(TOKEN_CACHE)
    print(f"✓ Refresh token saved to .env; grant code cleared.\n  scope: {data.get('scope', '?')}")


_TOKEN = {'value': None, 'expires': 0}


def access_token(env=None):
    """Access tokens live 1h and Zoho denies refreshes beyond ~10 per 10 min ("Access Denied"),
    so reuse one token per process AND across processes via a small on-disk cache."""
    if _TOKEN['value'] and time.time() < _TOKEN['expires']:
        return _TOKEN['value']
    try:
        with open(TOKEN_CACHE, encoding='utf-8') as f:
            cached = json.load(f)
        if time.time() < cached['expires']:
            _TOKEN.update(cached)
            return _TOKEN['value']
    except (OSError, ValueError, KeyError):
        pass
    env = env or load_env()
    if not env.get('ZOHO_REFRESH_TOKEN'):
        sys.exit("✘ No ZOHO_REFRESH_TOKEN in .env or the environment — run `python zoho_auth.py` locally first.")
    data = _token_request(env, grant_type='refresh_token', refresh_token=env['ZOHO_REFRESH_TOKEN'])
    _TOKEN.update(value=data['access_token'], expires=time.time() + int(data.get('expires_in', 3600)) - 120)
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    with open(TOKEN_CACHE, 'w', encoding='utf-8') as f:
        json.dump(_TOKEN, f)
    return _TOKEN['value']


def _headers():
    return {'Authorization': f'Zoho-oauthtoken {access_token()}'}


class ZohoError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Zoho People
# ──────────────────────────────────────────────────────────────────────────────
def people_get(path, _method='GET', **params):
    """Call people/api/<path>; returns response.result or raises ZohoError with Zoho's own message."""
    r = requests.request(_method, f"{people_url()}/{path}", timeout=60, params=params, headers=_headers())
    try:
        resp = r.json().get('response', {})
    except ValueError:
        raise ZohoError(f"HTTP {r.status_code}: {r.text[:300]}")
    if resp.get('status') != 0:
        raise ZohoError(f"HTTP {r.status_code}: {resp.get('errors') or resp.get('message') or resp}")
    return resp.get('result')


def people_get_all(path, **params):
    """Follow sIndex/limit pagination (max 200 per page). sIndex is 1-based: 0 and 1 both
    return the first record, so pages start at 1, 201, 401… (starting at 0 re-reads record 200)."""
    rows, start = [], 1
    while True:
        page = people_get(path, sIndex=start, limit=200, **params) or []
        rows.extend(page)
        if len(page) < 200:
            return rows
        start += 200


# ──────────────────────────────────────────────────────────────────────────────
# Zoho Projects (V3, read-only)
# ──────────────────────────────────────────────────────────────────────────────
def projects_get(path, **params):
    """GET <projectsapi>/api/v3/portal/<portal>/<path>; returns the parsed JSON body."""
    r = requests.get(f"{projects_url()}/{path.lstrip('/')}", timeout=60, params=params, headers=_headers())
    if r.status_code == 204:
        return {}
    try:
        body = r.json()
    except ValueError:
        raise ZohoError(f"HTTP {r.status_code}: {r.text[:300]}")
    if not r.ok:
        raise ZohoError(f"HTTP {r.status_code}: {body.get('error') or body}")
    return body


# ──────────────────────────────────────────────────────────────────────────────
def main():
    env = load_env()

    missing = [k for k in ('ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET') if not env.get(k)]
    if missing:
        sys.exit(f"✘ Set {', '.join(missing)} in .env or the environment first.")

    if env.get('ZOHO_GRANT_CODE'):
        # check BEFORE exchanging: a grant code works once, and the refresh token must land somewhere
        if not os.path.exists(ENV_PATH):
            sys.exit("✘ Exchange grant codes on a local machine with a .env file; routines read "
                     "ZOHO_REFRESH_TOKEN from the environment instead.")
        exchange_grant_code(env)
        env = load_env()
    elif not env.get('ZOHO_REFRESH_TOKEN'):
        sys.exit("✘ Neither ZOHO_GRANT_CODE nor ZOHO_REFRESH_TOKEN is set (.env or environment).")

    access_token(env)
    print("✓ Access token obtained.")

    # read-only smoke tests
    ok = True
    try:
        projects = people_get_all('timetracker/getprojects', assignedTo=env.get('ZOHO_USER_EMAIL'))
        print(f"✓ Zoho People — {len(projects)} project(s) assigned to {env.get('ZOHO_USER_EMAIL')}.")
    except ZohoError as e:
        ok = False
        print(f"✘ Zoho People: {e}")
    try:
        body = projects_get('projects', page=1, per_page=100)
        n = len(body.get('projects', body) if isinstance(body, dict) else body)
        print(f"✓ Zoho Projects — portal {env.get('ZOHO_PROJECTS_PORTAL_ID')} reachable, {n} project(s) on page 1.")
    except ZohoError as e:
        ok = False
        hint = ("\n  The refresh token lacks Zoho Projects scopes. Generate a new grant code with:\n  "
                + SCOPES) if 'scope' in str(e).lower() else ''
        print(f"✘ Zoho Projects: {e}{hint}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
