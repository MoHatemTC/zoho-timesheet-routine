#!/usr/bin/env python
"""
Zoho People login + the three calls the daily routine needs.

One-time setup (your laptop): put ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_USER_EMAIL and a
fresh ZOHO_GRANT_CODE in .env, then IMMEDIATELY run
    python zoho_auth.py
It swaps the grant code for a refresh token, saves it in .env, and runs a read-only check.

Routines have no .env file: set the same keys as environment variables (see .env.example)
and `python zoho_auth.py` just runs the check. Secrets are never printed.

Google Calendar and Zoho Projects are read through Claude connectors, not from here.
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

SCOPE = 'ZOHOPEOPLE.timetracker.ALL'  # Self Client -> Generate Code -> scope
ENV_KEYS = ('ZOHO_DC', 'ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET', 'ZOHO_GRANT_CODE', 'ZOHO_REFRESH_TOKEN',
            'ZOHO_USER_EMAIL')
WRITE_INTERVAL = 3.6  # seconds between writes: Zoho locks the API for 5 min above 20 writes/min

# ✓/✘ must survive cp1252 consoles and piped output on Windows
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding='utf-8')


# ──────────────────────────────────────────────────────────────────────────────
# settings: .env (laptop) or environment variables (routine)
# ──────────────────────────────────────────────────────────────────────────────
def load_env():
    """.env values, overridden by real environment variables."""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding='utf-8') as f:
            for line in f:
                m = re.match(r'\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$', line)
                if m:
                    env[m.group(1)] = m.group(2).strip('"').strip("'")
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


def people_url(env=None):
    env = env or load_env()
    return f"https://people.zoho.{_dc(env)}/people/api"


# ──────────────────────────────────────────────────────────────────────────────
# OAuth
# ──────────────────────────────────────────────────────────────────────────────
def _token_request(env, **params):
    r = requests.post(f"https://accounts.zoho.{_dc(env)}/oauth/v2/token", timeout=30, params={
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
    if os.path.exists(TOKEN_CACHE):
        os.remove(TOKEN_CACHE)
    print(f"✓ Refresh token saved to .env; grant code cleared (scope: {data.get('scope', '?')}).")


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
        sys.exit("✘ No ZOHO_REFRESH_TOKEN in .env or the environment — run `python zoho_auth.py` on your laptop first.")
    data = _token_request(env, grant_type='refresh_token', refresh_token=env['ZOHO_REFRESH_TOKEN'])
    _TOKEN.update(value=data['access_token'], expires=time.time() + int(data.get('expires_in', 3600)) - 120)
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    with open(TOKEN_CACHE, 'w', encoding='utf-8') as f:
        json.dump(_TOKEN, f)
    return _TOKEN['value']


class ZohoError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Zoho People API
# ──────────────────────────────────────────────────────────────────────────────
def people_get(path, _method='GET', **params):
    """Call people/api/<path>; returns response.result or raises ZohoError with Zoho's own message."""
    r = requests.request(_method, f"{people_url()}/{path}", timeout=60, params=params,
                         headers={'Authorization': f'Zoho-oauthtoken {access_token()}'})
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


def jobs():
    """My In-Progress Zoho People jobs (the only ones time can be logged against)."""
    rows = people_get_all('timetracker/getjobs', assignedTo=load_env()['ZOHO_USER_EMAIL'], dateFormat='yyyy-MM-dd')
    return [j for j in rows if j.get('jobStatus') == 'In-Progress']


def timelogs(from_date, to_date):
    """My time logs between two yyyy-mm-dd dates (at most one month per call)."""
    return people_get_all('timetracker/gettimelogs', user=load_env()['ZOHO_USER_EMAIL'], fromDate=from_date,
                          toDate=to_date, billingStatus='all', dateFormat='yyyy-MM-dd')


_last_write = [0.0]


def add_timelog(job_id, work_date, hours, description):
    """Add ONE time log (hours as 'HH:MM'); returns its timeLogId. Paced to stay under Zoho's write limit."""
    wait = WRITE_INTERVAL - (time.time() - _last_write[0])
    if wait > 0:
        time.sleep(wait)
    _last_write[0] = time.time()
    res = people_get('timetracker/addtimelog', _method='POST', user=load_env()['ZOHO_USER_EMAIL'],
                     jobId=job_id, workDate=work_date, hours=hours, description=description)
    return res[0]['timeLogId']


# ──────────────────────────────────────────────────────────────────────────────
def main():
    env = load_env()
    missing = [k for k in ('ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET', 'ZOHO_USER_EMAIL') if not env.get(k)]
    if missing:
        sys.exit(f"✘ Set {', '.join(missing)} in .env or the environment first.")

    if env.get('ZOHO_GRANT_CODE'):
        # check BEFORE exchanging: a grant code works once, and the refresh token must land somewhere
        if not os.path.exists(ENV_PATH):
            sys.exit("✘ Exchange the grant code on your laptop (with a .env file), then copy "
                     "ZOHO_REFRESH_TOKEN into the routine's environment variables.")
        exchange_grant_code(env)
    elif not env.get('ZOHO_REFRESH_TOKEN'):
        sys.exit("✘ Neither ZOHO_GRANT_CODE nor ZOHO_REFRESH_TOKEN is set (.env or environment).")

    try:
        n = len(jobs())
    except ZohoError as e:
        sys.exit(f"✘ Zoho People: {e}")
    print(f"✓ Zoho People — logged in as {env['ZOHO_USER_EMAIL']}, {n} In-Progress job(s).")


if __name__ == '__main__':
    main()
