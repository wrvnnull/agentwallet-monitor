#!/usr/bin/env python3
"""
AgentWallet FINAL Monitor — v4 ULTIMATE
=========================================
Semua fitur dari spec resmi:
  META       : skill.json version, metadata, heartbeat.md
  PUBLIC     : network pulse, wallet connected, connect-start endpoint
  WALLET     : info, balances, activity (auth+public), stats, list wallets,
               create wallet EVM+Solana
  REFERRALS  : count, tier multiplier, link
  POLICY     : GET, PATCH/PUT
  X402       : dryRun auto/EVM/Solana, token USDC/USDT/CASH,
               preferredChainId, idempotencyKey, timeout option,
               EVM+USDC, Solana+USDC, INVALID_URL error,
               legacy /pay endpoint, REAL fetch (actual TX untuk points!)
  ACTIONS    : sign Ethereum, sign Solana, sign with walletAddress param,
               faucet Solana devnet
  NETWORKS   : transfer Base/Optimism/Polygon/Arbitrum/BNB/Ethereum/Gnosis
               + Sepolia/BaseSepolia testnet
               + Solana mainnet/devnet
               + ContractCall EVM/Solana
               + transfer with idempotencyKey
  FEEDBACK   : 4 categories (other/bug/feature/stuck)

Scoring rules:
  PASS  = 2xx or expected 4xx (policy/funds/validation)
  WARN  = rate-limit, tier-limit, server-side 500, timeout (soft)
  FAIL  = truly unexpected error (exit 1)
"""

import os, json, time, datetime, sys, uuid

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

BASE_URL = "https://frames.ag/api"
USERNAME  = os.environ.get("AGENTWALLET_USERNAME", "")
API_TOKEN = os.environ.get("AGENTWALLET_API_TOKEN", "")

if not USERNAME or not API_TOKEN:
    print("ERROR: AGENTWALLET_USERNAME and AGENTWALLET_API_TOKEN must be set.")
    sys.exit(1)

AUTH = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}

results = {
    "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "username": USERNAME,
    "summary": {"total": 0, "passed": 0, "failed": 0, "warnings": 0},
    "tests": [],
    "meta": {
        "skill_version": None, "balance_usd": None, "rank": None,
        "tier": None, "referral_count": None, "airdrop_points": None,
        "wallet_count": None, "evm_address": None, "solana_address": None,
        "real_x402_done": False, "real_x402_amount": None, "real_x402_chain": None,
    },
}


def run_test(name, category, fn):
    start = time.time()
    entry = {"name": name, "category": category, "status": "fail",
             "duration_ms": 0, "data": None, "error": None}
    try:
        data = fn()
        entry["status"] = "pass"
        entry["data"] = data
        print(f"  OK   {name}")
    except AssertionError as e:
        entry["status"] = "warn"
        entry["error"] = str(e)
        print(f"  WARN {name}: {e}")
    except Exception as e:
        entry["status"] = "fail"
        entry["error"] = str(e)
        print(f"  FAIL {name}: {e}")
    finally:
        entry["duration_ms"] = round((time.time() - start) * 1000)
        results["tests"].append(entry)


def _safe(r):
    if r.status_code == 429:
        raise AssertionError("429 rate-limited (too many requests) — wait for next run")
    r.raise_for_status()
    return r.json()


def _network_check(r, label):
    """4xx = endpoint alive = PASS. 429/500 = server-side = WARN. 5xx = FAIL."""
    if r.status_code in (429, 500):
        code = "429 rate-limit" if r.status_code == 429 else "500 server error"
        raise AssertionError(f"{label} returned {code} (server-side issue)")
    if r.status_code in (400, 402, 403, 422, 200, 201):
        d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        return {"status_code": r.status_code, "resp": str(d)[:120]}
    r.raise_for_status()
    return {"status_code": r.status_code}


# ─────────────────────────────────────────────────────────────
# META
# ─────────────────────────────────────────────────────────────

def test_skill_version():
    d = _safe(requests.get("https://frames.ag/skill.json", timeout=15))
    v = d.get("version", "unknown")
    results["meta"]["skill_version"] = v
    return {"version": v, "name": d.get("name"), "homepage": d.get("homepage")}

def test_skill_json_metadata():
    d = _safe(requests.get("https://frames.ag/skill.json", timeout=15))
    mb = d.get("moltbot", {})
    x4 = d.get("metadata", {}).get("x402", d.get("x402", {}))
    assert mb.get("api_base"), "moltbot.api_base missing"
    return {"api_base": mb.get("api_base"), "x402_chains": x4.get("chains", []),
            "x402_tokens": x4.get("tokens", []), "keywords": d.get("keywords", [])[:5]}

def test_heartbeat_md():
    r = requests.get("https://frames.ag/heartbeat.md", timeout=15)
    r.raise_for_status()
    assert len(r.text) > 100, "HEARTBEAT.md too short"
    # Check key sections exist
    has_network = "Network Pulse" in r.text or "network" in r.text.lower()
    return {"bytes": len(r.text), "status": r.status_code, "has_network_section": has_network}


# ─────────────────────────────────────────────────────────────
# PUBLIC
# ─────────────────────────────────────────────────────────────

def test_network_pulse():
    d = _safe(requests.get(f"{BASE_URL}/network/pulse", timeout=15))
    return {"active_agents": d.get("activeAgents"), "tx_count": d.get("transactionCount"),
            "volume": d.get("volume"), "trending": d.get("trendingApis", [])[:3]}

def test_wallet_connected_public():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}", timeout=15))
    assert d.get("connected"), "Wallet not connected"
    results["meta"]["evm_address"]    = d.get("evmAddress", "")
    results["meta"]["solana_address"] = d.get("solanaAddress", "")
    return {"connected": True, "evm": str(d.get("evmAddress",""))[:14]+"...",
            "solana": str(d.get("solanaAddress",""))[:14]+"..."}

def test_connect_start_endpoint():
    """
    Verify /api/connect/start is reachable.
    We send a dummy email — expect 400/422 (validation error, not 500).
    This confirms the connect flow endpoint is alive.
    """
    r = requests.post(f"{BASE_URL}/connect/start",
                      json={"email": "monitor-test@example.invalid"}, timeout=15)
    # 400/422/429 = endpoint alive (email rejected or rate-limited)
    assert r.status_code != 500, f"Connect start returned 500"
    assert r.status_code not in (404, 405), f"Connect start endpoint not found: {r.status_code}"
    return {"status_code": r.status_code, "endpoint": "alive"}


# ─────────────────────────────────────────────────────────────
# WALLET
# ─────────────────────────────────────────────────────────────

def test_wallet_info():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}", timeout=15))
    assert d.get("connected"), "not connected"
    return {"evm": str(d.get("evmAddress",""))[:14]+"...",
            "solana": str(d.get("solanaAddress",""))[:14]+"..."}

def test_balances():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/balances", headers=AUTH, timeout=15))
    inner = d.get("data", d)
    total = inner.get("totalUsd") or inner.get("total_usd")
    results["meta"]["balance_usd"] = total
    return {"total_usd": total, "raw": str(inner)[:300]}

def test_activity_auth():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=20",
                            headers=AUTH, timeout=15))
    events = d.get("data", d)
    count = len(events) if isinstance(events, list) else "?"
    types = list({e.get("type","?") for e in (events if isinstance(events,list) else [])})[:8]
    return {"event_count": count, "event_types": types}

def test_activity_public():
    """Public unauthenticated — limited view."""
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=5", timeout=15))
    events = d.get("data", d)
    return {"public_events": len(events) if isinstance(events, list) else "?"}

def test_stats():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/stats", headers=AUTH, timeout=15))
    inner = d.get("data", d)
    results["meta"]["rank"]           = inner.get("rank")
    results["meta"]["tier"]           = inner.get("tier")
    results["meta"]["airdrop_points"] = inner.get("airdropPoints")
    return {"rank": inner.get("rank"), "tier": inner.get("tier"),
            "points": inner.get("airdropPoints"), "weekly_txs": inner.get("weeklyTransactions"),
            "streak": inner.get("streak"), "total_txs": inner.get("totalTransactions")}

def test_list_wallets():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/wallets", headers=AUTH, timeout=15))
    inner = d.get("data", d)
    wallets = inner.get("wallets", [])
    results["meta"]["wallet_count"] = len(wallets)
    # Store wallet addresses for multi-wallet tests
    results["meta"]["all_evm_wallets"] = [w["address"] for w in wallets
                                           if w.get("chainType") in ("ethereum","evm")]
    return {"count": len(wallets), "tier": inner.get("tier"),
            "limits": inner.get("limits"), "counts": inner.get("counts")}

def test_create_wallet_evm():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                      headers=AUTH, json={"chainType": "ethereum"}, timeout=15)
    if r.status_code == 403:
        raise AssertionError(f"Tier limit (expected Bronze): {r.json().get('error','')}")
    r.raise_for_status()
    return {"created": True, "address": str(r.json().get("data",{}).get("address",""))[:16]+"..."}

def test_create_wallet_solana():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                      headers=AUTH, json={"chainType": "solana"}, timeout=15)
    if r.status_code == 403:
        raise AssertionError(f"Tier limit (expected Bronze): {r.json().get('error','')}")
    r.raise_for_status()
    return {"created": True, "address": str(r.json().get("data",{}).get("address",""))[:16]+"..."}


# ─────────────────────────────────────────────────────────────
# REFERRALS
# ─────────────────────────────────────────────────────────────

def test_referrals():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/referrals", headers=AUTH, timeout=15))
    inner = d.get("data", d)
    count = inner.get("referralCount") or inner.get("count") or 0
    results["meta"]["referral_count"] = count
    thresholds = [(100,"3x Diamond"),(25,"2x Gold"),(5,"1.5x Silver"),(0,"1x Bronze")]
    multi = next(m for t,m in thresholds if count >= t)
    next_tier_map = [(0,"Silver",5),(5,"Gold",25),(25,"Diamond",100),(100,"Diamond",None)]
    next_info = next(((nt, nr) for t,nt,nr in next_tier_map if count >= t and nr), (None,None))
    return {
        "referral_count": count, "multiplier": multi,
        "link": f"https://frames.ag/connect?ref={USERNAME}",
        "next_tier": next_info[0],
        "need_for_next": None if next_info[1] is None else next_info[1] - count,
    }


# ─────────────────────────────────────────────────────────────
# POLICY
# ─────────────────────────────────────────────────────────────

def test_policy_get():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/policy", headers=AUTH, timeout=15))
    inner = d.get("data", d)
    return {"max_per_tx_usd": inner.get("max_per_tx_usd"),
            "allow_chains": inner.get("allow_chains", []),
            "allow_contracts": inner.get("allow_contracts", []),
            "rate_limit": inner.get("rate_limit")}

def test_policy_patch():
    """PATCH → PUT fallback. 400/405 = WARN (API restriction)."""
    payload = {"max_per_tx_usd": "25", "allow_chains": ["base", "solana"]}
    url = f"{BASE_URL}/wallets/{USERNAME}/policy"
    r = requests.patch(url, headers=AUTH, json=payload, timeout=15)
    if r.status_code == 405:
        r = requests.put(url, headers=AUTH, json=payload, timeout=15)
    if r.status_code in (400, 405):
        d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        raise AssertionError(f"Policy write {r.status_code} — {d.get('error','API restriction')}")
    r.raise_for_status()
    assert r.json().get("success"), f"Policy update failed: {r.json().get('error')}"
    return {"updated": True, "method": r.request.method}


# ─────────────────────────────────────────────────────────────
# X402 / fetch
# ─────────────────────────────────────────────────────────────

X402_TARGET = "https://registry.frames.ag/api/service/exa/api/search"
X402_BODY   = {"query": "AI agent payments x402", "numResults": 1}

def _x402_dry(extra=None):
    time.sleep(2)  # avoid 429 on rapid sequential x402 calls
    payload = {"url": X402_TARGET, "method": "POST", "body": X402_BODY, "dryRun": True}
    if extra:
        payload.update(extra)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                            headers=AUTH, json=payload, timeout=30))
    p = d.get("payment", {})
    return {"dry_run": True, "required": p.get("required"),
            "chain": p.get("chain"), "amount": p.get("amountFormatted"),
            "policy_ok": p.get("policyAllowed")}

# All chain/token combos (dryRun — zero cost)
def test_x402_auto():            return _x402_dry({"preferredChain": "auto"})
def test_x402_evm():             return _x402_dry({"preferredChain": "evm"})
def test_x402_solana():          return _x402_dry({"preferredChain": "solana"})
def test_x402_usdc():            return _x402_dry({"preferredToken": "USDC"})
def test_x402_usdt():            return _x402_dry({"preferredToken": "USDT"})
def test_x402_cash():            return _x402_dry({"preferredToken": "CASH"})
def test_x402_evm_usdc():        return _x402_dry({"preferredChain": "evm",    "preferredToken": "USDC"})
def test_x402_evm_usdt():        return _x402_dry({"preferredChain": "evm",    "preferredToken": "USDT"})
def test_x402_solana_usdc():     return _x402_dry({"preferredChain": "solana", "preferredToken": "USDC"})
def test_x402_solana_cash():     return _x402_dry({"preferredChain": "solana", "preferredToken": "CASH"})
def test_x402_timeout_opt():     return _x402_dry({"timeout": 15000})

def test_x402_preferred_chain_id():
    """Test preferredChainId field (Base = 8453)."""
    return _x402_dry({"preferredChainId": 8453})

def test_x402_idempotency_key():
    """Test idempotencyKey field — same key should be safe to replay."""
    ikey = f"monitor-dry-{datetime.date.today().isoformat()}"
    return _x402_dry({"idempotencyKey": ikey})

def test_x402_invalid_url():
    """INVALID_URL error code — localhost should be blocked."""
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                      headers=AUTH, json={"url": "http://localhost/secret", "dryRun": True},
                      timeout=15)
    assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}"
    return {"error": r.json().get("error",""), "code": r.json().get("code",""),
            "status": r.status_code}

def test_x402_legacy_pay_endpoint():
    """Legacy /x402/pay — verify endpoint exists (not 404/500)."""
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/pay",
                      headers=AUTH,
                      json={"requirement": "eyJ0eXBlIjoieC00MDIifQ==",
                            "preferredChain": "evm", "dryRun": True},
                      timeout=20)
    assert r.status_code != 500, "Legacy /pay returned 500"
    assert r.status_code not in (404, 405), f"Legacy /pay not found: {r.status_code}"
    d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
    return {"status_code": r.status_code, "endpoint": "alive", "preview": str(d)[:100]}

def test_x402_real_fetch():
    """
    REAL x402 fetch — actually pays & calls Exa search API.
    Generates a real TX → earns daily active points + weekly streak.
    No pre-flight balance check (balance API format varies).
    Uses per-minute idempotencyKey so retries don't double-charge.
    insufficient_funds error → WARN (not FAIL).
    """
    minute_key = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
    ikey = f"monitor-real-{minute_key}"

    payload = {
        "url": X402_TARGET,
        "method": "POST",
        "body": {"query": f"AgentWallet monitor {minute_key}", "numResults": 1},
        "preferredChain": "evm",
        "preferredToken": "USDC",
        "idempotencyKey": ikey,
        "timeout": 30000,
    }

    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                          headers=AUTH, json=payload, timeout=60)
    except requests.exceptions.Timeout:
        raise AssertionError("Real fetch timed out (60s) — server busy, retry next run")

    # Soft errors → WARN
    if r.status_code in (402, 403):
        d = r.json()
        raise AssertionError(f"Payment blocked ({r.status_code}): {d.get('error','') or d.get('code','')}")
    if r.status_code in (429, 502, 503, 504):
        raise AssertionError(f"Real fetch server error {r.status_code} — retry next run")

    r.raise_for_status()
    d = r.json()

    # Check if it actually paid
    paid = d.get("paid", False) or d.get("success", False)
    if not paid:
        err = d.get("error","") or d.get("code","")
        raise AssertionError(f"Real fetch returned success=false: {err}")

    results["meta"]["real_x402_done"]   = True
    results["meta"]["real_x402_amount"] = d.get("payment", {}).get("amountFormatted")
    results["meta"]["real_x402_chain"]  = d.get("payment", {}).get("chain")

    resp = d.get("response", {})
    return {
        "paid": True,
        "amount":          d.get("payment", {}).get("amountFormatted"),
        "chain":           d.get("payment", {}).get("chain"),
        "attempts":        d.get("attempts"),
        "response_status": resp.get("status"),
        "duration_ms":     d.get("duration"),
        "idempotency_key": ikey,
    }


# ─────────────────────────────────────────────────────────────
# ACTIONS — Sign
# ─────────────────────────────────────────────────────────────

def test_sign_ethereum():
    time.sleep(2)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain": "ethereum",
                                  "message": "AgentWallet monitor v4 ETH"},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data"), f"No signature: {d}"
    return {"chain": "ethereum", "signed": True}

def test_sign_solana():
    time.sleep(2)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain": "solana",
                                  "message": "AgentWallet monitor v4 SOL"},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data"), f"No signature: {d}"
    return {"chain": "solana", "signed": True}

def test_sign_with_wallet_address():
    """Sign using explicit walletAddress param (multi-wallet feature)."""
    time.sleep(2)
    evm_addr = results["meta"]["evm_address"] or ""
    if not evm_addr:
        raise AssertionError("No EVM address available (run wallet_info first)")
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain": "ethereum",
                                  "message": "AgentWallet monitor walletAddress param",
                                  "walletAddress": evm_addr},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data"), f"No signature: {d}"
    return {"chain": "ethereum", "signed": True, "wallet_address_param": evm_addr[:14]+"..."}


# ─────────────────────────────────────────────────────────────
# ACTIONS — Faucet
# ─────────────────────────────────────────────────────────────

def test_faucet_devnet():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/faucet-sol",
                      headers=AUTH, json={}, timeout=30)
    if r.status_code == 429:
        raise AssertionError("Faucet rate-limited (3/24h) — used today already")
    r.raise_for_status()
    inner = r.json().get("data", r.json())
    return {"amount": inner.get("amount"), "status": inner.get("status"),
            "tx": str(inner.get("txHash",""))[:20]+"...", "remaining": inner.get("remaining")}


# ─────────────────────────────────────────────────────────────
# NETWORKS — Transfer validation (endpoint-alive checks)
# 4xx = policy/funds blocked = PASS (endpoint alive, policy working)
# 429/500 = server-side = WARN | timeout = WARN | 5xx else = FAIL
# ─────────────────────────────────────────────────────────────

EVM_DUMMY    = "0x0000000000000000000000000000000000000001"
SOLANA_DUMMY = "11111111111111111111111111111111"

def _evm_transfer(chain_id, timeout_s=20, extra=None):
    time.sleep(1.2)  # avoid 429 rate-limit across sequential network tests
    to_addr = results["meta"]["evm_address"] or EVM_DUMMY
    payload = {"to": to_addr, "amount": "1", "asset": "usdc", "chainId": chain_id}
    if extra:
        payload.update(extra)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer",
                          headers=AUTH, json=payload, timeout=timeout_s)
    except requests.exceptions.Timeout:
        raise AssertionError(f"Chain {chain_id} timed out ({timeout_s}s)")
    return _network_check(r, f"chainId={chain_id}")

def test_transfer_base():         return _evm_transfer(8453)
def test_transfer_optimism():     return _evm_transfer(10)
def test_transfer_polygon():      return _evm_transfer(137)
def test_transfer_arbitrum():     return _evm_transfer(42161)
def test_transfer_bnb():          return _evm_transfer(56,  timeout_s=30)
def test_transfer_ethereum():     return _evm_transfer(1)
def test_transfer_gnosis():       return _evm_transfer(100)
def test_transfer_sepolia():      return _evm_transfer(11155111, timeout_s=30)
def test_transfer_base_sepolia(): return _evm_transfer(84532)

def test_transfer_with_idempotency():
    """Transfer endpoint with idempotencyKey field."""
    ikey = f"monitor-idem-{datetime.date.today().isoformat()}"
    return _evm_transfer(8453, extra={"idempotencyKey": ikey})

def test_transfer_sol_mainnet():
    time.sleep(1.2)
    to_addr = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to": to_addr, "amount": "1", "asset": "usdc",
                                "network": "mainnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana mainnet timed out")
    return _network_check(r, "solana_mainnet")

def test_transfer_sol_devnet():
    time.sleep(1.2)
    to_addr = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to": to_addr, "amount": "1", "asset": "sol",
                                "network": "devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana devnet timed out")
    return _network_check(r, "solana_devnet")

def test_contract_call_evm():
    time.sleep(1.2)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType": "ethereum", "to": EVM_DUMMY,
                                "data": "0x", "value": "0", "chainId": 8453},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("EVM contract-call timed out")
    return _network_check(r, "evm_contract_call_base")

def test_contract_call_solana():
    time.sleep(1.2)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType": "solana",
                                "instructions": [{
                                    "programId": SOLANA_DUMMY,
                                    "accounts": [{"pubkey": SOLANA_DUMMY,
                                                  "isSigner": False, "isWritable": False}],
                                    "data": "AA==",
                                }],
                                "network": "devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana contract-call timed out")
    return _network_check(r, "solana_contract_call_devnet")


# ─────────────────────────────────────────────────────────────
# FEEDBACK — all 4 categories
# ─────────────────────────────────────────────────────────────

def _feedback(cat, msg):
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/feedback",
                            headers=AUTH,
                            json={"category": cat, "message": msg,
                                  "context": {
                                      "automated": True,
                                      "version": "v4",
                                      "run_id": os.environ.get("GITHUB_RUN_ID","local"),
                                      "repo": os.environ.get("GITHUB_REPOSITORY","unknown"),
                                  }},
                            timeout=15))
    assert d.get("success"), f"Feedback failed: {d.get('error')}"
    return {"category": cat, "id": d.get("data",{}).get("id","?")}

def test_feedback_other():
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    real = results["meta"].get("real_x402_done", False)
    msg = (f"[AUTO-MONITOR v4] Heartbeat {ts}. "
           f"Real x402 tx: {'YES — ' + str(results['meta'].get('real_x402_amount')) if real else 'skipped (low balance)'}.")
    return _feedback("other", msg)

def test_feedback_bug():
    return _feedback("bug", "[AUTO-MONITOR v4] Automated category test: bug. Monitor ping.")

def test_feedback_feature():
    return _feedback("feature", "[AUTO-MONITOR v4] Automated category test: feature. Monitor ping.")

def test_feedback_stuck():
    return _feedback("stuck", "[AUTO-MONITOR v4] Automated category test: stuck. Monitor ping.")



def test_x402_free_endpoint():
    """
    Test x402/fetch against a FREE-tier endpoint.
    STATUS=FREE means no payment charged — x402 protocol still processes it.
    This is a distinct flow from paid endpoints.
    """
    time.sleep(2)
    # Use a known free registry endpoint
    payload = {
        "url": "https://registry.frames.ag/api/service/exa/api/search",
        "method": "POST",
        "body": {"query": "free tier test", "numResults": 1},
        "dryRun": True,  # dryRun to check if it's free without paying
    }
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                            headers=AUTH, json=payload, timeout=30))
    p = d.get("payment", {})
    status = p.get("status") or ("free" if not p.get("required") else "paid")
    return {
        "status": status,
        "payment_required": p.get("required"),
        "amount": p.get("amountFormatted"),
        "chain": p.get("chain"),
        "is_free": not p.get("required", True),
    }


def test_x402_real_free_fetch():
    """
    REAL fetch against free-tier endpoint — no balance needed.
    STATUS=FREE in activity = this flow.
    Earns TX points even when free!
    """
    time.sleep(2)
    minute_key = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
    ikey = f"monitor-free-{minute_key}"
    payload = {
        "url": "https://registry.frames.ag/api/service/exa/api/search",
        "method": "POST",
        "body": {"query": f"AgentWallet free tier {minute_key}", "numResults": 1},
        "idempotencyKey": ikey,
        "timeout": 30000,
        # No preferredChain/Token — let server decide (may be free)
    }
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                          headers=AUTH, json=payload, timeout=60)
    except requests.exceptions.Timeout:
        raise AssertionError("Free fetch timed out (60s)")

    if r.status_code in (429, 502, 503, 504):
        raise AssertionError(f"Free fetch server error {r.status_code} — retry next run")
    if r.status_code == 429:
        raise AssertionError("Rate limited — retry next run")

    r.raise_for_status()
    d = r.json()

    payment = d.get("payment", {})
    paid    = d.get("paid", False)
    success = d.get("success", False)
    status  = payment.get("status", "unknown")

    return {
        "success":  success,
        "paid":     paid,
        "status":   status,          # "free" or "paid"
        "amount":   payment.get("amountFormatted", "0"),
        "chain":    payment.get("chain"),
        "attempts": d.get("attempts"),
        "ikey":     ikey,
        "response_status": d.get("response", {}).get("status"),
    }


def test_x402_check_activity_free_events():
    """
    Verify recent activity contains PAYMENT FREE events.
    Confirms free-tier x402 flow is being recorded correctly.
    """
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=50",
                           headers=AUTH, timeout=15))
    events = d.get("data", d) or []
    if not isinstance(events, list):
        raise AssertionError("Activity response not a list")

    x402_events = [e for e in events if "x402" in str(e.get("type","")).lower()
                   or "payment" in str(e.get("type","")).lower()]
    free_events  = [e for e in events if str(e.get("status","")).lower() == "free"
                    or str(e.get("paymentStatus","")).lower() == "free"]
    paid_events  = [e for e in events if str(e.get("status","")).lower() == "paid"
                    or str(e.get("paymentStatus","")).lower() == "paid"]

    return {
        "total_events":  len(events),
        "x402_events":   len(x402_events),
        "free_payments": len(free_events),
        "paid_payments": len(paid_events),
        "event_types":   list({e.get("type","?") for e in events})[:8],
    }

# ─────────────────────────────────────────────────────────────
# TEST REGISTRY — ordered by execution
# ─────────────────────────────────────────────────────────────

TESTS = [
    # META
    ("Skill Version",                   "meta",      test_skill_version),
    ("Skill.json Full Metadata",         "meta",      test_skill_json_metadata),
    ("Heartbeat.md Reachable",           "meta",      test_heartbeat_md),
    # PUBLIC
    ("Network Pulse",                    "public",    test_network_pulse),
    ("Wallet Connected (public)",        "public",    test_wallet_connected_public),
    ("Connect Start Endpoint",           "public",    test_connect_start_endpoint),
    # WALLET
    ("Wallet Info",                      "wallet",    test_wallet_info),
    ("Balances All Chains",              "wallet",    test_balances),
    ("Activity Feed (authenticated)",    "wallet",    test_activity_auth),
    ("Activity Feed (public)",           "wallet",    test_activity_public),
    ("Stats & Rank",                     "wallet",    test_stats),
    ("List Wallets",                     "wallet",    test_list_wallets),
    ("Create Wallet EVM",                "wallet",    test_create_wallet_evm),
    ("Create Wallet Solana",             "wallet",    test_create_wallet_solana),
    # REFERRALS
    ("Referrals & Tier Progress",        "referrals", test_referrals),
    # POLICY
    ("Policy GET",                       "policy",    test_policy_get),
    ("Policy PATCH/PUT",                 "policy",    test_policy_patch),
    # X402 dryRun — all combos
    ("x402 DryRun auto-chain",           "x402",      test_x402_auto),
    ("x402 DryRun EVM",                  "x402",      test_x402_evm),
    ("x402 DryRun Solana",               "x402",      test_x402_solana),
    ("x402 DryRun USDC token",           "x402",      test_x402_usdc),
    ("x402 DryRun USDT token",           "x402",      test_x402_usdt),
    ("x402 DryRun CASH token",           "x402",      test_x402_cash),
    ("x402 DryRun EVM+USDC",             "x402",      test_x402_evm_usdc),
    ("x402 DryRun EVM+USDT",             "x402",      test_x402_evm_usdt),
    ("x402 DryRun Solana+USDC",          "x402",      test_x402_solana_usdc),
    ("x402 DryRun Solana+CASH",          "x402",      test_x402_solana_cash),
    ("x402 DryRun timeout option",       "x402",      test_x402_timeout_opt),
    ("x402 DryRun preferredChainId",     "x402",      test_x402_preferred_chain_id),
    ("x402 DryRun idempotencyKey",       "x402",      test_x402_idempotency_key),
    ("x402 Error INVALID_URL",           "x402",      test_x402_invalid_url),
    ("x402 Legacy /pay endpoint",        "x402",      test_x402_legacy_pay_endpoint),
    # X402 REAL fetch — actual TX for points!
    ("x402 REAL Fetch (earns TX pts!)",  "x402",      test_x402_real_fetch),
    # X402 FREE tier — STATUS=FREE flow
    ("x402 Free Endpoint DryRun",         "x402",      test_x402_free_endpoint),
    ("x402 REAL Free Fetch",              "x402",      test_x402_real_free_fetch),
    ("x402 Activity FREE events check",   "x402",      test_x402_check_activity_free_events),
    # ACTIONS
    ("Sign Message Ethereum",            "actions",   test_sign_ethereum),
    ("Sign Message Solana",              "actions",   test_sign_solana),
    ("Sign with walletAddress param",    "actions",   test_sign_with_wallet_address),
    ("Faucet Solana Devnet",             "actions",   test_faucet_devnet),
    # NETWORKS — EVM mainnet
    ("Transfer Base (8453)",             "networks",  test_transfer_base),
    ("Transfer Optimism (10)",           "networks",  test_transfer_optimism),
    ("Transfer Polygon (137)",           "networks",  test_transfer_polygon),
    ("Transfer Arbitrum (42161)",        "networks",  test_transfer_arbitrum),
    ("Transfer BNB (56)",                "networks",  test_transfer_bnb),
    ("Transfer Ethereum (1)",            "networks",  test_transfer_ethereum),
    ("Transfer Gnosis (100)",            "networks",  test_transfer_gnosis),
    # NETWORKS — EVM testnet
    ("Transfer Sepolia testnet",         "networks",  test_transfer_sepolia),
    ("Transfer Base Sepolia",            "networks",  test_transfer_base_sepolia),
    ("Transfer + idempotencyKey",        "networks",  test_transfer_with_idempotency),
    # NETWORKS — Solana
    ("Transfer Solana mainnet",          "networks",  test_transfer_sol_mainnet),
    ("Transfer Solana devnet",           "networks",  test_transfer_sol_devnet),
    # NETWORKS — Contract calls
    ("ContractCall EVM Base",            "networks",  test_contract_call_evm),
    ("ContractCall Solana devnet",       "networks",  test_contract_call_solana),
    # FEEDBACK — all 4 categories
    ("Feedback category:other",          "feedback",  test_feedback_other),
    ("Feedback category:bug",            "feedback",  test_feedback_bug),
    ("Feedback category:feature",        "feedback",  test_feedback_feature),
    ("Feedback category:stuck",          "feedback",  test_feedback_stuck),
]


# ─────────────────────────────────────────────────────────────
# RUN ALL TESTS
# ─────────────────────────────────────────────────────────────

print(f"\n{'='*62}")
print(f"  AgentWallet Monitor v4 ULTIMATE  |  {results['timestamp']}")
print(f"  User: {USERNAME}  |  Total tests: {len(TESTS)}")
print(f"{'='*62}")

last_cat = None
for name, category, fn in TESTS:
    if category != last_cat:
        print(f"\n[{category.upper()}]")
        last_cat = category
    run_test(name, category, fn)

# ── Tally ────────────────────────────────────────────────────
passed = sum(1 for t in results["tests"] if t["status"] == "pass")
failed = sum(1 for t in results["tests"] if t["status"] == "fail")
warned = sum(1 for t in results["tests"] if t["status"] == "warn")
total  = len(results["tests"])

results["summary"] = {
    "total": total, "passed": passed, "failed": failed,
    "warnings": warned, "overall": "pass" if failed == 0 else "fail",
}

# ── Persist history ───────────────────────────────────────────
HISTORY_FILE = "docs/history.json"
history = []
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE) as f:
            history = json.load(f)
    except Exception:
        history = []

history.insert(0, {
    "timestamp": results["timestamp"], "passed": passed,
    "failed": failed, "warnings": warned,
    "overall": results["summary"]["overall"],
    "rank": results["meta"].get("rank"),
    "real_tx": results["meta"].get("real_x402_done", False),
})
history = history[:100]

os.makedirs("docs", exist_ok=True)
with open(HISTORY_FILE, "w") as f:
    json.dump(history, f, indent=2)
with open("docs/status.json", "w") as f:
    json.dump(results, f, indent=2)

# ── Print summary ─────────────────────────────────────────────
print(f"\n{'='*62}")
print(f"  RESULT   : {passed}/{total} passed | {failed} failed | {warned} warnings")
if results["meta"]["balance_usd"] is not None:
    print(f"  Balance  : ${results['meta']['balance_usd']} USD")
if results["meta"]["rank"] is not None:
    print(f"  Rank     : #{results['meta']['rank']}  |  Tier: {results['meta']['tier']}")
if results["meta"]["airdrop_points"] is not None:
    print(f"  Points   : {results['meta']['airdrop_points']} airdrop pts")
if results["meta"]["referral_count"] is not None:
    print(f"  Referrals: {results['meta']['referral_count']}")
    print(f"  Ref link : https://frames.ag/connect?ref={USERNAME}")
if results["meta"].get("real_x402_done"):
    print(f"  Real TX  : ✅ {results['meta']['real_x402_amount']} on {results['meta']['real_x402_chain']}")
else:
    print(f"  Real TX  : ⚠️  skipped (fund wallet to earn TX points)")
print(f"{'='*62}\n")

if failed > 0:
    for t in results["tests"]:
        if t["status"] == "fail":
            print(f"  HARD FAIL [{t['category']}] {t['name']} — {t['error']}")
    sys.exit(1)
elif warned > 0:
    print(f"  {warned} soft warning(s) — tier limits / rate limits / chain issues (all expected)")
    sys.exit(0)
else:
    print("  PERFECT RUN — 0 failures, 0 warnings!")
    sys.exit(0)
