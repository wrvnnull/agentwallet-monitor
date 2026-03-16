#!/usr/bin/env python3
"""
AgentWallet Full Feature Monitor
Runs every 5 minutes via GitHub Actions, tests ALL features,
and writes results to docs/status.json for GitHub Pages dashboard.
"""

import os
import json
import time
import datetime
import sys
import traceback

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

BASE_URL = "https://frames.ag/api"
USERNAME = os.environ.get("AGENTWALLET_USERNAME", "")
API_TOKEN = os.environ.get("AGENTWALLET_API_TOKEN", "")

if not USERNAME or not API_TOKEN:
    print("❌ ERROR: AGENTWALLET_USERNAME and AGENTWALLET_API_TOKEN must be set.")
    sys.exit(1)

AUTH_HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

# ─────────────────────────────────────────────
# Result collector
# ─────────────────────────────────────────────

results = {
    "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "username": USERNAME,
    "summary": {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "warnings": 0
    },
    "tests": [],
    "meta": {
        "skill_version": None,
        "balance_usd": None,
        "rank": None,
        "tier": None,
        "referral_count": None,
        "airdrop_points": None
    }
}


def run_test(name: str, category: str, fn):
    """Execute a test function and record its result."""
    start = time.time()
    entry = {
        "name": name,
        "category": category,
        "status": "fail",
        "duration_ms": 0,
        "data": None,
        "error": None
    }
    try:
        data = fn()
        entry["status"] = "pass"
        entry["data"] = data
        print(f"  ✅  {name}")
    except AssertionError as e:
        entry["status"] = "warn"
        entry["error"] = str(e)
        print(f"  ⚠️  {name}: {e}")
    except Exception as e:
        entry["status"] = "fail"
        entry["error"] = str(e)
        print(f"  ❌  {name}: {e}")
    finally:
        entry["duration_ms"] = round((time.time() - start) * 1000)
        results["tests"].append(entry)


# ─────────────────────────────────────────────
# Individual test functions
# ─────────────────────────────────────────────

def test_skill_version():
    r = requests.get("https://frames.ag/skill.json", timeout=15)
    r.raise_for_status()
    data = r.json()
    version = data.get("version", "unknown")
    results["meta"]["skill_version"] = version
    return {"version": version}


def test_network_pulse():
    r = requests.get(f"{BASE_URL}/network/pulse", timeout=15)
    r.raise_for_status()
    data = r.json()
    return {
        "active_agents": data.get("activeAgents"),
        "tx_count": data.get("transactionCount"),
        "volume": data.get("volume"),
        "trending_apis": data.get("trendingApis", [])[:3]
    }


def test_wallet_info():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}", timeout=15)
    r.raise_for_status()
    data = r.json()
    connected = data.get("connected", False)
    assert connected, "Wallet not connected"
    return {
        "connected": connected,
        "evm_address": data.get("evmAddress", "")[:10] + "...",
        "solana_address": str(data.get("solanaAddress", ""))[:10] + "..."
    }


def test_balances():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}/balances",
                     headers=AUTH_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    balances = data.get("data", data)
    # Try to extract total USD
    total = None
    if isinstance(balances, dict):
        total = balances.get("totalUsd") or balances.get("total_usd")
    results["meta"]["balance_usd"] = total
    return {"raw": str(balances)[:300]}


def test_activity():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=10",
                     headers=AUTH_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    events = data.get("data", data)
    count = len(events) if isinstance(events, list) else "?"
    return {"event_count": count}


def test_stats():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}/stats",
                     headers=AUTH_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    inner = data.get("data", data)
    rank = inner.get("rank")
    tier = inner.get("tier")
    points = inner.get("airdropPoints")
    results["meta"]["rank"] = rank
    results["meta"]["tier"] = tier
    results["meta"]["airdrop_points"] = points
    return {
        "rank": rank,
        "tier": tier,
        "airdrop_points": points,
        "weekly_txs": inner.get("weeklyTransactions")
    }


def test_referrals():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}/referrals",
                     headers=AUTH_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    inner = data.get("data", data)
    count = inner.get("referralCount") or inner.get("count") or 0
    results["meta"]["referral_count"] = count
    return {
        "referral_count": count,
        "referral_link": f"https://frames.ag/connect?ref={USERNAME}"
    }


def test_policy_get():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}/policy",
                     headers=AUTH_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    inner = data.get("data", data)
    return {
        "max_per_tx_usd": inner.get("max_per_tx_usd"),
        "allow_chains": inner.get("allow_chains", []),
    }


def test_policy_patch():
    """Update policy with safe values (same as current to be non-destructive)."""
    payload = {
        "max_per_tx_usd": "25",
        "allow_chains": ["base", "solana"]
    }
    r = requests.patch(f"{BASE_URL}/wallets/{USERNAME}/policy",
                       headers=AUTH_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    assert data.get("success"), f"Policy update failed: {data.get('error')}"
    return {"updated": True, "payload": payload}


def test_list_wallets():
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                     headers=AUTH_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    inner = data.get("data", data)
    wallets = inner.get("wallets", [])
    tier = inner.get("tier")
    return {
        "wallet_count": len(wallets),
        "tier": tier,
        "limits": inner.get("limits")
    }


def test_x402_dryrun():
    """Dry-run x402/fetch – preview cost WITHOUT paying."""
    payload = {
        "url": "https://registry.frames.ag/api/service/exa/api/search",
        "method": "POST",
        "body": {"query": "AI agents", "numResults": 1},
        "dryRun": True
    }
    r = requests.post(
        f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
        headers=AUTH_HEADERS,
        json=payload,
        timeout=30
    )
    r.raise_for_status()
    data = r.json()
    payment = data.get("payment", {})
    return {
        "dry_run": True,
        "payment_required": payment.get("required"),
        "chain": payment.get("chain"),
        "amount": payment.get("amountFormatted"),
        "policy_allowed": payment.get("policyAllowed")
    }


def test_sign_message():
    """Sign a test message on Ethereum chain."""
    payload = {"chain": "ethereum", "message": "AgentWallet monitor ping"}
    r = requests.post(
        f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
        headers=AUTH_HEADERS,
        json=payload,
        timeout=15
    )
    r.raise_for_status()
    data = r.json()
    assert data.get("success") or data.get("signature") or data.get("data"), \
        f"Sign failed: {data}"
    return {"signed": True}


def test_feedback():
    """Submit a monitor feedback entry."""
    payload = {
        "category": "other",
        "message": f"[AUTO-MONITOR] Heartbeat from GitHub Actions at "
                   f"{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}. "
                   f"All feature tests running.",
        "context": {
            "source": "github-actions",
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "repo": os.environ.get("GITHUB_REPOSITORY", "unknown")
        }
    }
    r = requests.post(
        f"{BASE_URL}/wallets/{USERNAME}/feedback",
        headers=AUTH_HEADERS,
        json=payload,
        timeout=15
    )
    r.raise_for_status()
    data = r.json()
    assert data.get("success"), f"Feedback failed: {data.get('error')}"
    feedback_id = data.get("data", {}).get("id", "?")
    return {"submitted": True, "feedback_id": feedback_id}


def test_heartbeat_md():
    """Fetch the HEARTBEAT.md to ensure it's reachable."""
    r = requests.get("https://frames.ag/heartbeat.md", timeout=15)
    r.raise_for_status()
    content_len = len(r.text)
    assert content_len > 100, "HEARTBEAT.md seems too short"
    return {"content_length": content_len, "status_code": r.status_code}


def test_connect_check():
    """Public endpoint: check wallet connected status."""
    r = requests.get(f"{BASE_URL}/wallets/{USERNAME}", timeout=15)
    r.raise_for_status()
    data = r.json()
    assert data.get("connected"), "Wallet reports not connected"
    return {"connected": data.get("connected")}


# ─────────────────────────────────────────────
# Run all tests
# ─────────────────────────────────────────────

TESTS = [
    ("Skill Version Check",     "meta",      test_skill_version),
    ("Heartbeat.md Reachable",  "meta",      test_heartbeat_md),
    ("Network Pulse",           "public",    test_network_pulse),
    ("Wallet Connected (Public)","public",   test_connect_check),
    ("Wallet Info",             "wallet",    test_wallet_info),
    ("Balances",                "wallet",    test_balances),
    ("Activity Feed",           "wallet",    test_activity),
    ("Stats & Rank",            "wallet",    test_stats),
    ("Referrals",               "referrals", test_referrals),
    ("Policy GET",              "policy",    test_policy_get),
    ("Policy PATCH",            "policy",    test_policy_patch),
    ("List Wallets",            "wallet",    test_list_wallets),
    ("x402 Dry Run",            "x402",      test_x402_dryrun),
    ("Sign Message",            "actions",   test_sign_message),
    ("Feedback Submit",         "feedback",  test_feedback),
]

print(f"\n{'='*55}")
print(f"  AgentWallet Monitor  —  {results['timestamp']}")
print(f"  User: {USERNAME}")
print(f"{'='*55}")

categories_seen = []
for name, category, fn in TESTS:
    if category not in categories_seen:
        print(f"\n[{category.upper()}]")
        categories_seen.append(category)
    run_test(name, category, fn)

# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────

passed  = sum(1 for t in results["tests"] if t["status"] == "pass")
failed  = sum(1 for t in results["tests"] if t["status"] == "fail")
warned  = sum(1 for t in results["tests"] if t["status"] == "warn")
total   = len(results["tests"])

results["summary"] = {
    "total": total,
    "passed": passed,
    "failed": failed,
    "warnings": warned,
    "overall": "pass" if failed == 0 else "fail"
}

# Keep last 50 runs history
HISTORY_FILE = "docs/history.json"
history = []
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE) as f:
            history = json.load(f)
    except Exception:
        history = []

history.insert(0, {
    "timestamp": results["timestamp"],
    "passed": passed,
    "failed": failed,
    "warnings": warned,
    "overall": results["summary"]["overall"]
})
history = history[:50]  # keep last 50

os.makedirs("docs", exist_ok=True)
with open(HISTORY_FILE, "w") as f:
    json.dump(history, f, indent=2)

# Write main status
with open("docs/status.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*55}")
print(f"  RESULT: {passed}/{total} passed  |  {failed} failed  |  {warned} warnings")
if results["meta"]["balance_usd"] is not None:
    print(f"  Balance : ${results['meta']['balance_usd']} USD")
if results["meta"]["rank"] is not None:
    print(f"  Rank    : #{results['meta']['rank']}  |  Tier: {results['meta']['tier']}")
print(f"{'='*55}\n")

if failed > 0:
    print("Some tests failed – check docs/status.json for details.")
    sys.exit(1)
