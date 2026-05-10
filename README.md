# Stremio Account Merger

A small interactive Python utility for copying Stremio addons and library data
from one account into another.

It is designed for account migration, backup recovery, or merging an older
Stremio account into a newer one without deleting destination data.

## What It Does

`stremio_merge.py` logs into two Stremio accounts:

- the **source** account, which is copied from
- the **destination** account, which receives missing or better data

The script then compares both accounts, shows a summary, asks for confirmation,
and imports only the data that should be added or updated.

## Safety First

The merge is one-way and conservative.

| Area | Behavior |
| --- | --- |
| Source account | Never modified |
| Destination addons | Existing addons are kept, missing source addons are appended |
| Destination library | Existing items are kept when they have equal or better progress |
| Watch progress | Source progress replaces destination progress only when it appears newer or further along |
| Deletes | The script does not delete addons, library items, or watch history |
| Confirmation | No write requests are sent until you approve the preview |

## Features

- Copies addon collections between Stremio accounts.
- Copies library items, watchlist entries, and watch progress.
- Avoids overwriting destination progress with older or identical progress.
- Retries temporary API and network failures.
- Uses batch imports for large libraries.
- Falls back to single-item imports if a batch fails.
- Keeps credentials in memory only and prompts passwords through `getpass`.
- Prints a clear merge summary before making changes.

## Requirements

- Python 3.8 or newer
- A working internet connection
- Access to both Stremio accounts
- The Python packages listed in `requirements.txt`

## Installation

Clone the repository:

```bash
git clone https://github.com/Lovre-P/stremioMerge.git
cd stremioMerge
```

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the script:

```bash
python stremio_merge.py
```

You will be asked for:

1. Source account email and password
2. Destination account email and password
3. Final confirmation after the merge preview

Example flow:

```text
==================================================
  Stremio Account Merger
  Merge data from one account to another
  (without replacing equal or better destination progress)
==================================================

--- SOURCE account (copy FROM) ---
Email:
Password:

--- DESTINATION account (copy TO) ---
Email:
Password:

--- Summary ---
  Addons to add:        4
  New library items:    126
  Overlapping items:    38 (will keep better progress)

Proceed with merge? (y/n):
```

Type `y` to start the merge. Any other input cancels without writing changes.

## How Progress Is Compared

When the same library item exists in both accounts, the script decides whether
the destination should keep its current item or receive the source item.

The destination item is kept when it has:

- more total watch time
- more completed watches
- a later `lastWatched` timestamp
- a later season and episode position
- exactly equal progress

This protects newer destination watch activity while still allowing older
accounts to fill missing history into the destination account.

## How The Script Works

The script is intentionally simple and contained in one file:

| Step | Function | Purpose |
| --- | --- | --- |
| Create HTTP client | `make_session()` | Builds a reusable `requests` session with retries |
| Call Stremio API | `api_post()` | Sends JSON POST requests and normalizes request failures |
| Authenticate | `login()` | Logs in and returns a temporary Stremio auth key |
| Fetch library | `fetch_library()` | Downloads and normalizes library items by ID |
| Fetch addons | `fetch_addons()` | Downloads the account addon collection |
| Compare progress | `has_better_progress()` | Decides whether destination progress should be kept |
| Merge addons | `merge_addons()` | Appends source addons missing from the destination |
| Merge library | `merge_library()` | Imports new or better-progress source library items |
| Run workflow | `main()` | Handles prompts, preview, confirmation, and merge order |

## Troubleshooting

### Login fails

Check that the email and password are correct and that you can log into Stremio
normally. If your account uses a login method that does not accept password
authentication, the script may not be able to authenticate it.

### The merge finishes but Stremio does not show changes

Restart Stremio and wait a moment for account data to sync. Some clients cache
account state until they are restarted.

### A few library items fail

The script retries failed batches item by item. If failures remain, they are
counted in the final output. Temporary API issues can usually be resolved by
running the script again.

### Addon import behaves unexpectedly

Addons are matched by `transportUrl`. If two addons have different URLs but
represent the same catalog or provider, Stremio may still treat them as separate
addon entries.

## Privacy And Security Notes

- Passwords are entered through hidden terminal prompts.
- Passwords and auth keys are not written to files by this script.
- Account auth keys only live in memory during the script run.
- The script uses Stremio account API endpoints directly, so use it only on
  machines and networks you trust.

## Disclaimer

This is an unofficial utility. Review the code before running it, especially
because it writes data to the destination Stremio account after confirmation.
