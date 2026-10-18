# Zoho Timesheet Routine

Every night at **11:59 PM**, Claude reads **the day's meetings** from your Google Calendar. It matches each meeting to your **Zoho Projects** work and logs the hours in **Zoho People**. You check the week and submit it yourself.

---

## Setup (once)

### 1. Get your Zoho key (once, on your laptop)
Zoho never hands out a permanent key directly. It gives a **one-time code** (`ZOHO_GRANT_CODE`) that lasts a few minutes, and `scripts/zoho_auth.py` swaps it for a **permanent key** (`ZOHO_REFRESH_TOKEN`). That swap is the only reason for the code and for the `.env` file. The routine itself uses only the permanent key, stored in the cloud environment's variables.

1. Open **api-console.zoho.com** and choose **Add Client → Self Client**. Copy the **Client ID** and **Client Secret**.
2. Download this repo, then run `pip install requests`.
3. Copy `.env.example` to `.env`. Fill in `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET` and `ZOHO_USER_EMAIL`.
4. In the Self Client, open the **Generate Code** tab and enter the scope `ZOHOPEOPLE.timetracker.ALL`. Paste the code into `ZOHO_GRANT_CODE` in `.env`.
5. **Right away** (the code expires in minutes), run:
   ```
   python scripts/zoho_auth.py
   ```
   You should see `✓ Zoho People`. Your `.env` now contains `ZOHO_REFRESH_TOKEN`, and the grant code has been used up. You won't need it again unless you lose the permanent key.

### 2. Connect Claude
Open **claude.ai → Settings → Connectors** and connect **Google Calendar** and **Zoho Projects**.

### 3. Create the routine
1. In Claude, create a cloud environment and add these as its **environment variables**, copied from your `.env`:
   - `ZOHO_DC`
   - `ZOHO_CLIENT_ID`
   - `ZOHO_CLIENT_SECRET`
   - `ZOHO_REFRESH_TOKEN`
   - `ZOHO_USER_EMAIL`
2. Create a routine on this repo that uses that environment:
   - **Connectors:** Google Calendar and Zoho Projects.
   - **Prompt:**
     ```
     Run the daily routine in CLAUDE.md.
     ```
   - **Schedule:** every day at **11:59 PM** Cairo time. Routines are scheduled in UTC: use `59 21 * * *` in winter (UTC+2) and `59 20 * * *` in summer (UTC+3).

---

## Every day
Next morning, read the routine's notification. It shows the hours it logged and anything marked **NEEDS REVIEW**. Fix those items in Zoho People.

## Every week
On Friday, open Zoho People, check the week (Saturday → Friday) and **submit** it yourself.

## Redo one day
Run the routine once with the prompt:
```
Run the daily routine in CLAUDE.md for 2026-10-17.
```

---

**Safety:** the routine only *adds* time logs. It never edits, deletes or submits them, and it skips anything already logged. Keep `.env` private: it's ignored by git and must never be committed.
