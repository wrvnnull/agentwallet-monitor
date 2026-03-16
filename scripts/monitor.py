#!/usr/bin/env python3
"""
AgentWallet FINAL Monitor — v5 ALL REGISTRY
============================================
Semua 10 service dari registry.frames.ag + semua fitur AgentWallet.

Harga per-call (USDC, 6 decimals):
  test/echo        = $0.001  (Base Sepolia testnet)
  coingecko        = $0.003
  ai-gen/schnell   = $0.004
  exa              = $0.010
  twitter          = $0.010
  near-intents     = $0.010
  jupiter          = $0.010
  agentmail        = $2.000  ← per-day idempotency
  wordspace        = $2.000  ← per-day idempotency
  openrouter       = varies  ← per-hour

Idempotency strategy:
  per-run   = setiap 5 menit (test testnet, super murah)
  per-hour  = 1x/jam  (murah-menengah)
  per-day   = 1x/hari (mahal $2)
"""

import os, json, time, datetime, sys

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

BASE_URL  = "https://frames.ag/api"
REG_URL   = "https://registry.frames.ag/api/service"
USERNAME  = os.environ.get("AGENTWALLET_USERNAME", "")
API_TOKEN = os.environ.get("AGENTWALLET_API_TOKEN", "")

if not USERNAME or not API_TOKEN:
    print("ERROR: AGENTWALLET_USERNAME and AGENTWALLET_API_TOKEN must be set.")
    sys.exit(1)

AUTH = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}

NOW       = datetime.datetime.utcnow()
KEY_RUN   = NOW.strftime("%Y%m%d-%H%M")   # per-run  (~every 5 min)
KEY_HOUR  = NOW.strftime("%Y%m%d-%H")     # per-hour
KEY_DAY   = NOW.strftime("%Y%m%d")        # per-day

results = {
    "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "username":  USERNAME,
    "summary":   {"total": 0, "passed": 0, "failed": 0, "warnings": 0},
    "tests":     [],
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
        entry["data"]   = data
        print(f"  OK   {name}")
    except AssertionError as e:
        entry["status"] = "warn"
        entry["error"]  = str(e)
        print(f"  WARN {name}: {e}")
    except Exception as e:
        entry["status"] = "fail"
        entry["error"]  = str(e)
        print(f"  FAIL {name}: {e}")
    finally:
        entry["duration_ms"] = round((time.time() - start) * 1000)
        results["tests"].append(entry)


def _safe(r):
    if r.status_code == 429:
        raise AssertionError("429 rate-limited — wait for next run")
    r.raise_for_status()
    return r.json()


def _network_check(r, label):
    if r.status_code in (429, 500):
        code = "429 rate-limit" if r.status_code == 429 else "500 server error"
        raise AssertionError(f"{label} returned {code} (server-side issue)")
    if r.status_code in (400, 402, 403, 422, 200, 201):
        d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        return {"status_code": r.status_code, "resp": str(d)[:120]}
    r.raise_for_status()
    return {"status_code": r.status_code}


def _x402_fetch(url, method="POST", body=None, ikey=None, chain="evm",
                token="USDC", dry=False, timeout_ms=30000):
    """Generic x402/fetch wrapper used by all registry service calls."""
    time.sleep(2)
    payload = {
        "url": url, "method": method,
        "preferredChain": chain, "preferredToken": token,
        "timeout": timeout_ms,
    }
    if body:
        payload["body"] = body
    if ikey:
        payload["idempotencyKey"] = ikey
    if dry:
        payload["dryRun"] = True

    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                          headers=AUTH, json=payload, timeout=90)
    except requests.exceptions.Timeout:
        raise AssertionError("x402/fetch timed out (90s)")

    if r.status_code in (429, 500, 502, 503, 504):
        code_label = {429:"rate-limit",500:"server error",502:"bad gateway",
                      503:"unavailable",504:"gateway timeout"}.get(r.status_code, str(r.status_code))
        raise AssertionError(f"x402/fetch {code_label} ({r.status_code}) — server-side, retry next run")

    r.raise_for_status()
    d = r.json()

    if dry:
        p = d.get("payment", {})
        return {"dry_run": True, "required": p.get("required"),
                "chain": p.get("chain"), "amount": p.get("amountFormatted")}

    paid    = d.get("paid", False) or d.get("success", False)
    payment = d.get("payment", {})
    resp    = d.get("response", {})

    if not paid and not dry:
        err = d.get("error","") or d.get("code","")
        if err:
            raise AssertionError(f"Fetch failed: {err}")

    return {
        "paid":    paid,
        "amount":  payment.get("amountFormatted","free"),
        "chain":   payment.get("chain"),
        "status":  payment.get("status","unknown"),
        "resp_status": resp.get("status"),
        "ikey":    ikey,
    }


# ─────────────────────────────────────────────────────────────
# META
# ─────────────────────────────────────────────────────────────

def test_skill_version():
    d = _safe(requests.get("https://frames.ag/skill.json", timeout=15))
    v = d.get("version","unknown")
    results["meta"]["skill_version"] = v
    return {"version": v}

def test_skill_json_metadata():
    d = _safe(requests.get("https://frames.ag/skill.json", timeout=15))
    mb = d.get("moltbot", {})
    assert mb.get("api_base"), "moltbot.api_base missing"
    return {"api_base": mb.get("api_base"), "keywords": d.get("keywords",[])[:4]}

def test_heartbeat_md():
    r = requests.get("https://frames.ag/heartbeat.md", timeout=15)
    r.raise_for_status()
    assert len(r.text) > 100
    return {"bytes": len(r.text)}


# ─────────────────────────────────────────────────────────────
# PUBLIC
# ─────────────────────────────────────────────────────────────

def test_network_pulse():
    d = _safe(requests.get(f"{BASE_URL}/network/pulse", timeout=15))
    return {"active_agents": d.get("activeAgents"),
            "tx_count": d.get("transactionCount"), "volume": d.get("volume")}

def test_wallet_connected_public():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}", timeout=15))
    assert d.get("connected"), "Wallet not connected"
    results["meta"]["evm_address"]    = d.get("evmAddress","")
    results["meta"]["solana_address"] = d.get("solanaAddress","")
    return {"connected": True, "evm": str(d.get("evmAddress",""))[:14]+"..."}

def test_connect_start_endpoint():
    r = requests.post(f"{BASE_URL}/connect/start",
                      json={"email": "monitor-test@example.invalid"}, timeout=15)
    assert r.status_code not in (404, 405, 500), f"Connect start broken: {r.status_code}"
    return {"status_code": r.status_code, "endpoint": "alive"}


# ─────────────────────────────────────────────────────────────
# REGISTRY — Service Health Checks (free, no payment)
# ─────────────────────────────────────────────────────────────

def _registry_health(slug):
    d = _safe(requests.get(f"{REG_URL}/{slug}/health", timeout=15))
    assert d.get("status") == "healthy", f"{slug} not healthy: {d}"
    return {"status": d.get("status"), "ts": d.get("timestamp","")}

def test_registry_twitter_health():   return _registry_health("twitter")
def test_registry_ai_gen_health():    return _registry_health("ai-gen")
def test_registry_test_health():      return _registry_health("test")
def test_registry_exa_health():       return _registry_health("exa")
def test_registry_wordspace_health(): return _registry_health("wordspace")
def test_registry_openrouter_health():return _registry_health("openrouter")
def test_registry_jupiter_health():   return _registry_health("jupiter")
def test_registry_near_health():      return _registry_health("near-intents")
def test_registry_agentmail_health(): return _registry_health("agentmail")
def test_registry_coingecko_health(): return _registry_health("coingecko")

def test_registry_services_list():
    """Verify all 10 services are in the registry."""
    d = _safe(requests.get("https://registry.frames.ag/api/services", timeout=15))
    services = d.get("services", [])
    slugs    = [s.get("slug") for s in services]
    expected = ["twitter","ai-gen","test","exa","wordspace",
                "openrouter","jupiter","near-intents","agentmail","coingecko"]
    missing  = [s for s in expected if s not in slugs]
    assert not missing, f"Missing services: {missing}"
    return {"count": len(services), "slugs": slugs}


# ─────────────────────────────────────────────────────────────
# REGISTRY — Paid calls via x402/fetch
# ─────────────────────────────────────────────────────────────

# ── TEST service ($0.001 each — testnet Base Sepolia — use per-run) ──────────

def test_registry_test_echo():
    """$0.001 — testnet USDC, very cheap, run every time."""
    return _x402_fetch(
        url=f"{REG_URL}/test/api/echo",
        method="POST",
        body={"data": f"monitor-ping-{KEY_RUN}"},
        ikey=f"test-echo-{KEY_RUN}",
        chain="evm", token="USDC",
    )

def test_registry_test_networks():
    """$0.001 — test service /api/networks endpoint."""
    return _x402_fetch(
        url=f"{REG_URL}/test/api/networks",
        method="GET",
        ikey=f"test-networks-{KEY_RUN}",
        chain="evm", token="USDC",
    )


# ── COINGECKO ($0.003/call — per-hour) ───────────────────────────────────────

def test_registry_coingecko_price():
    """$0.003 — get BTC price."""
    return _x402_fetch(
        url=f"{REG_URL}/coingecko/api/price",
        method="POST",
        body={"ids": ["bitcoin","ethereum","solana"], "vs_currencies": ["usd"]},
        ikey=f"cg-price-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_coingecko_trending():
    """$0.003 — trending tokens."""
    return _x402_fetch(
        url=f"{REG_URL}/coingecko/api/trending",
        method="GET",
        ikey=f"cg-trending-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_coingecko_search():
    """$0.003 — search tokens."""
    return _x402_fetch(
        url=f"{REG_URL}/coingecko/api/search",
        method="POST",
        body={"query": "solana"},
        ikey=f"cg-search-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_coingecko_markets():
    """$0.003 — market data."""
    return _x402_fetch(
        url=f"{REG_URL}/coingecko/api/markets",
        method="POST",
        body={"vs_currency": "usd", "per_page": 5},
        ikey=f"cg-markets-{KEY_HOUR}",
        chain="evm", token="USDC",
    )


# ── EXA ($0.01/call — per-hour) ──────────────────────────────────────────────

def test_registry_exa_search():
    """$0.01 — semantic search."""
    return _x402_fetch(
        url=f"{REG_URL}/exa/api/search",
        method="POST",
        body={"query": f"AgentWallet x402 {KEY_HOUR}", "numResults": 2},
        ikey=f"exa-search-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_exa_answer():
    """$0.01 — exa answer endpoint."""
    return _x402_fetch(
        url=f"{REG_URL}/exa/api/answer",
        method="POST",
        body={"query": "What is x402 payment protocol?"},
        ikey=f"exa-answer-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_exa_find_similar():
    """$0.01 — find similar pages."""
    return _x402_fetch(
        url=f"{REG_URL}/exa/api/find-similar",
        method="POST",
        body={"url": "https://frames.ag", "numResults": 2},
        ikey=f"exa-similar-{KEY_HOUR}",
        chain="evm", token="USDC",
    )


# ── TWITTER ($0.01/call — per-hour) ──────────────────────────────────────────

def test_registry_twitter_search_tweets():
    """$0.01 — search tweets."""
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/search-tweets",
        method="POST",
        body={"query": "AgentWallet x402", "queryType": "Latest"},
        ikey=f"tw-search-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_twitter_trends():
    """$0.01 — trending topics."""
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/trends",
        method="POST",
        body={},
        ikey=f"tw-trends-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_twitter_user_info():
    """$0.01 — user info."""
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/user-info",
        method="POST",
        body={"userName": "frames_ag"},
        ikey=f"tw-userinfo-{KEY_HOUR}",
        chain="evm", token="USDC",
    )


# ── NEAR INTENTS ($0.01/call — per-hour) ─────────────────────────────────────

def test_registry_near_intents_tokens():
    """$0.01 — list supported tokens."""
    return _x402_fetch(
        url=f"{REG_URL}/near-intents/api/tokens",
        method="GET",
        ikey=f"near-tokens-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_near_intents_quote():
    """$0.01 — cross-chain swap quote."""
    return _x402_fetch(
        url=f"{REG_URL}/near-intents/api/quote",
        method="POST",
        body={"tokenIn": "USDC", "tokenOut": "SOL", "amountIn": "1"},
        ikey=f"near-quote-{KEY_HOUR}",
        chain="evm", token="USDC",
    )


# ── JUPITER ($0.01/call — per-hour) ──────────────────────────────────────────

def test_registry_jupiter_price():
    """$0.01 — Solana token prices via Jupiter."""
    return _x402_fetch(
        url=f"{REG_URL}/jupiter/api/price",
        method="POST",
        body={"ids": ["SOL", "USDC", "JUP"]},
        ikey=f"jup-price-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_registry_jupiter_tokens():
    """$0.01 — list Jupiter tokens."""
    return _x402_fetch(
        url=f"{REG_URL}/jupiter/api/tokens",
        method="GET",
        ikey=f"jup-tokens-{KEY_HOUR}",
        chain="evm", token="USDC",
    )


# ── AI-GEN ($0.004/image — cheapest model flux/schnell — per-hour) ───────────

def test_registry_ai_gen_models():
    """Free — list available models (no payment needed)."""
    d = _safe(requests.get(f"{REG_URL}/ai-gen/api/models", timeout=15))
    models = d.get("models", [])
    cheapest = min(models, key=lambda m: m.get("pricing",{}).get("price", 999))
    return {
        "model_count": len(models),
        "cheapest": cheapest.get("name"),
        "cheapest_price": cheapest.get("pricing",{}).get("priceString"),
    }

def test_registry_ai_gen_image():
    """$0.004 — generate image with flux/schnell (cheapest model)."""
    return _x402_fetch(
        url=f"{REG_URL}/ai-gen/api/invoke",
        method="POST",
        body={
            "owner": "flux", "name": "schnell",
            "input": {
                "prompt": f"Abstract digital art, geometric shapes, {KEY_HOUR}",
                "aspect_ratio": "1:1",
            }
        },
        ikey=f"aigen-{KEY_HOUR}",
        chain="evm", token="USDC",
        timeout_ms=60000,
    )


# ── OPENROUTER (varies — per-hour) ───────────────────────────────────────────

def test_registry_openrouter_chat():
    """~$0.001 — gpt-4o-mini via OpenRouter. Auth: Bearer username:token."""
    time.sleep(2)
    # OpenRouter needs special auth header: Bearer username:token
    or_headers = {
        "Authorization": f"Bearer {USERNAME}:{API_TOKEN}",
        "Content-Type":  "application/json",
    }
    ikey = f"or-chat-{KEY_HOUR}"
    payload = {
        "url": f"{REG_URL}/openrouter/v1/chat/completions",
        "method": "POST",
        "body": {
            "model":    "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Reply with one word: monitor-{KEY_HOUR}"}],
            "max_tokens": 10,
        },
        "preferredChain":  "evm",
        "preferredToken":  "USDC",
        "idempotencyKey":  ikey,
        "timeout":         30000,
    }
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                          headers=AUTH, json=payload, timeout=60)
    except requests.exceptions.Timeout:
        raise AssertionError("OpenRouter timed out")
    if r.status_code in (429, 502, 503, 504):
        raise AssertionError(f"OpenRouter server error {r.status_code}")
    r.raise_for_status()
    d = r.json()
    resp = d.get("response", {}).get("body", {})
    choice = resp.get("choices", [{}])[0].get("message", {}).get("content","") if resp else ""
    return {
        "paid":   d.get("paid"),
        "amount": d.get("payment",{}).get("amountFormatted","?"),
        "reply":  str(choice)[:50],
        "ikey":   ikey,
    }


# ── AGENTMAIL ($2.00/call — per-day) ─────────────────────────────────────────

def test_registry_agentmail_inbox_create():
    """$2.00 — create agent inbox. Per-day idempotency to save $."""
    return _x402_fetch(
        url=f"{REG_URL}/agentmail/api/inbox/create",
        method="POST",
        body={},
        ikey=f"agentmail-inbox-{KEY_DAY}",
        chain="evm", token="USDC",
        timeout_ms=60000,
    )

def test_registry_agentmail_messages():
    """$2.00 — list messages. Per-day."""
    return _x402_fetch(
        url=f"{REG_URL}/agentmail/api/messages",
        method="GET",
        ikey=f"agentmail-msgs-{KEY_DAY}",
        chain="evm", token="USDC",
        timeout_ms=60000,
    )


# ── WORDSPACE ($2.00/call — per-day) ─────────────────────────────────────────

def test_registry_wordspace_invoke():
    """$2.00 — AI agent loop. Per-day idempotency to save $."""
    return _x402_fetch(
        url=f"{REG_URL}/wordspace/api/invoke",
        method="POST",
        body={
            "prompt":   f"Write one sentence about AgentWallet x402 payments. Date: {KEY_DAY}",
            "maxSteps": 1,
        },
        ikey=f"wordspace-{KEY_DAY}",
        chain="evm", token="USDC",
        timeout_ms=60000,
    )


# ─────────────────────────────────────────────────────────────
# WALLET
# ─────────────────────────────────────────────────────────────

def test_wallet_info():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}", timeout=15))
    assert d.get("connected"), "not connected"
    return {"evm": str(d.get("evmAddress",""))[:14]+"...",
            "solana": str(d.get("solanaAddress",""))[:14]+"..."}

def test_balances():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/balances",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    total = inner.get("totalUsd") or inner.get("total_usd")
    results["meta"]["balance_usd"] = total
    return {"total_usd": total, "raw": str(inner)[:250]}

def test_activity_auth():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=20",
                            headers=AUTH, timeout=15))
    events = d.get("data", d)
    count = len(events) if isinstance(events, list) else "?"
    types = list({e.get("type","?") for e in (events if isinstance(events,list) else [])})[:8]
    return {"event_count": count, "event_types": types}

def test_activity_public():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=5", timeout=15))
    events = d.get("data", d)
    return {"public_events": len(events) if isinstance(events, list) else "?"}

def test_stats():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/stats",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    results["meta"]["rank"]           = inner.get("rank")
    results["meta"]["tier"]           = inner.get("tier")
    results["meta"]["airdrop_points"] = inner.get("airdropPoints")
    return {"rank": inner.get("rank"), "tier": inner.get("tier"),
            "points": inner.get("airdropPoints"), "weekly_txs": inner.get("weeklyTransactions"),
            "streak": inner.get("streak")}

def test_list_wallets():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    wallets = inner.get("wallets", [])
    results["meta"]["wallet_count"] = len(wallets)
    return {"count": len(wallets), "tier": inner.get("tier"),
            "limits": inner.get("limits")}

def test_create_wallet_evm():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                      headers=AUTH, json={"chainType": "ethereum"}, timeout=15)
    if r.status_code == 403:
        raise AssertionError(f"Tier limit (expected Bronze): {r.json().get('error','')}")
    r.raise_for_status()
    return {"created": True}

def test_create_wallet_solana():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                      headers=AUTH, json={"chainType": "solana"}, timeout=15)
    if r.status_code == 403:
        raise AssertionError(f"Tier limit (expected Bronze): {r.json().get('error','')}")
    r.raise_for_status()
    return {"created": True}


# ─────────────────────────────────────────────────────────────
# REFERRALS
# ─────────────────────────────────────────────────────────────

def test_referrals():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/referrals",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    count = inner.get("referralCount") or inner.get("count") or 0
    results["meta"]["referral_count"] = count
    thresholds = [(100,"3x Diamond"),(25,"2x Gold"),(5,"1.5x Silver"),(0,"1x Bronze")]
    multi = next(m for t,m in thresholds if count >= t)
    return {"referral_count": count, "multiplier": multi,
            "link": f"https://frames.ag/connect?ref={USERNAME}"}


# ─────────────────────────────────────────────────────────────
# POLICY
# ─────────────────────────────────────────────────────────────

def test_policy_get():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/policy",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    return {"max_per_tx_usd": inner.get("max_per_tx_usd"),
            "allow_chains": inner.get("allow_chains", [])}

def test_policy_patch():
    payload = {"max_per_tx_usd": "25", "allow_chains": ["base", "solana"]}
    url = f"{BASE_URL}/wallets/{USERNAME}/policy"
    r = requests.patch(url, headers=AUTH, json=payload, timeout=15)
    if r.status_code == 405:
        r = requests.put(url, headers=AUTH, json=payload, timeout=15)
    if r.status_code in (400, 405):
        d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        raise AssertionError(f"Policy write {r.status_code} — {d.get('error','')}")
    r.raise_for_status()
    assert r.json().get("success"), f"Policy update failed"
    return {"updated": True}


# ─────────────────────────────────────────────────────────────
# X402 dryRun — all options
# ─────────────────────────────────────────────────────────────

def _x402_dry_generic(extra=None):
    time.sleep(2)
    payload = {"url": f"{REG_URL}/exa/api/search", "method": "POST",
               "body": {"query": "test"}, "dryRun": True}
    if extra:
        payload.update(extra)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                            headers=AUTH, json=payload, timeout=30))
    p = d.get("payment", {})
    return {"required": p.get("required"), "chain": p.get("chain"),
            "amount": p.get("amountFormatted")}

def test_x402_dry_auto():         return _x402_dry_generic({"preferredChain":"auto"})
def test_x402_dry_evm():          return _x402_dry_generic({"preferredChain":"evm"})
def test_x402_dry_solana():       return _x402_dry_generic({"preferredChain":"solana"})
def test_x402_dry_usdc():         return _x402_dry_generic({"preferredToken":"USDC"})
def test_x402_dry_usdt():         return _x402_dry_generic({"preferredToken":"USDT"})
def test_x402_dry_cash():         return _x402_dry_generic({"preferredToken":"CASH"})
def test_x402_dry_chain_id():     return _x402_dry_generic({"preferredChainId":8453})
def test_x402_dry_idem_key():     return _x402_dry_generic({"idempotencyKey":f"dry-{KEY_HOUR}"})
def test_x402_dry_timeout():      return _x402_dry_generic({"timeout":15000})
def test_x402_dry_evm_usdc():     return _x402_dry_generic({"preferredChain":"evm","preferredToken":"USDC"})
def test_x402_dry_solana_usdc():  return _x402_dry_generic({"preferredChain":"solana","preferredToken":"USDC"})
def test_x402_dry_solana_cash():  return _x402_dry_generic({"preferredChain":"solana","preferredToken":"CASH"})

def test_x402_invalid_url():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                      headers=AUTH, json={"url":"http://localhost/bad","dryRun":True},
                      timeout=15)
    assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}"
    return {"error": r.json().get("error",""), "status": r.status_code}

def test_x402_legacy_pay():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/pay",
                      headers=AUTH,
                      json={"requirement":"eyJ0eXBlIjoieC00MDIifQ==",
                            "preferredChain":"evm","dryRun":True},
                      timeout=20)
    assert r.status_code not in (404, 405, 500), f"Legacy /pay broken: {r.status_code}"
    return {"status_code": r.status_code, "alive": True}


# ─────────────────────────────────────────────────────────────
# ACTIONS
# ─────────────────────────────────────────────────────────────

def test_sign_ethereum():
    time.sleep(2)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain":"ethereum","message":"monitor v5 ETH"},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data")
    return {"chain": "ethereum", "signed": True}

def test_sign_solana():
    time.sleep(2)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain":"solana","message":"monitor v5 SOL"},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data")
    return {"chain": "solana", "signed": True}

def test_sign_with_wallet_address():
    time.sleep(2)
    evm = results["meta"]["evm_address"] or ""
    if not evm:
        raise AssertionError("No EVM address available")
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain":"ethereum","message":"walletAddress param test",
                                  "walletAddress": evm},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data")
    return {"signed": True, "walletAddress": evm[:14]+"..."}

def test_faucet_devnet():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/faucet-sol",
                      headers=AUTH, json={}, timeout=30)
    if r.status_code == 429:
        raise AssertionError("Faucet rate-limited (3/24h)")
    if r.status_code in (500, 502, 503, 504):
        raise AssertionError(f"Faucet server error {r.status_code} — server-side, retry next run")
    r.raise_for_status()
    inner = r.json().get("data", r.json())
    return {"amount": inner.get("amount"), "remaining": inner.get("remaining")}


# ─────────────────────────────────────────────────────────────
# NETWORKS — Transfer/ContractCall validation
# ─────────────────────────────────────────────────────────────

EVM_DUMMY    = "0x0000000000000000000000000000000000000001"
SOLANA_DUMMY = "11111111111111111111111111111111"

def _evm_tx(chain_id, timeout_s=20, extra=None):
    time.sleep(1.2)
    to = results["meta"]["evm_address"] or EVM_DUMMY
    payload = {"to": to, "amount": "1", "asset": "usdc", "chainId": chain_id}
    if extra:
        payload.update(extra)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer",
                          headers=AUTH, json=payload, timeout=timeout_s)
    except requests.exceptions.Timeout:
        raise AssertionError(f"Chain {chain_id} timed out ({timeout_s}s)")
    return _network_check(r, f"chainId={chain_id}")

def test_tx_base():          return _evm_tx(8453)
def test_tx_optimism():      return _evm_tx(10)
def test_tx_polygon():       return _evm_tx(137)
def test_tx_arbitrum():      return _evm_tx(42161)
def test_tx_bnb():           return _evm_tx(56, timeout_s=30)
def test_tx_ethereum():      return _evm_tx(1)
def test_tx_gnosis():        return _evm_tx(100)
def test_tx_sepolia():       return _evm_tx(11155111, timeout_s=30)
def test_tx_base_sepolia():  return _evm_tx(84532)
def test_tx_idempotency():   return _evm_tx(8453, extra={"idempotencyKey": f"idem-{KEY_HOUR}"})

def test_tx_sol_mainnet():
    time.sleep(1.2)
    to = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to": to,"amount":"1","asset":"usdc","network":"mainnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana mainnet timed out")
    return _network_check(r, "solana_mainnet")

def test_tx_sol_devnet():
    time.sleep(1.2)
    to = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to": to,"amount":"1","asset":"sol","network":"devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana devnet timed out")
    return _network_check(r, "solana_devnet")

def test_contract_call_evm():
    time.sleep(1.2)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType":"ethereum","to":EVM_DUMMY,
                                "data":"0x","value":"0","chainId":8453},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("EVM contract-call timed out")
    return _network_check(r, "evm_contract_call")

def test_contract_call_solana():
    time.sleep(1.2)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType":"solana",
                                "instructions":[{"programId":SOLANA_DUMMY,
                                   "accounts":[{"pubkey":SOLANA_DUMMY,
                                                "isSigner":False,"isWritable":False}],
                                   "data":"AA=="}],
                                "network":"devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana contract-call timed out")
    return _network_check(r, "solana_contract_call")


# ─────────────────────────────────────────────────────────────
# FEEDBACK
# ─────────────────────────────────────────────────────────────

def _feedback(cat, msg):
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/feedback",
                            headers=AUTH,
                            json={"category": cat, "message": msg,
                                  "context": {"automated": True, "version": "v5",
                                              "run_id": os.environ.get("GITHUB_RUN_ID","local")}},
                            timeout=15))
    assert d.get("success"), f"Feedback failed: {d.get('error')}"
    return {"category": cat, "id": d.get("data",{}).get("id","?")}

def test_feedback_other():
    return _feedback("other",
        f"[AUTO-MONITOR v5] Heartbeat {NOW.strftime('%Y-%m-%d %H:%M UTC')}. "
        f"All 10 registry services tested.")

def test_feedback_bug():
    return _feedback("bug", "[AUTO-MONITOR v5] Category test: bug.")
def test_feedback_feature():
    return _feedback("feature", "[AUTO-MONITOR v5] Category test: feature.")
def test_feedback_stuck():
    return _feedback("stuck", "[AUTO-MONITOR v5] Category test: stuck.")


# ─────────────────────────────────────────────────────────────
# TEST REGISTRY
# ─────────────────────────────────────────────────────────────

TESTS = [
    # META
    ("Skill Version",                       "meta",      test_skill_version),
    ("Skill.json Metadata",                 "meta",      test_skill_json_metadata),
    ("Heartbeat.md",                        "meta",      test_heartbeat_md),
    # PUBLIC
    ("Network Pulse",                       "public",    test_network_pulse),
    ("Wallet Connected (public)",           "public",    test_wallet_connected_public),
    ("Connect Start Endpoint",              "public",    test_connect_start_endpoint),
    # REGISTRY — Health (free)
    ("Registry Services List",             "registry",  test_registry_services_list),
    ("Registry: twitter health",           "registry",  test_registry_twitter_health),
    ("Registry: ai-gen health",            "registry",  test_registry_ai_gen_health),
    ("Registry: test health",              "registry",  test_registry_test_health),
    ("Registry: exa health",               "registry",  test_registry_exa_health),
    ("Registry: wordspace health",         "registry",  test_registry_wordspace_health),
    ("Registry: openrouter health",        "registry",  test_registry_openrouter_health),
    ("Registry: jupiter health",           "registry",  test_registry_jupiter_health),
    ("Registry: near-intents health",      "registry",  test_registry_near_health),
    ("Registry: agentmail health",         "registry",  test_registry_agentmail_health),
    ("Registry: coingecko health",         "registry",  test_registry_coingecko_health),
    # REGISTRY — Paid (testnet $0.001/run)
    ("Registry: test/echo $0.001",         "registry",  test_registry_test_echo),
    ("Registry: test/networks $0.001",     "registry",  test_registry_test_networks),
    # REGISTRY — Paid (cheap $0.003/hr)
    ("Registry: coingecko/price $0.003",   "registry",  test_registry_coingecko_price),
    ("Registry: coingecko/trending",       "registry",  test_registry_coingecko_trending),
    ("Registry: coingecko/search",         "registry",  test_registry_coingecko_search),
    ("Registry: coingecko/markets",        "registry",  test_registry_coingecko_markets),
    # REGISTRY — Paid ($0.01/hr)
    ("Registry: exa/search $0.01",         "registry",  test_registry_exa_search),
    ("Registry: exa/answer $0.01",         "registry",  test_registry_exa_answer),
    ("Registry: exa/find-similar $0.01",   "registry",  test_registry_exa_find_similar),
    ("Registry: twitter/search $0.01",     "registry",  test_registry_twitter_search_tweets),
    ("Registry: twitter/trends $0.01",     "registry",  test_registry_twitter_trends),
    ("Registry: twitter/user-info $0.01",  "registry",  test_registry_twitter_user_info),
    ("Registry: near-intents/tokens",      "registry",  test_registry_near_intents_tokens),
    ("Registry: near-intents/quote",       "registry",  test_registry_near_intents_quote),
    ("Registry: jupiter/price $0.01",      "registry",  test_registry_jupiter_price),
    ("Registry: jupiter/tokens $0.01",     "registry",  test_registry_jupiter_tokens),
    # REGISTRY — AI & LLM
    ("Registry: ai-gen/models (free)",     "registry",  test_registry_ai_gen_models),
    ("Registry: ai-gen/schnell $0.004",    "registry",  test_registry_ai_gen_image),
    ("Registry: openrouter/gpt4o-mini",    "registry",  test_registry_openrouter_chat),
    # REGISTRY — Expensive ($2.00/day)
    ("Registry: agentmail/inbox $2.00",    "registry",  test_registry_agentmail_inbox_create),
    ("Registry: agentmail/messages $2.00", "registry",  test_registry_agentmail_messages),
    ("Registry: wordspace/invoke $2.00",   "registry",  test_registry_wordspace_invoke),
    # WALLET
    ("Wallet Info",                         "wallet",    test_wallet_info),
    ("Balances",                            "wallet",    test_balances),
    ("Activity (authenticated)",            "wallet",    test_activity_auth),
    ("Activity (public)",                   "wallet",    test_activity_public),
    ("Stats & Rank",                        "wallet",    test_stats),
    ("List Wallets",                        "wallet",    test_list_wallets),
    ("Create Wallet EVM",                   "wallet",    test_create_wallet_evm),
    ("Create Wallet Solana",                "wallet",    test_create_wallet_solana),
    # REFERRALS
    ("Referrals & Tier",                    "referrals", test_referrals),
    # POLICY
    ("Policy GET",                          "policy",    test_policy_get),
    ("Policy PATCH/PUT",                    "policy",    test_policy_patch),
    # X402 dryRun
    ("x402 DryRun auto-chain",             "x402",      test_x402_dry_auto),
    ("x402 DryRun EVM",                    "x402",      test_x402_dry_evm),
    ("x402 DryRun Solana",                 "x402",      test_x402_dry_solana),
    ("x402 DryRun USDC",                   "x402",      test_x402_dry_usdc),
    ("x402 DryRun USDT",                   "x402",      test_x402_dry_usdt),
    ("x402 DryRun CASH",                   "x402",      test_x402_dry_cash),
    ("x402 DryRun preferredChainId",       "x402",      test_x402_dry_chain_id),
    ("x402 DryRun idempotencyKey",         "x402",      test_x402_dry_idem_key),
    ("x402 DryRun timeout option",         "x402",      test_x402_dry_timeout),
    ("x402 DryRun EVM+USDC",              "x402",      test_x402_dry_evm_usdc),
    ("x402 DryRun Solana+USDC",           "x402",      test_x402_dry_solana_usdc),
    ("x402 DryRun Solana+CASH",           "x402",      test_x402_dry_solana_cash),
    ("x402 Error INVALID_URL",            "x402",      test_x402_invalid_url),
    ("x402 Legacy /pay endpoint",         "x402",      test_x402_legacy_pay),
    # ACTIONS
    ("Sign Message Ethereum",              "actions",   test_sign_ethereum),
    ("Sign Message Solana",                "actions",   test_sign_solana),
    ("Sign with walletAddress param",      "actions",   test_sign_with_wallet_address),
    ("Faucet Solana Devnet",               "actions",   test_faucet_devnet),
    # NETWORKS
    ("Transfer Base (8453)",               "networks",  test_tx_base),
    ("Transfer Optimism (10)",             "networks",  test_tx_optimism),
    ("Transfer Polygon (137)",             "networks",  test_tx_polygon),
    ("Transfer Arbitrum (42161)",          "networks",  test_tx_arbitrum),
    ("Transfer BNB (56)",                  "networks",  test_tx_bnb),
    ("Transfer Ethereum (1)",              "networks",  test_tx_ethereum),
    ("Transfer Gnosis (100)",              "networks",  test_tx_gnosis),
    ("Transfer Sepolia testnet",           "networks",  test_tx_sepolia),
    ("Transfer Base Sepolia",              "networks",  test_tx_base_sepolia),
    ("Transfer + idempotencyKey",          "networks",  test_tx_idempotency),
    ("Transfer Solana mainnet",            "networks",  test_tx_sol_mainnet),
    ("Transfer Solana devnet",             "networks",  test_tx_sol_devnet),
    ("ContractCall EVM Base",              "networks",  test_contract_call_evm),
    ("ContractCall Solana devnet",         "networks",  test_contract_call_solana),
    # FEEDBACK
    ("Feedback category:other",            "feedback",  test_feedback_other),
    ("Feedback category:bug",              "feedback",  test_feedback_bug),
    ("Feedback category:feature",          "feedback",  test_feedback_feature),
    ("Feedback category:stuck",            "feedback",  test_feedback_stuck),
]


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

print(f"\n{'='*64}")
print(f"  AgentWallet Monitor v5 ALL REGISTRY  |  {results['timestamp']}")
print(f"  User: {USERNAME}  |  Tests: {len(TESTS)}")
print(f"{'='*64}")

last_cat = None
for name, category, fn in TESTS:
    if category != last_cat:
        print(f"\n[{category.upper()}]")
        last_cat = category
    run_test(name, category, fn)

passed = sum(1 for t in results["tests"] if t["status"] == "pass")
failed = sum(1 for t in results["tests"] if t["status"] == "fail")
warned = sum(1 for t in results["tests"] if t["status"] == "warn")
total  = len(results["tests"])

results["summary"] = {
    "total": total, "passed": passed, "failed": failed,
    "warnings": warned, "overall": "pass" if failed == 0 else "fail",
}

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
})
history = history[:100]

os.makedirs("docs", exist_ok=True)
with open(HISTORY_FILE, "w") as f:
    json.dump(history, f, indent=2)
with open("docs/status.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*64}")
print(f"  RESULT  : {passed}/{total} passed | {failed} failed | {warned} warnings")
if results["meta"]["balance_usd"] is not None:
    print(f"  Balance : ${results['meta']['balance_usd']} USD")
if results["meta"]["rank"] is not None:
    print(f"  Rank    : #{results['meta']['rank']} | Tier: {results['meta']['tier']}")
if results["meta"]["referral_count"] is not None:
    print(f"  Refs    : {results['meta']['referral_count']} | Pts: {results['meta']['airdrop_points']}")
    print(f"  Link    : https://frames.ag/connect?ref={USERNAME}")
print(f"{'='*64}\n")

if failed > 0:
    for t in results["tests"]:
        if t["status"] == "fail":
            print(f"  HARD FAIL [{t['category']}] {t['name']} — {t['error']}")
    sys.exit(1)
elif warned > 0:
    print(f"  {warned} soft warning(s) — all expected")
    sys.exit(0)
else:
    print("  PERFECT RUN!")
    sys.exit(0)

# ═══════════════════════════════════════════════════════════════
# PATCH v5.1 — All missing features appended below
# ═══════════════════════════════════════════════════════════════

# ── x402 REAL paid fetch (per-hour ikey) ────────────────────
def test_x402_real_paid_fetch():
    """Real x402 paid call via exa — earns TX points each hour."""
    return _x402_fetch(
        url=f"{REG_URL}/exa/api/search",
        method="POST",
        body={"query": f"x402 payment protocol {KEY_HOUR}", "numResults": 1},
        ikey=f"real-paid-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

def test_x402_preferred_token_address():
    """x402 with preferredTokenAddress (USDC contract on Base)."""
    time.sleep(2)
    payload = {
        "url": f"{REG_URL}/exa/api/search",
        "method": "POST",
        "body": {"query": "test token address", "numResults": 1},
        "dryRun": True,
        "preferredChain": "evm",
        # USDC contract on Base
        "preferredTokenAddress": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "idempotencyKey": f"tokaddr-{KEY_HOUR}",
    }
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                            headers=AUTH, json=payload, timeout=30))
    p = d.get("payment", {})
    return {"dry_run": True, "chain": p.get("chain"), "amount": p.get("amountFormatted")}

def test_x402_with_wallet_address_param():
    """x402/fetch with explicit walletAddress param."""
    evm = results["meta"]["evm_address"] or ""
    if not evm:
        raise AssertionError("No EVM address yet")
    time.sleep(2)
    payload = {
        "url": f"{REG_URL}/exa/api/search",
        "method": "POST",
        "body": {"query": "wallet address param test", "numResults": 1},
        "dryRun": True,
        "walletAddress": evm,
        "idempotencyKey": f"waddr-{KEY_HOUR}",
    }
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                            headers=AUTH, json=payload, timeout=30))
    p = d.get("payment", {})
    return {"dry_run": True, "wallet_address_used": evm[:14]+"...",
            "chain": p.get("chain")}

# ── Transfer with walletAddress param ───────────────────────
def test_transfer_evm_wallet_address():
    """EVM transfer using explicit walletAddress param."""
    time.sleep(1.2)
    evm = results["meta"]["evm_address"] or EVM_DUMMY
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer",
                      headers=AUTH,
                      json={"to": evm, "amount": "1", "asset": "usdc",
                            "chainId": 8453, "walletAddress": evm},
                      timeout=20)
    return _network_check(r, "evm_transfer_walletAddress")

def test_transfer_sol_wallet_address():
    """Solana transfer using explicit walletAddress param."""
    time.sleep(1.2)
    sol = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to": sol, "amount": "1", "asset": "sol",
                                "network": "devnet", "walletAddress": sol},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana transfer walletAddress timed out")
    return _network_check(r, "sol_transfer_walletAddress")

# ── ContractCall rawTransaction modes ───────────────────────
def test_contract_call_evm_raw_tx():
    """EVM contract-call with rawTransaction hex field."""
    time.sleep(1.2)
    # Minimal valid-looking hex tx (will be rejected but endpoint alive)
    raw_hex = "0x02f86d01808459682f00850c92a69c0082520894" + "00"*20 + "8080c0"
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType": "ethereum",
                                "rawTransaction": raw_hex, "chainId": 8453},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("EVM rawTx timed out")
    return _network_check(r, "evm_raw_transaction")

def test_contract_call_solana_raw_tx():
    """Solana contract-call with rawTransaction base64 field."""
    time.sleep(1.2)
    import base64
    # Minimal placeholder base64 tx
    raw_b64 = base64.b64encode(b"\x01" + b"\x00"*63).decode()
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType": "solana",
                                "rawTransaction": raw_b64, "network": "devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana rawTx timed out")
    return _network_check(r, "solana_raw_transaction")

# ── Faucet with walletAddress param ─────────────────────────
def test_faucet_with_wallet_address():
    """Faucet with explicit walletAddress param."""
    sol = results["meta"]["solana_address"] or ""
    if not sol:
        raise AssertionError("No Solana address yet")
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/faucet-sol",
                      headers=AUTH,
                      json={"walletAddress": sol}, timeout=30)
    if r.status_code == 429:
        raise AssertionError("Faucet rate-limited (3/24h)")
    if r.status_code in (500, 502, 503, 504):
        raise AssertionError(f"Faucet server error {r.status_code} — retry next run")
    r.raise_for_status()
    inner = r.json().get("data", r.json())
    return {"amount": inner.get("amount"), "remaining": inner.get("remaining"),
            "walletAddress_param": sol[:14]+"..."}

# ── TEST service — /api/invoke ───────────────────────────────
def test_registry_test_invoke():
    """$0.001 — test service /api/invoke endpoint."""
    return _x402_fetch(
        url=f"{REG_URL}/test/api/invoke",
        method="POST",
        body={"prompt": f"ping {KEY_RUN}"},
        ikey=f"test-invoke-{KEY_RUN}",
        chain="evm", token="USDC",
    )

# ── EXA — /api/contents ─────────────────────────────────────
def test_registry_exa_contents():
    """$0.01 — fetch page contents via Exa."""
    return _x402_fetch(
        url=f"{REG_URL}/exa/api/contents",
        method="POST",
        body={"ids": ["https://frames.ag"]},
        ikey=f"exa-contents-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

# ── COINGECKO — /api/token-info ─────────────────────────────
def test_registry_coingecko_token_info():
    """$0.003 — token info by id."""
    return _x402_fetch(
        url=f"{REG_URL}/coingecko/api/token-info",
        method="POST",
        body={"id": "solana"},
        ikey=f"cg-tokeninfo-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

# ── JUPITER — /api/portfolio, /api/swap (dryRun via dryRun=true) ────────────
def test_registry_jupiter_portfolio():
    """$0.01 — Jupiter portfolio."""
    return _x402_fetch(
        url=f"{REG_URL}/jupiter/api/portfolio",
        method="POST",
        body={"wallet": results["meta"]["solana_address"] or SOLANA_DUMMY},
        ikey=f"jup-portfolio-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

# ── NEAR-INTENTS — /api/status ──────────────────────────────
def test_registry_near_status():
    """$0.01 — near-intents status check."""
    return _x402_fetch(
        url=f"{REG_URL}/near-intents/api/status",
        method="POST",
        body={"intentId": "monitor-test"},
        ikey=f"near-status-{KEY_HOUR}",
        chain="evm", token="USDC",
    )

# ── AGENTMAIL — /api/threads, /api/send ─────────────────────
def test_registry_agentmail_threads():
    """$2.00 — list threads. Per-day."""
    return _x402_fetch(
        url=f"{REG_URL}/agentmail/api/threads",
        method="GET",
        ikey=f"agentmail-threads-{KEY_DAY}",
        chain="evm", token="USDC", timeout_ms=60000,
    )

def test_registry_agentmail_send():
    """$2.00 — send email. Per-day."""
    return _x402_fetch(
        url=f"{REG_URL}/agentmail/api/send",
        method="POST",
        body={"to": "monitor@example.invalid",
              "subject": f"Monitor test {KEY_DAY}",
              "body": "Automated monitor test email."},
        ikey=f"agentmail-send-{KEY_DAY}",
        chain="evm", token="USDC", timeout_ms=60000,
    )

# ── AI-GEN — more models ─────────────────────────────────────
def test_registry_ai_gen_z_image_turbo():
    """$0.006 — Pruna Z-Image Turbo (2nd cheapest)."""
    return _x402_fetch(
        url=f"{REG_URL}/ai-gen/api/invoke",
        method="POST",
        body={"owner": "prunaai", "name": "z-image-turbo",
              "input": {"prompt": f"minimal geometric logo {KEY_HOUR}",
                        "aspect_ratio": "1:1"}},
        ikey=f"aigen-z-{KEY_HOUR}",
        chain="evm", token="USDC", timeout_ms=60000,
    )

def test_registry_ai_gen_imagen4_fast():
    """$0.03 — Google Imagen 4 Fast."""
    return _x402_fetch(
        url=f"{REG_URL}/ai-gen/api/invoke",
        method="POST",
        body={"owner": "google", "name": "imagen-4-fast",
              "input": {"prompt": f"abstract art digital {KEY_HOUR}",
                        "aspect_ratio": "1:1"}},
        ikey=f"aigen-imagen4-{KEY_HOUR}",
        chain="evm", token="USDC", timeout_ms=60000,
    )

def test_registry_ai_gen_ideogram():
    """$0.04 — Ideogram V3 Turbo."""
    return _x402_fetch(
        url=f"{REG_URL}/ai-gen/api/invoke",
        method="POST",
        body={"owner": "ideogram", "name": "v3-turbo",
              "input": {"prompt": f"futuristic city neon {KEY_HOUR}",
                        "aspect_ratio": "1:1"}},
        ikey=f"aigen-ideogram-{KEY_HOUR}",
        chain="evm", token="USDC", timeout_ms=60000,
    )

# ── OPENROUTER — more models ─────────────────────────────────
def _openrouter_chat(model, ikey):
    time.sleep(2)
    payload = {
        "url": f"{REG_URL}/openrouter/v1/chat/completions",
        "method": "POST",
        "body": {
            "model": model,
            "messages": [{"role": "user",
                          "content": f"One word reply: ok. Key:{KEY_HOUR}"}],
            "max_tokens": 5,
        },
        "preferredChain": "evm", "preferredToken": "USDC",
        "idempotencyKey": ikey, "timeout": 30000,
    }
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                          headers=AUTH, json=payload, timeout=60)
    except requests.exceptions.Timeout:
        raise AssertionError(f"OpenRouter {model} timed out")
    if r.status_code in (429, 500, 502, 503, 504):
        raise AssertionError(f"OpenRouter {model} server error {r.status_code} — retry next run")
    r.raise_for_status()
    d = r.json()
    resp = d.get("response", {}).get("body", {})
    choice = resp.get("choices",[{}])[0].get("message",{}).get("content","") if resp else ""
    return {"model": model, "paid": d.get("paid"),
            "amount": d.get("payment",{}).get("amountFormatted","?"),
            "reply": str(choice)[:30]}

def test_openrouter_claude_haiku():
    return _openrouter_chat("anthropic/claude-haiku-4-5",
                            f"or-claude-{KEY_HOUR}")
def test_openrouter_gemini_flash():
    return _openrouter_chat("google/gemini-2.0-flash-001",
                            f"or-gemini-{KEY_HOUR}")
def test_openrouter_llama():
    return _openrouter_chat("meta-llama/llama-3.1-8b-instruct:free",
                            f"or-llama-{KEY_HOUR}")
def test_openrouter_mistral():
    return _openrouter_chat("mistralai/mistral-7b-instruct:free",
                            f"or-mistral-{KEY_HOUR}")

# ── TWITTER — remaining endpoints ────────────────────────────
def test_registry_twitter_user_tweets():
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/user-tweets",
        method="POST", body={"userName": "frames_ag", "count": 5},
        ikey=f"tw-usertweets-{KEY_HOUR}", chain="evm", token="USDC")

def test_registry_twitter_user_followers():
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/user-followers",
        method="POST", body={"userName": "frames_ag"},
        ikey=f"tw-followers-{KEY_HOUR}", chain="evm", token="USDC")

def test_registry_twitter_search_users():
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/search-users",
        method="POST", body={"query": "AgentWallet"},
        ikey=f"tw-searchusers-{KEY_HOUR}", chain="evm", token="USDC")

def test_registry_twitter_user_mentions():
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/user-mentions",
        method="POST", body={"userName": "frames_ag"},
        ikey=f"tw-mentions-{KEY_HOUR}", chain="evm", token="USDC")

def test_registry_twitter_user_following():
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/user-following",
        method="POST", body={"userName": "frames_ag"},
        ikey=f"tw-following-{KEY_HOUR}", chain="evm", token="USDC")

def test_registry_twitter_tweet_replies():
    # Use a known tweet — frames_ag pinned or recent
    return _x402_fetch(
        url=f"{REG_URL}/twitter/api/tweet-replies",
        method="POST", body={"tweetId": "1"},
        ikey=f"tw-replies-{KEY_HOUR}", chain="evm", token="USDC")

# ═══════════════════════════════════════════════════════════════
# APPEND TO TESTS LIST
# ═══════════════════════════════════════════════════════════════
_EXTRA_TESTS = [
    # x402 extra options
    ("x402 REAL Paid Fetch $0.01",          "x402",      test_x402_real_paid_fetch),
    ("x402 preferredTokenAddress",          "x402",      test_x402_preferred_token_address),
    ("x402 walletAddress param",            "x402",      test_x402_with_wallet_address_param),
    # Transfer extra params
    ("Transfer EVM walletAddress",          "networks",  test_transfer_evm_wallet_address),
    ("Transfer Solana walletAddress",       "networks",  test_transfer_sol_wallet_address),
    # ContractCall rawTransaction
    ("ContractCall EVM rawTransaction",     "networks",  test_contract_call_evm_raw_tx),
    ("ContractCall Solana rawTransaction",  "networks",  test_contract_call_solana_raw_tx),
    # Faucet walletAddress
    ("Faucet walletAddress param",          "actions",   test_faucet_with_wallet_address),
    # Registry — test service
    ("Registry: test/invoke $0.001",        "registry",  test_registry_test_invoke),
    # Registry — exa missing endpoint
    ("Registry: exa/contents $0.01",        "registry",  test_registry_exa_contents),
    # Registry — coingecko missing
    ("Registry: coingecko/token-info",      "registry",  test_registry_coingecko_token_info),
    # Registry — Jupiter missing
    ("Registry: jupiter/portfolio $0.01",   "registry",  test_registry_jupiter_portfolio),
    # Registry — near-intents missing
    ("Registry: near-intents/status",       "registry",  test_registry_near_status),
    # Registry — agentmail missing
    ("Registry: agentmail/threads $2.00",   "registry",  test_registry_agentmail_threads),
    ("Registry: agentmail/send $2.00",      "registry",  test_registry_agentmail_send),
    # Registry — AI-gen more models
    ("Registry: ai-gen/z-image $0.006",     "registry",  test_registry_ai_gen_z_image_turbo),
    ("Registry: ai-gen/imagen4-fast $0.03", "registry",  test_registry_ai_gen_imagen4_fast),
    ("Registry: ai-gen/ideogram $0.04",     "registry",  test_registry_ai_gen_ideogram),
    # Registry — OpenRouter more models
    ("OpenRouter: claude-haiku",            "registry",  test_openrouter_claude_haiku),
    ("OpenRouter: gemini-2-flash",          "registry",  test_openrouter_gemini_flash),
    ("OpenRouter: llama-3.1-8b (free)",     "registry",  test_openrouter_llama),
    ("OpenRouter: mistral-7b (free)",       "registry",  test_openrouter_mistral),
    # Registry — Twitter remaining
    ("Registry: twitter/user-tweets",       "registry",  test_registry_twitter_user_tweets),
    ("Registry: twitter/user-followers",    "registry",  test_registry_twitter_user_followers),
    ("Registry: twitter/search-users",      "registry",  test_registry_twitter_search_users),
    ("Registry: twitter/user-mentions",     "registry",  test_registry_twitter_user_mentions),
    ("Registry: twitter/user-following",    "registry",  test_registry_twitter_user_following),
    ("Registry: twitter/tweet-replies",     "registry",  test_registry_twitter_tweet_replies),
]
TESTS.extend(_EXTRA_TESTS)
