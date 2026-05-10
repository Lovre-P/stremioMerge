#!/usr/bin/env python3
"""
Stremio Account Merger
Merge/clone data from one Stremio account to another.
Imports addons and library (watchlist, watch progress) without overwriting
existing data on the destination account.

Usage: python3 stremio_merge.py
"""

import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import getpass
import time
import hashlib
import sys

API_BASE = "https://api.strem.io/api"

def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

session = make_session()

def api_post(url, payload):
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

def login(email, password):
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

def fetch_library(auth_key):
    data = api_post(f"{API_BASE}/datastoreGet", {
        "authKey": auth_key, "collection": "libraryItem", "all": True
    })
    items = {}
    result = data.get("result")
    if result and isinstance(result, list):
        for entry in result:
            if isinstance(entry, dict) and entry.get("_id"):
                items[entry["_id"]] = entry
    elif result and isinstance(result, dict):
        for k, v in result.items():
            if isinstance(v, dict):
                items[k] = v
    return items

def fetch_addons(auth_key):
    data = api_post(f"{API_BASE}/addonCollectionGet", {
        "type": "AddonCollectionGet", "authKey": auth_key
    })
    if isinstance(data.get("result"), dict) and data["result"].get("addons"):
        return data["result"]["addons"]
    return []

def has_better_progress(existing, incoming):
    """Return True if existing item has equal or better watch progress."""
    ex_state = existing.get("state", {})
    in_state = incoming.get("state", {})
    if not isinstance(ex_state, dict) or not isinstance(in_state, dict):
        return False

    ex_time = ex_state.get("overallTimeWatched", 0) or 0
    in_time = in_state.get("overallTimeWatched", 0) or 0
    if ex_time > in_time:
        return True

    ex_times = ex_state.get("timesWatched", 0) or 0
    in_times = in_state.get("timesWatched", 0) or 0
    if ex_times > in_times:
        return True

    ex_last = ex_state.get("lastWatched", "") or ""
    in_last = in_state.get("lastWatched", "") or ""
    if ex_last > in_last:
        return True

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
    to_import = []
    skipped = 0
    new_count = 0
    updated_count = 0

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
    print(f"  New: {new_count} | Update (old has better progress): {updated_count} | "
          f"Skipped (dest has better/equal): {skipped}")

    if not to_import:
        print("  [OK] Nothing to import, destination already up to date")
        return

    success = 0
    failed = 0
    batch_size = 20

    for i in range(0, len(to_import), batch_size):
        batch = to_import[i:i+batch_size]
        data = api_post(f"{API_BASE}/datastorePut", {
            "authKey": dst_auth,
            "collection": "libraryItem",
            "changes": batch
        })
        if data.get("result", {}).get("success"):
            success += len(batch)
        else:
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
    print("=" * 50)
    print("  Stremio Account Merger")
    print("  Merge data from one account to another")
    print("  (without overwriting destination progress)")
    print("=" * 50)

    # Source account
    print("\n--- SOURCE account (copy FROM) ---")
    src_email = input("Email: ").strip()
    src_pass = getpass.getpass("Password: ")

    src_auth = login(src_email, src_pass)
    if not src_auth:
        print("[ERROR] Failed to login to source account")
        sys.exit(1)
    print(f"[OK] Logged into source: {src_email}")

    # Destination account
    print("\n--- DESTINATION account (copy TO) ---")
    dst_email = input("Email: ").strip()
    dst_pass = getpass.getpass("Password: ")

    dst_auth = login(dst_email, dst_pass)
    if not dst_auth:
        print("[ERROR] Failed to login to destination account")
        sys.exit(1)
    print(f"[OK] Logged into destination: {dst_email}")

    # Fetch data from both accounts
    print("\n--- Fetching data from source ---")
    src_addons = fetch_addons(src_auth)
    src_lib = fetch_library(src_auth)
    print(f"  Addons: {len(src_addons)} | Library: {len(src_lib)}")

    print("\n--- Fetching data from destination ---")
    dst_addons = fetch_addons(dst_auth)
    dst_lib = fetch_library(dst_auth)
    print(f"  Addons: {len(dst_addons)} | Library: {len(dst_lib)}")

    # Preview
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

    # Merge
    print("\n--- Merging addons ---")
    merge_addons(src_addons, dst_addons, dst_auth)

    print("\n--- Merging library ---")
    merge_library(src_lib, dst_lib, dst_auth)

    print("\n" + "=" * 50)
    print("  Merge complete! Restart Stremio to see changes.")
    print("=" * 50)

if __name__ == "__main__":
    main()
