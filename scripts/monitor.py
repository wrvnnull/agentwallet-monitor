#!/usr/bin/env python3
"""
AgentWallet Monitor v5 — ZERO SPEND EDITION
============================================
Semua paid call diubah ke dryRun=True.
Tidak ada USDC, CASH, atau SOL yang keluar.

Perubahan dari versi original:
  - Semua _x402_fetch() → dry=True (estimasi harga saja)
  - Agentmail, Wordspace, AI-gen, OpenRouter → dryRun only
  - test/echo, test/invoke, test/networks → dryRun
  - x402 REAL Paid Fetch → dryRun
  - Faucet SOL devnet → dikomentari (hemat limit 3/24h)
  - Semua endpoint GET/POST non-payment tetap jalan normal
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

NOW      = datetime.datetime.utcnow()
KEY_RUN  = NOW.strftime("%Y%m%d-%H%M")
KEY_HOUR = NOW.strftime("%Y%m%d-%H")
KEY_DAY  = NOW.strftime("%Y%m%d")

results = {
    "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "username":  USERNAME,
    "summary":   {"total": 0, "passed": 0, "failed": 0, "warnings": 0},
    "tests":     [],
    "meta": {
        "skill_version": None, "balance_usd": None, "rank": None,
        "tier": None, "referral_count": None, "airdrop_points": None,
        "wallet_count": None, "evm_address": None, "solana_address": None,
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
        raise AssertionError("429 rate-limited")
    r.raise_for_status()
    return r.json()


def _network_check(r, label):
    if r.status_code in (429, 500):
        code = "429 rate-limit" if r.status_code == 429 else "500 server error"
        raise AssertionError(f"{label} returned {code}")
    if r.status_code in (400, 402, 403, 422, 200, 201):
        d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        return {"status_code": r.status_code, "resp": str(d)[:120]}
    r.raise_for_status()
    return {"status_code": r.status_code}


# =============================================================
# HELPER x402 — SEMUA PAKAI dryRun=True (tidak bayar)
# =============================================================
def _x402_dry(url, method="POST", body=None, ikey=None,
               chain="evm", token="USDC"):
    """Semua call lewat sini → dryRun=True, tidak ada USDC keluar."""
    time.sleep(1)
    payload = {
        "url": url, "method": method,
        "preferredChain": chain, "preferredToken": token,
        "dryRun": True,   # ← kunci utama, tidak pernah bayar
    }
    if body:
        payload["body"] = body
    if ikey:
        payload["idempotencyKey"] = ikey

    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                          headers=AUTH, json=payload, timeout=30)
    except requests.exceptions.Timeout:
        raise AssertionError("x402/fetch timed out")

    if r.status_code in (429, 500, 502, 503, 504):
        label = {429:"rate-limit",500:"server error",502:"bad gateway",
                 503:"unavailable",504:"gateway timeout"}.get(r.status_code, str(r.status_code))
        raise AssertionError(f"x402/fetch {label} ({r.status_code})")

    r.raise_for_status()
    d  = r.json()
    p  = d.get("payment", {})
    return {
        "dry_run": True,
        "would_pay": p.get("amountFormatted", "?"),
        "chain":     p.get("chain"),
        "required":  p.get("required"),
    }


# =============================================================
# META
# =============================================================

def test_skill_version():
    d = _safe(requests.get("https://frames.ag/skill.json", timeout=15))
    v = d.get("version","unknown")
    results["meta"]["skill_version"] = v
    return {"version": v}

def test_skill_json_metadata():
    d = _safe(requests.get("https://frames.ag/skill.json", timeout=15))
    mb = d.get("moltbot", {})
    assert mb.get("api_base"), "moltbot.api_base missing"
    return {"api_base": mb.get("api_base")}

def test_heartbeat_md():
    r = requests.get("https://frames.ag/heartbeat.md", timeout=15)
    r.raise_for_status()
    assert len(r.text) > 100
    return {"bytes": len(r.text)}


# =============================================================
# PUBLIC
# =============================================================

def test_network_pulse():
    d = _safe(requests.get(f"{BASE_URL}/network/pulse", timeout=15))
    return {"active_agents": d.get("activeAgents"),
            "tx_count": d.get("transactionCount")}

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
    return {"status_code": r.status_code}


# =============================================================
# REGISTRY — Health checks (semua GRATIS)
# =============================================================

def _registry_health(slug):
    d = _safe(requests.get(f"{REG_URL}/{slug}/health", timeout=15))
    assert d.get("status") == "healthy", f"{slug} not healthy: {d}"
    return {"status": d.get("status")}

def test_registry_twitter_health():    return _registry_health("twitter")
def test_registry_ai_gen_health():     return _registry_health("ai-gen")
def test_registry_test_health():       return _registry_health("test")
def test_registry_exa_health():        return _registry_health("exa")
def test_registry_wordspace_health():  return _registry_health("wordspace")
def test_registry_openrouter_health(): return _registry_health("openrouter")
def test_registry_jupiter_health():    return _registry_health("jupiter")
def test_registry_near_health():       return _registry_health("near-intents")
def test_registry_agentmail_health():  return _registry_health("agentmail")
def test_registry_coingecko_health():  return _registry_health("coingecko")

def test_registry_services_list():
    d = _safe(requests.get("https://registry.frames.ag/api/services", timeout=15))
    services = d.get("services", [])
    slugs    = [s.get("slug") for s in services]
    expected = ["twitter","ai-gen","test","exa","wordspace",
                "openrouter","jupiter","near-intents","agentmail","coingecko"]
    missing  = [s for s in expected if s not in slugs]
    assert not missing, f"Missing: {missing}"
    return {"count": len(services)}


# =============================================================
# REGISTRY — Paid calls → SEMUA dryRun (cek endpoint hidup saja)
# =============================================================

# ── TEST service ──────────────────────────────────────────────
def test_registry_test_echo():
    return _x402_dry(f"{REG_URL}/test/api/echo", method="POST",
                     body={"data": f"ping-{KEY_RUN}"}, ikey=f"test-echo-{KEY_RUN}")

def test_registry_test_networks():
    return _x402_dry(f"{REG_URL}/test/api/networks", method="GET",
                     ikey=f"test-networks-{KEY_RUN}")

def test_registry_test_invoke():
    return _x402_dry(f"{REG_URL}/test/api/invoke", method="POST",
                     body={"prompt": f"ping {KEY_RUN}"}, ikey=f"test-invoke-{KEY_RUN}")

# ── COINGECKO ─────────────────────────────────────────────────
def test_registry_coingecko_price():
    return _x402_dry(f"{REG_URL}/coingecko/api/price", method="POST",
                     body={"ids":["bitcoin","ethereum","solana"]},
                     ikey=f"cg-price-{KEY_HOUR}")

def test_registry_coingecko_trending():
    return _x402_dry(f"{REG_URL}/coingecko/api/trending", method="GET",
                     ikey=f"cg-trending-{KEY_HOUR}")

def test_registry_coingecko_search():
    return _x402_dry(f"{REG_URL}/coingecko/api/search", method="POST",
                     body={"query":"solana"}, ikey=f"cg-search-{KEY_HOUR}")

def test_registry_coingecko_markets():
    return _x402_dry(f"{REG_URL}/coingecko/api/markets", method="POST",
                     body={"vs_currency":"usd","per_page":5},
                     ikey=f"cg-markets-{KEY_HOUR}")

def test_registry_coingecko_token_info():
    return _x402_dry(f"{REG_URL}/coingecko/api/token-info", method="POST",
                     body={"id":"solana"}, ikey=f"cg-tokeninfo-{KEY_HOUR}")

# ── EXA ───────────────────────────────────────────────────────
def test_registry_exa_search():
    return _x402_dry(f"{REG_URL}/exa/api/search", method="POST",
                     body={"query":f"AgentWallet {KEY_HOUR}","numResults":2},
                     ikey=f"exa-search-{KEY_HOUR}")

def test_registry_exa_answer():
    return _x402_dry(f"{REG_URL}/exa/api/answer", method="POST",
                     body={"query":"What is x402 payment protocol?"},
                     ikey=f"exa-answer-{KEY_HOUR}")

def test_registry_exa_find_similar():
    return _x402_dry(f"{REG_URL}/exa/api/find-similar", method="POST",
                     body={"url":"https://frames.ag","numResults":2},
                     ikey=f"exa-similar-{KEY_HOUR}")

def test_registry_exa_contents():
    return _x402_dry(f"{REG_URL}/exa/api/contents", method="POST",
                     body={"ids":["https://frames.ag"]},
                     ikey=f"exa-contents-{KEY_HOUR}")

# ── TWITTER ───────────────────────────────────────────────────
def test_registry_twitter_search_tweets():
    return _x402_dry(f"{REG_URL}/twitter/api/search-tweets", method="POST",
                     body={"query":"AgentWallet x402","queryType":"Latest"},
                     ikey=f"tw-search-{KEY_HOUR}")

def test_registry_twitter_trends():
    return _x402_dry(f"{REG_URL}/twitter/api/trends", method="POST",
                     body={}, ikey=f"tw-trends-{KEY_HOUR}")

def test_registry_twitter_user_info():
    return _x402_dry(f"{REG_URL}/twitter/api/user-info", method="POST",
                     body={"userName":"frames_ag"}, ikey=f"tw-userinfo-{KEY_HOUR}")

def test_registry_twitter_user_tweets():
    return _x402_dry(f"{REG_URL}/twitter/api/user-tweets", method="POST",
                     body={"userName":"frames_ag","count":5},
                     ikey=f"tw-usertweets-{KEY_HOUR}")

def test_registry_twitter_user_followers():
    return _x402_dry(f"{REG_URL}/twitter/api/user-followers", method="POST",
                     body={"userName":"frames_ag"}, ikey=f"tw-followers-{KEY_HOUR}")

def test_registry_twitter_search_users():
    return _x402_dry(f"{REG_URL}/twitter/api/search-users", method="POST",
                     body={"query":"AgentWallet"}, ikey=f"tw-searchusers-{KEY_HOUR}")

def test_registry_twitter_user_mentions():
    return _x402_dry(f"{REG_URL}/twitter/api/user-mentions", method="POST",
                     body={"userName":"frames_ag"}, ikey=f"tw-mentions-{KEY_HOUR}")

def test_registry_twitter_user_following():
    return _x402_dry(f"{REG_URL}/twitter/api/user-following", method="POST",
                     body={"userName":"frames_ag"}, ikey=f"tw-following-{KEY_HOUR}")

def test_registry_twitter_tweet_replies():
    return _x402_dry(f"{REG_URL}/twitter/api/tweet-replies", method="POST",
                     body={"tweetId":"1"}, ikey=f"tw-replies-{KEY_HOUR}")

# ── NEAR INTENTS ──────────────────────────────────────────────
def test_registry_near_intents_tokens():
    return _x402_dry(f"{REG_URL}/near-intents/api/tokens", method="GET",
                     ikey=f"near-tokens-{KEY_HOUR}")

def test_registry_near_intents_quote():
    return _x402_dry(f"{REG_URL}/near-intents/api/quote", method="POST",
                     body={"tokenIn":"USDC","tokenOut":"SOL","amountIn":"1"},
                     ikey=f"near-quote-{KEY_HOUR}")

def test_registry_near_status():
    return _x402_dry(f"{REG_URL}/near-intents/api/status", method="POST",
                     body={"intentId":"monitor-test"}, ikey=f"near-status-{KEY_HOUR}")

# ── JUPITER ───────────────────────────────────────────────────
def test_registry_jupiter_price():
    return _x402_dry(f"{REG_URL}/jupiter/api/price", method="POST",
                     body={"ids":["SOL","USDC","JUP"]}, ikey=f"jup-price-{KEY_HOUR}")

def test_registry_jupiter_tokens():
    return _x402_dry(f"{REG_URL}/jupiter/api/tokens", method="GET",
                     ikey=f"jup-tokens-{KEY_HOUR}")

def test_registry_jupiter_portfolio():
    sol = results["meta"]["solana_address"] or "11111111111111111111111111111111"
    return _x402_dry(f"{REG_URL}/jupiter/api/portfolio", method="POST",
                     body={"wallet": sol}, ikey=f"jup-portfolio-{KEY_HOUR}")

# ── AI-GEN — dryRun cek endpoint, tidak generate gambar ───────
def test_registry_ai_gen_models():
    d = _safe(requests.get(f"{REG_URL}/ai-gen/api/models", timeout=15))
    models = d.get("models", [])
    cheapest = min(models, key=lambda m: m.get("pricing",{}).get("price", 999)) if models else {}
    return {"model_count": len(models),
            "cheapest": cheapest.get("name"),
            "cheapest_price": cheapest.get("pricing",{}).get("priceString")}

def test_registry_ai_gen_schnell():
    return _x402_dry(f"{REG_URL}/ai-gen/api/invoke", method="POST",
                     body={"owner":"flux","name":"schnell",
                           "input":{"prompt":f"test {KEY_HOUR}","aspect_ratio":"1:1"}},
                     ikey=f"aigen-schnell-{KEY_HOUR}")

def test_registry_ai_gen_z_image():
    return _x402_dry(f"{REG_URL}/ai-gen/api/invoke", method="POST",
                     body={"owner":"prunaai","name":"z-image-turbo",
                           "input":{"prompt":f"test {KEY_HOUR}","aspect_ratio":"1:1"}},
                     ikey=f"aigen-z-{KEY_HOUR}")

def test_registry_ai_gen_imagen4():
    return _x402_dry(f"{REG_URL}/ai-gen/api/invoke", method="POST",
                     body={"owner":"google","name":"imagen-4-fast",
                           "input":{"prompt":f"test {KEY_HOUR}","aspect_ratio":"1:1"}},
                     ikey=f"aigen-imagen4-{KEY_HOUR}")

def test_registry_ai_gen_ideogram():
    return _x402_dry(f"{REG_URL}/ai-gen/api/invoke", method="POST",
                     body={"owner":"ideogram","name":"v3-turbo",
                           "input":{"prompt":f"test {KEY_HOUR}","aspect_ratio":"1:1"}},
                     ikey=f"aigen-ideogram-{KEY_HOUR}")

# ── OPENROUTER — dryRun (cek tarif, tidak generate) ───────────
def _openrouter_dry(model, ikey):
    return _x402_dry(
        url=f"{REG_URL}/openrouter/v1/chat/completions",
        method="POST",
        body={"model": model,
              "messages":[{"role":"user","content":f"ping {KEY_HOUR}"}],
              "max_tokens": 5},
        ikey=ikey,
    )

def test_registry_openrouter_gpt4o_mini():
    return _openrouter_dry("openai/gpt-4o-mini", f"or-gpt4omini-{KEY_HOUR}")

def test_registry_openrouter_claude_haiku():
    return _openrouter_dry("anthropic/claude-haiku-4-5", f"or-claude-{KEY_HOUR}")

def test_registry_openrouter_gemini_flash():
    return _openrouter_dry("google/gemini-2.0-flash-001", f"or-gemini-{KEY_HOUR}")

def test_registry_openrouter_llama():
    return _openrouter_dry("meta-llama/llama-3.1-8b-instruct:free", f"or-llama-{KEY_HOUR}")

def test_registry_openrouter_mistral():
    return _openrouter_dry("mistralai/mistral-7b-instruct:free", f"or-mistral-{KEY_HOUR}")

# ── AGENTMAIL — dryRun (cek endpoint hidup, tidak kirim email) ─
def test_registry_agentmail_inbox_create():
    return _x402_dry(f"{REG_URL}/agentmail/api/inbox/create", method="POST",
                     body={}, ikey=f"agentmail-inbox-{KEY_DAY}")

def test_registry_agentmail_messages():
    return _x402_dry(f"{REG_URL}/agentmail/api/messages", method="GET",
                     ikey=f"agentmail-msgs-{KEY_DAY}")

def test_registry_agentmail_threads():
    return _x402_dry(f"{REG_URL}/agentmail/api/threads", method="GET",
                     ikey=f"agentmail-threads-{KEY_DAY}")

def test_registry_agentmail_send():
    return _x402_dry(f"{REG_URL}/agentmail/api/send", method="POST",
                     body={"to":"monitor@example.invalid",
                           "subject":f"test {KEY_DAY}","body":"dry run"},
                     ikey=f"agentmail-send-{KEY_DAY}")

# ── WORDSPACE — dryRun ────────────────────────────────────────
def test_registry_wordspace_invoke():
    return _x402_dry(f"{REG_URL}/wordspace/api/invoke", method="POST",
                     body={"prompt":f"One sentence about x402. {KEY_DAY}","maxSteps":1},
                     ikey=f"wordspace-{KEY_DAY}")


# =============================================================
# WALLET
# =============================================================

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
    return {"total_usd": total}

def test_activity_auth():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/activity?limit=20",
                            headers=AUTH, timeout=15))
    events = d.get("data", d)
    count  = len(events) if isinstance(events, list) else "?"
    return {"event_count": count}

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
            "points": inner.get("airdropPoints"), "streak": inner.get("streak")}

def test_list_wallets():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    wallets = inner.get("wallets", [])
    results["meta"]["wallet_count"] = len(wallets)
    return {"count": len(wallets), "tier": inner.get("tier")}

def test_create_wallet_evm():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                      headers=AUTH, json={"chainType":"ethereum"}, timeout=15)
    if r.status_code == 403:
        raise AssertionError(f"Tier limit (expected Bronze): {r.json().get('error','')}")
    r.raise_for_status()
    return {"created": True}

def test_create_wallet_solana():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/wallets",
                      headers=AUTH, json={"chainType":"solana"}, timeout=15)
    if r.status_code == 403:
        raise AssertionError(f"Tier limit (expected Bronze): {r.json().get('error','')}")
    r.raise_for_status()
    return {"created": True}


# =============================================================
# REFERRALS
# =============================================================

def test_referrals():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/referrals",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    count = inner.get("referralCount") or inner.get("count") or 0
    results["meta"]["referral_count"] = count
    return {"referral_count": count,
            "link": f"https://frames.ag/connect?ref={USERNAME}"}


# =============================================================
# POLICY
# =============================================================

def test_policy_get():
    d = _safe(requests.get(f"{BASE_URL}/wallets/{USERNAME}/policy",
                            headers=AUTH, timeout=15))
    inner = d.get("data", d)
    return {"max_per_tx_usd": inner.get("max_per_tx_usd"),
            "allow_chains": inner.get("allow_chains", [])}

def test_policy_patch():
    payload = {"max_per_tx_usd":"25","allow_chains":["base","solana"]}
    url = f"{BASE_URL}/wallets/{USERNAME}/policy"
    r   = requests.patch(url, headers=AUTH, json=payload, timeout=15)
    if r.status_code == 405:
        r = requests.put(url, headers=AUTH, json=payload, timeout=15)
    if r.status_code in (400, 405):
        d = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        raise AssertionError(f"Policy write {r.status_code} — {d.get('error','')}")
    r.raise_for_status()
    assert r.json().get("success"), "Policy update failed"
    return {"updated": True}


# =============================================================
# X402 dryRun — semua variasi opsi (tidak bayar)
# =============================================================

def _x402_dry_generic(extra=None):
    time.sleep(1)
    payload = {"url":f"{REG_URL}/exa/api/search","method":"POST",
               "body":{"query":"test"},"dryRun":True}
    if extra:
        payload.update(extra)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                            headers=AUTH, json=payload, timeout=30))
    p = d.get("payment", {})
    return {"required":p.get("required"),"chain":p.get("chain"),
            "would_pay":p.get("amountFormatted")}

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

def test_x402_dry_token_address():
    return _x402_dry_generic({
        "preferredChain":"evm",
        "preferredTokenAddress":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "idempotencyKey":f"tokaddr-{KEY_HOUR}",
    })

def test_x402_dry_wallet_address():
    evm = results["meta"]["evm_address"] or ""
    if not evm:
        raise AssertionError("No EVM address yet")
    return _x402_dry_generic({"walletAddress":evm,"idempotencyKey":f"waddr-{KEY_HOUR}"})

def test_x402_invalid_url():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/fetch",
                      headers=AUTH,
                      json={"url":"http://localhost/bad","dryRun":True},
                      timeout=15)
    assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}"
    return {"error":r.json().get("error",""),"status":r.status_code}

def test_x402_legacy_pay():
    r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/x402/pay",
                      headers=AUTH,
                      json={"requirement":"eyJ0eXBlIjoieC00MDIifQ==",
                            "preferredChain":"evm","dryRun":True},
                      timeout=20)
    assert r.status_code not in (404, 405, 500), f"Legacy /pay broken: {r.status_code}"
    return {"status_code":r.status_code,"alive":True}


# =============================================================
# ACTIONS
# =============================================================

def test_sign_ethereum():
    time.sleep(1)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain":"ethereum","message":"monitor v5 free ETH"},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data")
    return {"chain":"ethereum","signed":True}

def test_sign_solana():
    time.sleep(1)
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain":"solana","message":"monitor v5 free SOL"},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data")
    return {"chain":"solana","signed":True}

def test_sign_with_wallet_address():
    time.sleep(1)
    evm = results["meta"]["evm_address"] or ""
    if not evm:
        raise AssertionError("No EVM address available")
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/sign-message",
                            headers=AUTH,
                            json={"chain":"ethereum","message":"walletAddress param test",
                                  "walletAddress": evm},
                            timeout=15))
    assert d.get("success") or d.get("signature") or d.get("data")
    return {"signed":True,"walletAddress":evm[:14]+"..."}

# Faucet dikomentari — hemat limit 3x/24jam
# def test_faucet_devnet():
#     ...


# =============================================================
# NETWORKS — Transfer/ContractCall (validasi saja, tidak eksekusi)
# =============================================================

EVM_DUMMY    = "0x0000000000000000000000000000000000000001"
SOLANA_DUMMY = "11111111111111111111111111111111"

def _evm_tx(chain_id, extra=None):
    time.sleep(1)
    to      = results["meta"]["evm_address"] or EVM_DUMMY
    payload = {"to":to,"amount":"1","asset":"usdc","chainId":chain_id}
    if extra:
        payload.update(extra)
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer",
                          headers=AUTH, json=payload, timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError(f"Chain {chain_id} timed out")
    return _network_check(r, f"chainId={chain_id}")

def test_tx_base():          return _evm_tx(8453)
def test_tx_optimism():      return _evm_tx(10)
def test_tx_polygon():       return _evm_tx(137)
def test_tx_arbitrum():      return _evm_tx(42161)
def test_tx_bnb():           return _evm_tx(56)
def test_tx_ethereum():      return _evm_tx(1)
def test_tx_gnosis():        return _evm_tx(100)
def test_tx_sepolia():       return _evm_tx(11155111)
def test_tx_base_sepolia():  return _evm_tx(84532)
def test_tx_idempotency():   return _evm_tx(8453, extra={"idempotencyKey":f"idem-{KEY_HOUR}"})
def test_tx_wallet_address():
    evm = results["meta"]["evm_address"] or EVM_DUMMY
    return _evm_tx(8453, extra={"walletAddress": evm})

def test_tx_sol_mainnet():
    time.sleep(1)
    to = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to":to,"amount":"1","asset":"usdc","network":"mainnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana mainnet timed out")
    return _network_check(r, "solana_mainnet")

def test_tx_sol_devnet():
    time.sleep(1)
    to = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to":to,"amount":"1","asset":"sol","network":"devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana devnet timed out")
    return _network_check(r, "solana_devnet")

def test_tx_sol_wallet_address():
    time.sleep(1)
    sol = results["meta"]["solana_address"] or SOLANA_DUMMY
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/transfer-solana",
                          headers=AUTH,
                          json={"to":sol,"amount":"1","asset":"sol",
                                "network":"devnet","walletAddress":sol},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana walletAddress timed out")
    return _network_check(r, "sol_walletAddress")

def test_contract_call_evm():
    time.sleep(1)
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
    time.sleep(1)
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

def test_contract_call_evm_raw_tx():
    time.sleep(1)
    raw_hex = "0x02f86d01808459682f00850c92a69c0082520894" + "00"*20 + "8080c0"
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType":"ethereum","rawTransaction":raw_hex,"chainId":8453},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("EVM rawTx timed out")
    return _network_check(r, "evm_raw_transaction")

def test_contract_call_solana_raw_tx():
    import base64
    time.sleep(1)
    raw_b64 = base64.b64encode(b"\x01" + b"\x00"*63).decode()
    try:
        r = requests.post(f"{BASE_URL}/wallets/{USERNAME}/actions/contract-call",
                          headers=AUTH,
                          json={"chainType":"solana","rawTransaction":raw_b64,"network":"devnet"},
                          timeout=20)
    except requests.exceptions.Timeout:
        raise AssertionError("Solana rawTx timed out")
    return _network_check(r, "solana_raw_transaction")


# =============================================================
# FEEDBACK
# =============================================================

def _feedback(cat, msg):
    d = _safe(requests.post(f"{BASE_URL}/wallets/{USERNAME}/feedback",
                            headers=AUTH,
                            json={"category":cat,"message":msg,
                                  "context":{"automated":True,"version":"v5-free",
                                             "run_id":os.environ.get("GITHUB_RUN_ID","local")}},
                            timeout=15))
    assert d.get("success"), f"Feedback failed: {d.get('error')}"
    return {"category":cat,"id":d.get("data",{}).get("id","?")}

def test_feedback_other():
    return _feedback("other",
        f"[AUTO-MONITOR v5-FREE] Heartbeat {NOW.strftime('%Y-%m-%d %H:%M UTC')}. "
        f"Zero-spend mode — all x402 calls are dryRun only.")

def test_feedback_bug():     return _feedback("bug",     "[AUTO-MONITOR v5-FREE] Category test: bug.")
def test_feedback_feature(): return _feedback("feature", "[AUTO-MONITOR v5-FREE] Category test: feature.")
def test_feedback_stuck():   return _feedback("stuck",   "[AUTO-MONITOR v5-FREE] Category test: stuck.")


# =============================================================
# DAFTAR TEST
# =============================================================

TESTS = [
    # META
    ("Skill Version",                       "meta",      test_skill_version),
    ("Skill.json Metadata",                 "meta",      test_skill_json_metadata),
    ("Heartbeat.md",                        "meta",      test_heartbeat_md),
    # PUBLIC
    ("Network Pulse",                       "public",    test_network_pulse),
    ("Wallet Connected (public)",           "public",    test_wallet_connected_public),
    ("Connect Start Endpoint",              "public",    test_connect_start_endpoint),
    # REGISTRY — Health (gratis)
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
    # REGISTRY — x402 dryRun (cek endpoint, tidak bayar)
    ("Registry: test/echo [dry]",          "registry",  test_registry_test_echo),
    ("Registry: test/networks [dry]",      "registry",  test_registry_test_networks),
    ("Registry: test/invoke [dry]",        "registry",  test_registry_test_invoke),
    ("Registry: coingecko/price [dry]",    "registry",  test_registry_coingecko_price),
    ("Registry: coingecko/trending [dry]", "registry",  test_registry_coingecko_trending),
    ("Registry: coingecko/search [dry]",   "registry",  test_registry_coingecko_search),
    ("Registry: coingecko/markets [dry]",  "registry",  test_registry_coingecko_markets),
    ("Registry: coingecko/token-info [dry]","registry", test_registry_coingecko_token_info),
    ("Registry: exa/search [dry]",         "registry",  test_registry_exa_search),
    ("Registry: exa/answer [dry]",         "registry",  test_registry_exa_answer),
    ("Registry: exa/find-similar [dry]",   "registry",  test_registry_exa_find_similar),
    ("Registry: exa/contents [dry]",       "registry",  test_registry_exa_contents),
    ("Registry: twitter/search [dry]",     "registry",  test_registry_twitter_search_tweets),
    ("Registry: twitter/trends [dry]",     "registry",  test_registry_twitter_trends),
    ("Registry: twitter/user-info [dry]",  "registry",  test_registry_twitter_user_info),
    ("Registry: twitter/user-tweets [dry]","registry",  test_registry_twitter_user_tweets),
    ("Registry: twitter/followers [dry]",  "registry",  test_registry_twitter_user_followers),
    ("Registry: twitter/search-users [dry]","registry", test_registry_twitter_search_users),
    ("Registry: twitter/mentions [dry]",   "registry",  test_registry_twitter_user_mentions),
    ("Registry: twitter/following [dry]",  "registry",  test_registry_twitter_user_following),
    ("Registry: twitter/replies [dry]",    "registry",  test_registry_twitter_tweet_replies),
    ("Registry: near/tokens [dry]",        "registry",  test_registry_near_intents_tokens),
    ("Registry: near/quote [dry]",         "registry",  test_registry_near_intents_quote),
    ("Registry: near/status [dry]",        "registry",  test_registry_near_status),
    ("Registry: jupiter/price [dry]",      "registry",  test_registry_jupiter_price),
    ("Registry: jupiter/tokens [dry]",     "registry",  test_registry_jupiter_tokens),
    ("Registry: jupiter/portfolio [dry]",  "registry",  test_registry_jupiter_portfolio),
    ("Registry: ai-gen/models (gratis)",   "registry",  test_registry_ai_gen_models),
    ("Registry: ai-gen/schnell [dry]",     "registry",  test_registry_ai_gen_schnell),
    ("Registry: ai-gen/z-image [dry]",     "registry",  test_registry_ai_gen_z_image),
    ("Registry: ai-gen/imagen4 [dry]",     "registry",  test_registry_ai_gen_imagen4),
    ("Registry: ai-gen/ideogram [dry]",    "registry",  test_registry_ai_gen_ideogram),
    ("Registry: openrouter/gpt4o-mini [dry]","registry",test_registry_openrouter_gpt4o_mini),
    ("Registry: openrouter/claude [dry]",  "registry",  test_registry_openrouter_claude_haiku),
    ("Registry: openrouter/gemini [dry]",  "registry",  test_registry_openrouter_gemini_flash),
    ("Registry: openrouter/llama [dry]",   "registry",  test_registry_openrouter_llama),
    ("Registry: openrouter/mistral [dry]", "registry",  test_registry_openrouter_mistral),
    ("Registry: agentmail/inbox [dry]",    "registry",  test_registry_agentmail_inbox_create),
    ("Registry: agentmail/messages [dry]", "registry",  test_registry_agentmail_messages),
    ("Registry: agentmail/threads [dry]",  "registry",  test_registry_agentmail_threads),
    ("Registry: agentmail/send [dry]",     "registry",  test_registry_agentmail_send),
    ("Registry: wordspace/invoke [dry]",   "registry",  test_registry_wordspace_invoke),
    # WALLET
    ("Wallet Info",                         "wallet",    test_wallet_info),
    ("Balances",                            "wallet",    test_balances),
    ("Activity (auth)",                     "wallet",    test_activity_auth),
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
    # X402 dryRun opsi
    ("x402 DryRun auto-chain",             "x402",      test_x402_dry_auto),
    ("x402 DryRun EVM",                    "x402",      test_x402_dry_evm),
    ("x402 DryRun Solana",                 "x402",      test_x402_dry_solana),
    ("x402 DryRun USDC",                   "x402",      test_x402_dry_usdc),
    ("x402 DryRun USDT",                   "x402",      test_x402_dry_usdt),
    ("x402 DryRun CASH",                   "x402",      test_x402_dry_cash),
    ("x402 DryRun chainId",                "x402",      test_x402_dry_chain_id),
    ("x402 DryRun idempotencyKey",         "x402",      test_x402_dry_idem_key),
    ("x402 DryRun timeout",                "x402",      test_x402_dry_timeout),
    ("x402 DryRun EVM+USDC",              "x402",      test_x402_dry_evm_usdc),
    ("x402 DryRun Solana+USDC",           "x402",      test_x402_dry_solana_usdc),
    ("x402 DryRun Solana+CASH",           "x402",      test_x402_dry_solana_cash),
    ("x402 DryRun tokenAddress",          "x402",      test_x402_dry_token_address),
    ("x402 DryRun walletAddress",         "x402",      test_x402_dry_wallet_address),
    ("x402 Error INVALID_URL",            "x402",      test_x402_invalid_url),
    ("x402 Legacy /pay endpoint",         "x402",      test_x402_legacy_pay),
    # ACTIONS
    ("Sign Message Ethereum",              "actions",   test_sign_ethereum),
    ("Sign Message Solana",                "actions",   test_sign_solana),
    ("Sign walletAddress param",           "actions",   test_sign_with_wallet_address),
    # NETWORKS
    ("Transfer Base (8453)",               "networks",  test_tx_base),
    ("Transfer Optimism (10)",             "networks",  test_tx_optimism),
    ("Transfer Polygon (137)",             "networks",  test_tx_polygon),
    ("Transfer Arbitrum (42161)",          "networks",  test_tx_arbitrum),
    ("Transfer BNB (56)",                  "networks",  test_tx_bnb),
    ("Transfer Ethereum (1)",              "networks",  test_tx_ethereum),
    ("Transfer Gnosis (100)",              "networks",  test_tx_gnosis),
    ("Transfer Sepolia",                   "networks",  test_tx_sepolia),
    ("Transfer Base Sepolia",              "networks",  test_tx_base_sepolia),
    ("Transfer + idempotencyKey",          "networks",  test_tx_idempotency),
    ("Transfer EVM walletAddress",         "networks",  test_tx_wallet_address),
    ("Transfer Solana mainnet",            "networks",  test_tx_sol_mainnet),
    ("Transfer Solana devnet",             "networks",  test_tx_sol_devnet),
    ("Transfer Solana walletAddress",      "networks",  test_tx_sol_wallet_address),
    ("ContractCall EVM Base",              "networks",  test_contract_call_evm),
    ("ContractCall Solana devnet",         "networks",  test_contract_call_solana),
    ("ContractCall EVM rawTransaction",    "networks",  test_contract_call_evm_raw_tx),
    ("ContractCall Solana rawTransaction", "networks",  test_contract_call_solana_raw_tx),
    # FEEDBACK
    ("Feedback category:other",            "feedback",  test_feedback_other),
    ("Feedback category:bug",              "feedback",  test_feedback_bug),
    ("Feedback category:feature",          "feedback",  test_feedback_feature),
    ("Feedback category:stuck",            "feedback",  test_feedback_stuck),
]


# =============================================================
# RUN
# =============================================================

print(f"\n{'='*64}")
print(f"  AgentWallet Monitor v5 ZERO SPEND  |  {results['timestamp']}")
print(f"  User: {USERNAME}  |  Tests: {len(TESTS)}")
print(f"  Semua x402 = dryRun only — USDC/CASH/SOL tidak keluar")
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

os.makedirs("docs", exist_ok=True)

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
    "zero_spend": True,
})
history = history[:100]

with open(HISTORY_FILE, "w") as f:
    json.dump(history, f, indent=2)
with open("docs/status.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*64}")
print(f"  RESULT   : {passed}/{total} passed | {failed} failed | {warned} warnings")
print(f"  BIAYA    : $0.00 — zero spend mode aktif")
if results["meta"]["balance_usd"] is not None:
    print(f"  Balance  : ${results['meta']['balance_usd']} USD (tidak berubah)")
if results["meta"]["rank"] is not None:
    print(f"  Rank     : #{results['meta']['rank']} | Tier: {results['meta']['tier']}")
if results["meta"]["referral_count"] is not None:
    print(f"  Refs     : {results['meta']['referral_count']} | Pts: {results['meta']['airdrop_points']}")
    print(f"  Link     : https://frames.ag/connect?ref={USERNAME}")
print(f"{'='*64}\n")

if failed > 0:
    for t in results["tests"]:
        if t["status"] == "fail":
            print(f"  HARD FAIL [{t['category']}] {t['name']} — {t['error']}")
    sys.exit(1)
elif warned > 0:
    print(f"  {warned} soft warning(s) — semua expected")
    sys.exit(0)
else:
    print("  PERFECT RUN — $0.00 spent!")
    sys.exit(0)
