# Zoho timesheet routine

Every night at **11:59 PM Cairo time**, a Claude routine logs **that day's work meetings** into Zoho People as time logs.

1. It reads the meetings from Google Calendar.
2. It checks Zoho Projects and my recent Zoho People logs, to pick the same jobs and wording I already use.
3. It adds the logs.

I review the week and submit it myself.

| Source | How it's reached | Used for |
|---|---|---|
| Google Calendar | Claude connector | read meetings |
| Zoho Projects | Claude connector | read my projects and tasks |
| Zoho People | API through `scripts/zoho_auth.py` | read logs and jobs, add time logs |

## Daily routine

The routine prompt is one line: `Run the daily routine in CLAUDE.md.` To redo one day, it can add a date: `... for 2026-10-17`.

- **Target day:** today's date in Africa/Cairo time (the routine runs at 11:59 PM).
  - If the run starts after midnight but before 06:00 Cairo time (a late start, or the summer-time hour shift), the target day is **yesterday**.
  - If the prompt names a date (YYYY-MM-DD), that date only.
  - Get the time with `python -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo('Africa/Cairo')))"`. Never assume the machine's clock is Cairo time.
- **This section is my standing OK** to add time logs for the target day. Nothing else may be written.

### 1. Log in
From the repo root, run `pip install requests`, then `python scripts/zoho_auth.py`. It must print `✓ Zoho People`. If it doesn't, stop and send me a notification with the error.

The `zoho_auth.…` calls below are Python helpers in `scripts/zoho_auth.py`. From the repo root, load them with `import sys; sys.path.insert(0, 'scripts'); import zoho_auth`.

### 2. Learn how I log my time (Zoho People + Zoho Projects)
Before mapping anything, line up with what I've already logged and submitted:
- `zoho_auth.timelogs(<target − 14 days>, <target − 1 day>)` returns my logs from the two weeks before. For each kind of meeting, note:
  - which project and job I used,
  - how I wrote the description,
  - how many hours.

  Logs with `approvalStatus` = `approved` are the strongest guide, because my manager accepted them.
- `zoho_auth.jobs()` returns my In-Progress jobs. Only these can be logged against.
- **Zoho Projects connector:**
  - Call `get_portals` to get the portal id.
  - Then list my open tasks (owner = me) and their projects.
  - Use them to understand what each job is for, and to match meeting titles to the right project.
- `zoho_auth.timelogs(<target>, <target>)` returns what's already logged on the target day.

### 3. Read the meetings (Google Calendar connector)
List my events from 00:00 to 23:59 Cairo time on the target day.
- **Skip:**
  - declined or cancelled events
  - all-day and out-of-office events
  - events I'm not attending
  - non-work events
- **Flag** overlapping meetings in the report instead of dropping them.

### 4. Map meetings to jobs
- Map each meeting to exactly one In-Progress job, chosen the way I chose for similar meetings in step 2.
- **One log per job per day.** Add up the meetings that go to the same job; hours are written `HH:MM`.
- **Description** is one comma-separated line of the meeting titles in my wording: chronological, no duplicates, spelling fixed. Example: `weekly squad meeting, sync with content team, demo prep`.
- **Not sure?** Mark the row `NEEDS REVIEW`. Don't guess.

### 5. Push
- Skip any job that already has a log on the target day (from step 2). Never log the same job twice in a day.
- For every other row not marked `NEEDS REVIEW`, call `zoho_auth.add_timelog(job_id, '<target>', 'HH:MM', description)`.
- If a call fails, stop and report the error. Don't retry with different values.

### 6. Check and report
- Read the day back with `zoho_auth.timelogs(<target>, <target>)`.
- Report:
  - a table with project, job, hours, description, source meetings and status (`pushed` / `already logged` / `NEEDS REVIEW`),
  - the day's total,
  - the skipped events, each with its reason.
- Send me a push notification with the hours logged, the number of logs and anything that needs my decision. If there were no meetings, say: "No work meetings on <day>, nothing logged."

## Rules
- **Write only to Zoho People, and only with `add_timelog`.**
  - Never edit, delete or submit time logs: no `edittimelog`, `deletetimelog` or `createtimesheet`.
  - I submit the week myself in Zoho People.
- Never push a `NEEDS REVIEW` row.
- Never move a log to another date.
- Never log a meeting that hasn't ended yet.
- Log only work meetings from the calendar, and don't invent hours to fill gaps.
- Never commit to this repo from a routine.
- Secrets live in environment variables (routine) or `.env` (laptop). **The repo is public**, so never print, echo or commit them.

## Zoho facts
- The week runs **Saturday → Friday** (Sprints convention), so timesheets cover Sat–Fri ranges.
- Approved logs are locked; leave them alone.
- **Writes:** at most 20 per minute, or the API locks for 5 minutes. `add_timelog` already waits 3.6 s between calls.
- **Token refreshes:** about 10 per 10 minutes. `scripts/zoho_auth.py` caches the token, so don't refresh in a loop.
- `timelogs()` covers at most one month per call.
