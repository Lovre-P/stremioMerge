#!/usr/bin/env python3
"""
Stremio Account Merger

This script copies selected account data from one Stremio account into another.
It imports addon configuration and library items such as watchlist entries and
watch progress, while protecting destination data that already has equal or
better progress.

The script is intentionally interactive: it asks for both accounts, previews the
number of changes, and only writes to the destination account after confirmation.

Usage:
    python stremio_merge.py
"""

import getpass
import hashlib
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Base URL for Stremio's public account API. Every helper below builds its
# endpoint URL from this constant so the API host is defined in one place.
API_BASE = "https://api.strem.io/api"


def make_session():
    """
    Create a reusable HTTP session with automatic retries.

    Stremio account operations are network-bound and may occasionally hit a
    temporary 5xx response. Using a shared session keeps connections efficient,
    and the retry adapter gives short-lived server or gateway failures a chance
    to recover before the script reports an error.
    """
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods={"POST"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# One global session is enough because the script runs sequentially. Keeping it
# at module scope avoids recreating TCP connections for every API request.
session = make_session()


def api_post(url, payload):
    """
    Send a JSON POST request to the Stremio API and return the decoded response.

    The retry adapter handles retryable HTTP status codes. This loop handles
    connection errors, timeouts, invalid JSON, and other request-level failures
    by waiting briefly and trying again before returning a normalized error
    dictionary that callers can inspect or print.
    """
    for attempt in range(3):
        try:
            resp = session.post(url, json=payload, timeout=30)
            return resp.json()
        except Exception as e:
            if attempt < 2:
                print(f"  [RETRY] Connection error, retrying in 3s...")
                time.sleep(3)
            else:
                print(f"  [ERROR] Failed after 3 attempts: {e}")
                return {"error": str(e)}


def login_with_password(email, password):
    """
    Authenticate a Stremio account with email/password and return its auth key.

    Stremio commonly accepts an MD5 hash of the password for login, so the first
    attempt mirrors that client behavior. The second attempt sends the plain
    password as a compatibility fallback. Nothing is stored on disk; the returned
    auth key only lives in memory for this script run.
    """
    pass_hash = hashlib.md5(password.encode()).hexdigest()
    data = api_post(f"{API_BASE}/login", {
        "email": email, "password": pass_hash, "type": "Login"
    })
    if data.get("result"):
        return data["result"]["authKey"]
    # Fallback: plain password
    data2 = api_post(f"{API_BASE}/login", {
        "email": email, "password": password, "type": "Login"
    })
    if data2.get("result"):
        return data2["result"]["authKey"]
    return None


def login_with_token(token):
    """
    Authenticate with an existing Stremio auth key and return a fresh auth key.

    One-click sign-in users, such as Facebook or Apple users, may not have a
    Stremio password they can enter here. The official Stremio API supports
    validating an existing session token through loginWithToken, which lets this
    script use the same merge workflow after the user pastes an auth key from an
    already-authenticated Stremio session.
    """
    token = token.strip()
    if not token:
        return None

    data = api_post(f"{API_BASE}/loginWithToken", {
        "type": "LoginWithToken", "token": token
    })
    result = data.get("result")
    if isinstance(result, dict) and result.get("authKey"):
        return result["authKey"]
    return None


def prompt_account_auth(label):
    """
    Prompt for one account and return the auth key plus a display label.

    Users can choose the existing email/password flow or paste an auth key from
    an already logged-in Stremio session. Invalid menu choices are reprompted so
    a mistyped selection does not accidentally fall through to the wrong method.
    """
    print(f"\n--- {label} ---")
    print("Login method:")
    print("  1) Email + password")
    print("  2) Stremio auth key (for Facebook/Apple/one-click sign-in)")

    while True:
        choice = input("Choose login method (1/2, default 1): ").strip()
        if choice == "":
            choice = "1"

        if choice == "1":
            email = input("Email: ").strip()
            password = getpass.getpass("Password: ")
            return login_with_password(email, password), email

        if choice == "2":
            auth_key = getpass.getpass("Auth key: ").strip()
            return login_with_token(auth_key), "auth key"

        print("  [ERROR] Please choose 1 for email/password or 2 for auth key.")


def fetch_library(auth_key):
    """
    Download all library items for an account and normalize them by item ID.

    The datastore endpoint can return either a list of library entries or a
    mapping of IDs to entries depending on API response shape. The merge logic is
    simpler and safer when both forms are converted into a single dictionary:
    {
        "item_id": {full library item payload}
    }
    """
    data = api_post(f"{API_BASE}/datastoreGet", {
        "authKey": auth_key, "collection": "libraryItem", "all": True
    })
    items = {}

    # Some responses are lists of item objects. In that case the item's "_id"
    # field becomes the dictionary key used for duplicate detection.
    result = data.get("result")
    if result and isinstance(result, list):
        for entry in result:
            if isinstance(entry, dict) and entry.get("_id"):
                items[entry["_id"]] = entry

    # Other responses are already dictionaries. Keep only values that look like
    # complete item payloads so malformed entries do not break the merge.
    elif result and isinstance(result, dict):
        for k, v in result.items():
            if isinstance(v, dict):
                items[k] = v
    return items


def fetch_addons(auth_key):
    """
    Download an account's addon collection.

    The API wraps addons inside result.addons. Returning an empty list for any
    unexpected response keeps the rest of the script deterministic and prevents
    accidental writes based on malformed data.
    """
    data = api_post(f"{API_BASE}/addonCollectionGet", {
        "type": "AddonCollectionGet", "authKey": auth_key
    })
    if isinstance(data.get("result"), dict) and data["result"].get("addons"):
        return data["result"]["addons"]
    return []


def has_better_progress(existing, incoming):
    """
    Return True when the destination item should be kept as-is.

    Stremio stores progress inside the item "state". The comparison checks the
    strongest signals first:
    - total watch time
    - number of completed watches
    - last watched timestamp
    - season and episode position

    Equal progress also returns True because importing an identical item would
    create unnecessary writes and could still disturb metadata ordering.
    """
    ex_state = existing.get("state", {})
    in_state = incoming.get("state", {})
    if not isinstance(ex_state, dict) or not isinstance(in_state, dict):
        return False

    # Prefer whichever item has accumulated more watch time.
    ex_time = ex_state.get("overallTimeWatched", 0) or 0
    in_time = in_state.get("overallTimeWatched", 0) or 0
    if ex_time > in_time:
        return True

    # If total time is not decisive, completed watch count is the next signal.
    ex_times = ex_state.get("timesWatched", 0) or 0
    in_times = in_state.get("timesWatched", 0) or 0
    if ex_times > in_times:
        return True

    # ISO-like timestamp strings compare correctly in chronological order when
    # both values use the same Stremio format.
    ex_last = ex_state.get("lastWatched", "") or ""
    in_last = in_state.get("lastWatched", "") or ""
    if ex_last > in_last:
        return True

    # For episodic content, a later season/episode position should not be
    # replaced by an older source item.
    ex_season = ex_state.get("season", 0) or 0
    in_season = in_state.get("season", 0) or 0
    ex_ep = ex_state.get("episode", 0) or 0
    in_ep = in_state.get("episode", 0) or 0
    if (ex_season, ex_ep) > (in_season, in_ep):
        return True

    if ex_time == in_time and ex_times == in_times and ex_last == in_last:
        return True

    return False


def merge_addons(src_addons, dst_addons, dst_auth):
    """
    Add source addons that do not already exist on the destination account.

    Addons are identified by their transportUrl. The destination collection is
    rewritten as "existing destination addons + missing source addons", which
    preserves the destination's existing addon entries and ordering first.
    """
    dst_urls = {a["transportUrl"] for a in dst_addons}
    new_addons = [a for a in src_addons if a["transportUrl"] not in dst_urls]

    print(f"  Source: {len(src_addons)} | Destination: {len(dst_addons)} | New: {len(new_addons)}")

    if not new_addons:
        print("  [OK] All addons already exist on destination")
        return

    merged = dst_addons + new_addons
    data = api_post(f"{API_BASE}/addonCollectionSet", {
        "type": "AddonCollectionSet", "authKey": dst_auth, "addons": merged
    })
    if data.get("result", {}).get("success"):
        print(f"  [OK] Added {len(new_addons)} new addons")
    else:
        print(f"  [ERROR] {data}")


def merge_library(src_lib, dst_lib, dst_auth):
    """
    Merge source library items into the destination account.

    New items are imported directly. Existing items are imported only when the
    source appears to have better progress than the destination. Items are sent
    in batches for speed, with a single-item fallback for batches that fail so
    one bad item does not block the rest of the merge.
    """
    to_import = []
    skipped = 0
    new_count = 0
    updated_count = 0

    # Decide the merge action for every source item before making any writes.
    # This creates a predictable preview and protects destination progress.
    for item_id, item_data in src_lib.items():
        if item_id in dst_lib:
            if has_better_progress(dst_lib[item_id], item_data):
                skipped += 1
            else:
                updated_count += 1
                to_import.append(item_data)
        else:
            new_count += 1
            to_import.append(item_data)

    print(f"  Source: {len(src_lib)} | Destination: {len(dst_lib)}")
    print(f"  New: {new_count} | Updates (source has better progress): {updated_count} | "
          f"Skipped (dest has better/equal): {skipped}")

    if not to_import:
        print("  [OK] Nothing to import, destination already up to date")
        return

    success = 0
    failed = 0
    batch_size = 20

    for i in range(0, len(to_import), batch_size):
        batch = to_import[i:i+batch_size]

        # The datastore accepts multiple changes at once, so batches keep the
        # script fast for large libraries.
        data = api_post(f"{API_BASE}/datastorePut", {
            "authKey": dst_auth,
            "collection": "libraryItem",
            "changes": batch
        })
        if data.get("result", {}).get("success"):
            success += len(batch)
        else:
            # If a whole batch fails, retry each item separately. This salvages
            # valid entries and gives a realistic failure count.
            for item in batch:
                data2 = api_post(f"{API_BASE}/datastorePut", {
                    "authKey": dst_auth,
                    "collection": "libraryItem",
                    "changes": [item]
                })
                if data2.get("result", {}).get("success"):
                    success += 1
                else:
                    failed += 1
                time.sleep(0.2)

        done = min(i + batch_size, len(to_import))
        print(f"  Progress: {done}/{len(to_import)} (ok: {success}, fail: {failed})")
        time.sleep(0.5)

    print(f"  [DONE] {success} imported, {skipped} skipped, {failed} failed")


def main():
    """
    Run the full interactive merge workflow.

    The order is:
    1. collect source credentials
    2. collect destination credentials
    3. fetch both accounts
    4. preview the merge
    5. write addons and library items after confirmation
    """
    print("=" * 50)
    print("  Stremio Account Merger")
    print("  Merge data from one account to another")
    print("  (without replacing equal or better destination progress)")
    print("=" * 50)

    # Source account. The prompt supports email/password and pasted auth keys,
    # but both paths return the same kind of auth key for the merge steps below.
    src_auth, src_identity = prompt_account_auth("SOURCE account (copy FROM)")
    if not src_auth:
        print("[ERROR] Failed to login to source account")
        sys.exit(1)
    print(f"[OK] Logged into source: {src_identity}")

    # Destination account. The destination auth key is the only credential used
    # for write requests after the user confirms the merge preview.
    dst_auth, dst_identity = prompt_account_auth("DESTINATION account (copy TO)")
    if not dst_auth:
        print("[ERROR] Failed to login to destination account")
        sys.exit(1)
    print(f"[OK] Logged into destination: {dst_identity}")

    # Fetch data from both accounts before writing anything. Keeping reads and
    # writes separate makes the preview truthful and gives the user a final
    # chance to cancel.
    print("\n--- Fetching data from source ---")
    src_addons = fetch_addons(src_auth)
    src_lib = fetch_library(src_auth)
    print(f"  Addons: {len(src_addons)} | Library: {len(src_lib)}")

    print("\n--- Fetching data from destination ---")
    dst_addons = fetch_addons(dst_auth)
    dst_lib = fetch_library(dst_auth)
    print(f"  Addons: {len(dst_addons)} | Library: {len(dst_lib)}")

    # Preview the addon and library impact. This is intentionally calculated
    # locally from fetched data so the user can see what will change before the
    # script sends any write requests.
    dst_urls = {a["transportUrl"] for a in dst_addons}
    new_addon_count = sum(1 for a in src_addons if a["transportUrl"] not in dst_urls)
    new_lib = sum(1 for k in src_lib if k not in dst_lib)
    overlap = sum(1 for k in src_lib if k in dst_lib)

    print(f"\n--- Summary ---")
    print(f"  Addons to add:        {new_addon_count}")
    print(f"  New library items:    {new_lib}")
    print(f"  Overlapping items:    {overlap} (will keep better progress)")
    print()

    confirm = input("Proceed with merge? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    # Writes happen only after explicit confirmation. Addons are merged first
    # because they are a single collection update; library items follow in
    # batches because libraries can be much larger.
    print("\n--- Merging addons ---")
    merge_addons(src_addons, dst_addons, dst_auth)

    print("\n--- Merging library ---")
    merge_library(src_lib, dst_lib, dst_auth)

    print("\n" + "=" * 50)
    print("  Merge complete! Restart Stremio to see changes.")
    print("=" * 50)


if __name__ == "__main__":
    # Keep import side effects minimal: the interactive workflow runs only when
    # this file is executed directly, not when imported by a test or another tool.
    main()
