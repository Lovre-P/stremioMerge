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
- Supports email/password login or pasted Stremio auth keys.
- Keeps credentials in memory only and prompts passwords/auth keys through `getpass`.
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

1. Source account login method
2. Destination account login method
3. Final confirmation after the merge preview

For each account, choose one of these login methods:

| Option | Use when |
| --- | --- |
| `1) Email + password` | You normally log into Stremio with an email and password |
| `2) Stremio auth key` | You use Facebook, Apple, or another one-click sign-in method |

Example flow:

```text
==================================================
  Stremio Account Merger
  Merge data from one account to another
  (without replacing equal or better destination progress)
==================================================

--- SOURCE account (copy FROM) ---
Login method:
  1) Email + password
  2) Stremio auth key (for Facebook/Apple/one-click sign-in)
Choose login method (1/2, default 1):
Email:
Password:

--- DESTINATION account (copy TO) ---
Login method:
  1) Email + password
  2) Stremio auth key (for Facebook/Apple/one-click sign-in)
Choose login method (1/2, default 1): 2
Auth key:

--- Fetching data from source ---
  Addons: 12 | Library: 164

--- Fetching data from destination ---
  Addons: 8 | Library: 72

--- Summary ---
  Addons to add:        4
  New library items:    126
  Overlapping items:    38 (will keep better progress)

Proceed with merge? (y/n):
```

Type `y` to start the merge. Any other input cancels without writing changes.

## Facebook / Apple / One-Click Sign-In

Facebook and Apple users may not have a Stremio password that works with the
direct API login endpoint. For these accounts, use the auth-key login option.

1. Open [Stremio Web](https://web.stremio.com/) in your browser.
2. Log in using Facebook, Apple, or your normal one-click sign-in option.
3. Open browser developer tools.
4. Go to the Console tab.
5. Paste this snippet and press Enter:

```javascript
(() => {
  const readJson = (value) => {
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  };

  const profiles = [];
  const directProfile = readJson(localStorage.getItem("profile"));
  if (directProfile?.auth?.key) {
    profiles.push(directProfile);
  }

  for (let i = 0; i < localStorage.length; i += 1) {
    const storageKey = localStorage.key(i);
    const value = readJson(localStorage.getItem(storageKey));
    if (value?.auth?.key) {
      profiles.push(value);
    }
  }

  const authKey = profiles[0]?.auth?.key;
  if (!authKey) {
    console.error("No Stremio auth key found. Make sure you are logged into Stremio Web in this browser.");
    return;
  }

  console.log(authKey);
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(authKey);
    console.log("Auth key copied to clipboard.");
  }
})();
```

6. Run this script and choose `2) Stremio auth key`.
7. Paste the copied auth key when prompted.

The current official Stremio Web/Core source exposes Facebook and Apple auth
paths. Google login was not visible in the official source checked for this
feature. If Stremio later adds Google and still stores a normal `authKey`, this
auth-key mode should work for Google accounts too.

The auth key is a session secret. Treat it like a password: do not share it,
publish it, or paste it into tools you do not trust.

## Email / Password Login

If you log into Stremio with email and password, choose option `1`. The script
first tries Stremio's common hashed-password login format, then falls back to the
plain password format for compatibility.

```text
--- SOURCE account (copy FROM) ---
Login method:
  1) Email + password
  2) Stremio auth key (for Facebook/Apple/one-click sign-in)
Choose login method (1/2, default 1):
Email:
Password:
```

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
| Password login | `login_with_password()` | Logs in with email/password and returns a temporary Stremio auth key |
| Auth-key login | `login_with_token()` | Validates a pasted auth key through `loginWithToken` |
| Account prompt | `prompt_account_auth()` | Lets each account use password login or auth-key login |
| Fetch library | `fetch_library()` | Downloads and normalizes library items by ID |
| Fetch addons | `fetch_addons()` | Downloads the account addon collection |
| Compare progress | `has_better_progress()` | Decides whether destination progress should be kept |
| Merge addons | `merge_addons()` | Appends source addons missing from the destination |
| Merge library | `merge_library()` | Imports new or better-progress source library items |
| Run workflow | `main()` | Handles prompts, preview, confirmation, and merge order |

## Troubleshooting

### Login fails

Check that the email and password are correct and that you can log into Stremio
normally. If your account uses Facebook, Apple, or another one-click sign-in
method, use option `2) Stremio auth key` instead of password login.

### Auth key login fails

Make sure the auth key was copied from a browser session that is currently
logged into Stremio Web. If you logged out, cleared browser storage, or copied
from the wrong browser profile, open Stremio Web again and generate a fresh key.

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
- Auth keys are entered through hidden terminal prompts.
- Passwords and auth keys are not written to files by this script.
- Account auth keys only live in memory during the script run.
- A Stremio auth key can access your account through the Stremio API, so treat
  it like a password.
- The script uses Stremio account API endpoints directly, so use it only on
  machines and networks you trust.

## Disclaimer

This is an unofficial utility. Review the code before running it, especially
because it writes data to the destination Stremio account after confirmation.
