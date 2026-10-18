# Timesheet automation: Calendar + Zoho Projects → Zoho People

## What this project is

This project builds my weekly Zoho People timesheet from live sources, so I no longer export Clockify by hand:

1. **Calendar.** Read my calendar for the week. Each meeting gives a time block with a title.
2. **Zoho Projects.** Read the projects and jobs (tasks) I'm assigned to and that are still In-Progress.
3. **Map.** Map every time block to exactly one Zoho People job. Build a preview and show it to me.
4. **Push.** After my go-ahead, add the time logs to Zoho People through the API and verify them against live Zoho.
5. **Submit.** Only after a *second*, separate go-ahead, submit the week for approval.

**Repo:** https://github.com/MoHatemTC/zoho-timesheet-routine. It's used from Claude routines and shared with the team.

**Status (18 Oct 2026):**
- Built so far: `zoho_auth.py`, `.env.example` and `.gitignore`. `python zoho_auth.py` exchanges a grant code (local only) and smoke-tests both Zoho APIs, read-only.
- Zoho People works.
- Zoho Projects returns 401 INVALID_OAUTHSCOPE until a new grant code with `zoho_auth.SCOPES` has been exchanged.
- Google Calendar isn't connected: `GOOGLE_CALENDAR_ICS_URL` is empty.
- Not built yet: discover, fetch_calendar, build_preview, push and submit.

**Predecessor:** `../claude tiemsheets/`, which exists only on the owner's machine. It is not in this repo, and a cloud routine can't read it. It takes a Clockify CSV and pushes it to Zoho People through the API. It works and has handled every week up to and including Sat 26 Sep – Fri 2 Oct 2026. Port its code and rules rather than rediscovering them:

| File there | What to reuse |
|---|---|
| `zoho_auth.py` | `.env` loader, OAuth refresh with on-disk token cache, `api_get`, `api_get_all` (pagination) |
| `zoho_discover.py` | Snapshots of projects, jobs and timelogs into `data/` |
| `mapping_rules.py` | Ordered regex rules that map text to a job key, `since=` date gates, `SPLITS` (80/20, 50/50), plus every mapping call I've already made. Don't re-ask those. |
| `typos.py` | Spelling cleanup for descriptions |
| `build_preview.py` | Builds weekly previews into `previews/vN/`; resolves jobs (In-Progress only, exactly one match) |
| `zoho_push.py` | Throttled writes, ledger, `--sync` (edit in place, delete only on dates the preview covers), `--undo-week` |
| `zoho_submit.py` | One timesheet per project, named exactly like the Zoho UI names them |
| `verify_all.py` | Cross-check against live Zoho. The UI can change logs behind the ledger's back. |

Copy what you need into this folder. Don't import across folders, and don't modify the old one. It holds the ledger for every week pushed so far.

## Hard rules

- **Dry run by default.** Any Zoho write (`addtimelog`, `edittimelog`, `deletetimelog`, `createtimesheet`) needs both an `--execute` flag and my explicit OK *for that week* in the conversation.
- **Pushing and submitting are separate go-aheads.** I review each week's preview before anything is pushed, and again before it is submitted.
- **The week runs Saturday → Friday**, target ≈ 80h. Older sheets in Zoho use Sun → Sat ranges; don't let them confuse you.
- **One log per job per day.** Never move a log to another date, and never merge logs across days.
- **Description format:** one comma-separated line in my own wording. Keep it chronological, remove duplicates and clean the spelling, e.g. `ILF call heba, ILF meeting weekly, squad comm`.
- **Only In-Progress jobs.** Resolve job ids from a fresh `getjobs` snapshot on every run. Never hard-code ids.
- **Never overwrite outputs.** Previews go to `previews/vN/` with the next free N; snapshots get a timestamp in their filename.
- **Live Zoho is the source of truth for what's already logged.** Dedupe against `gettimelogs` for the week, not just a local ledger. The old pipeline keeps its own ledger in `../claude tiemsheets/data/push_ledger.csv`, which this project can't see.
- **Secrets live only in `.env` (local runs) or in environment variables (cloud routines). Token caches live in `data/`.** The repo's `.gitignore` ignores `.env` and `data/`. **The repo is public**, so never print, echo or commit secret values. When checking setup, read key names only.
- **A routine run is unattended.** It may only run read-only steps and build the preview. It never passes `--execute`. It finishes by reporting the preview and totals, so I can give the go-ahead in a live session.

## Sources and access

### Zoho People: target for reads and writes (works today)
- Base URL: `https://people.zoho.com/people/api` (data centre `com`).
- Auth: OAuth Self Client, header `Authorization: Zoho-oauthtoken <access token>`, scope `ZOHOPEOPLE.timetracker.ALL`. A single token covers People and Projects once it carries `zoho_auth.SCOPES`.
- Credentials:
  - Local runs: `.env`, copied from `.env.example`.
  - Cloud routines: the same keys as environment variables. `zoho_auth.load_env()` reads both, and environment variables win.
  - Grant codes can only be exchanged locally, because the refresh token is written back into `.env`.
  - Keys:
    - `ZOHO_DC`
    - `ZOHO_CLIENT_ID`
    - `ZOHO_CLIENT_SECRET`
    - `ZOHO_GRANT_CODE`
    - `ZOHO_REFRESH_TOKEN`
    - `ZOHO_USER_EMAIL`
    - `ZOHO_PROJECTS_PORTAL_ID`
    - `GOOGLE_CALENDAR_ICS_URL`
- Endpoints, all under `timetracker/`:

| Endpoint | Key parameters |
|---|---|
| `getprojects` | `assignedTo` |
| `getjobs` | `assignedTo`, `dateFormat=yyyy-MM-dd` |
| `gettimelogs` | `user`, `fromDate`, `toDate`, `billingStatus=all` |
| `addtimelog` | `user`, `jobId`, `workDate`, `hours=HH:MM`, `description` |
| `edittimelog` | `timeLogId`, plus `workDate` + `jobId` (required in practice) |
| `deletetimelog` | `timeLogId` (comma-separated, ≤200) |
| `gettimesheet` | — |
| `createtimesheet` | `sendforApproval=true` |

### Zoho Projects: read source (decided 11 Oct: read it directly)
- Every Zoho People project and job is **synced from Zoho Projects** (portal `782665901`, `ZOHO_PROJECTS_PORTAL_ID` in `.env`). Each record carries `zProjectsPortalId`, `zProjectsProjectRefId` and `zProjectsJobRefId`; use these to join a Projects task to the People `jobId` we log against.
- Time logged in Zoho People is pushed back to Zoho Projects (`isTimelogPushedToZP`), so **never log time in Zoho Projects directly**: it would double-count.
- **Read** my projects and tasks from the Zoho Projects V3 API. **Write** only to Zoho People.
- Base URL: `https://projectsapi.zoho.com/api/v3/portal/{portal}/`. Use `zoho_auth.projects_get()`.
- Paths seen in the V3 docs:
  - `projects`
  - `projects/{id}/tasks`
  - `projects/{id}/users`
  - `users`
  - `users/{id}/projects`
  - `mytasks/customviews`
  - `logs`
  Confirm the filters and paging live; the old `restapi` is being deprecated.
- Scopes, verified against the V3 docs on 11 Oct, held in `zoho_auth.SCOPES`:
  - `ZOHOPEOPLE.timetracker.ALL`
  - `ZohoProjects.portals.READ`
  - `ZohoProjects.projects.READ`
  - `ZohoProjects.tasklists.READ`
  - `ZohoProjects.tasks.READ`
  - `ZohoProjects.users.READ`
  - `ZohoProjects.timesheets.READ`

  A new grant code must request **all** of these. Leaving out the People scope would break the writes.

### Google Calendar: meetings (decided 11 Oct; not connected yet)
Route: the **secret iCal address**. Google Calendar → Settings → my calendar → *Integrate calendar* → *Secret address in iCal format*. It's read-only and needs no OAuth. It goes in `GOOGLE_CALENDAR_ICS_URL` in `.env` and is a secret.
- Expand recurring events with `recurring_ical_events`; weekly meetings are RRULEs, and a plain parse would miss them.
- Read my RSVP from the `ATTENDEE;PARTSTAT` entry that matches my email.
- Not installed yet: `pip install icalendar recurring-ical-events`.
- Fallback, if the admin has disabled secret addresses: a Google Cloud *Desktop app* OAuth client with scope `https://www.googleapis.com/auth/calendar.readonly`. Keep `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`; cache the token in `data/google_token.json`.

Calendar rules:
- Convert every event to **Africa/Cairo** with `zoneinfo` before choosing its `workDate`. Egypt has DST, so never use a fixed UTC offset.
- Skip:
  - events I declined
  - cancelled events
  - all-day events and out-of-office blocks
  - events with no other attendees, unless they're clearly work blocks
- Show overlapping events in the review. Don't silently drop or trim them.

## Pipeline (planned)

1. `auth_check`: smoke-test every source with read-only calls.
2. `discover`: snapshot projects, In-Progress jobs and the week's existing timelogs. Also pull 2–3 months of **approved** timelogs, the best guide to how my manager expects work to be categorised.
3. `fetch_calendar --week <Sat date>`: write the week's events to `data/`.
4. `build_preview`:
   - Map each event title to a job, using the ported mapping rules plus approved history.
   - Use the Zoho Projects task names in my In-Progress projects as extra matching vocabulary.
   - Flag anything unmatched for my review; don't guess silently.
   - Only work meetings are logged, with no gap-filling (decision 1). Show the daily and weekly totals so I can see the shortfall against 80h.
   - Write `previews/vN/week_<sat>_to_<fri>.csv`.
5. **I review**, and the rules get updated with my calls (each gated with `since=` so pushed weeks can't re-map).
6. `push --week <sat>`: dry run, then `--execute`; then verify the minutes against live `gettimelogs`.
7. `submit --from <sat> --to <fri>`: dry run, then `--execute`. Creates one timesheet per project named `Timesheet (dd/mm/yyyy - dd/mm/yyyy)`. Only on my explicit go-ahead.

## Zoho API gotchas (learned the hard way)

**Rate limits**
- At most 20 write calls per minute; going over locks the API for 5 minutes. Pace writes at about 17 per minute (one every 3.6 s).
- Token refreshes are capped at about 10 per 10 minutes; beyond that the token endpoint answers "Access Denied". Cache the access token on disk (`data/.access_token.json`) and reuse it across processes.

**Endpoint quirks**
- `gettimelogs` returns at most one month per call; split ranges on calendar months.
- `sIndex` is **1-based**, so pages start at 1, 201, 401…
- `edittimelog` fails with error 8000 unless both `workDate` and `jobId` are sent.
- It's `gettimesheet` (singular). `gettimesheets` returns 404.

**Things that can't be changed**
- Approved logs are locked (`isEditAllowed` / `isDeleteAllowed` are False). Work around them; don't try to edit them.

**Org behaviour verified 14 Sep 2026**
- Logging up to 7 weeks back works.
- Weekends aren't rejected. If one is, move the log to the nearest open day and note it in the description.
- Dates outside a job's from/to window are accepted.

**Sync safety**
- Never `--sync` with a partial-week preview. Sync may only delete logs on dates the preview actually covers.

**Python**
- Write regexes as raw strings. A `'\\b'` string patched in through `python -c` once became a literal backspace.

## Decisions (11 Oct 2026)

1. **Work = work meetings.** The timesheet is built from the work meetings on my calendar. Each meeting's duration is logged to the job it maps to. Non-work events are skipped, and nothing is invented to fill the gaps.
2. **Calendar = Google Calendar**, read through the secret iCal address (see above).
3. **Zoho Projects is read directly** through the V3 API for my projects and tasks. Writes go to Zoho People only.
4. **First week = Sat 3 Oct – Fri 9 Oct 2026.** I answered "Fri 9/10/2026", read as the week ending that Friday. Live `gettimelogs` showed nothing logged from 3–10 Oct; 26 Sep – 2 Oct is fully logged (62 logs, approved or pending).
