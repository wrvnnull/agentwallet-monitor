# AgentWallet Monitor 🔍

Automated full-feature monitoring for [AgentWallet](https://frames.ag), running every **5 minutes** via GitHub Actions with a live dashboard on GitHub Pages.

---

## 📊 Dashboard

Once deployed, your dashboard is live at:

```
https://<your-github-username>.github.io/<repo-name>/
```

---

## 🚀 Setup (3 steps)

### Step 1 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name             | Value                          |
|-------------------------|--------------------------------|
| `AGENTWALLET_USERNAME`  | Your AgentWallet username      |
| `AGENTWALLET_API_TOKEN` | Your API token (starts `mf_`)  |

### Step 2 — Enable GitHub Pages

Go to **Settings → Pages**:

- **Source**: `Deploy from a branch`
- **Branch**: `main` (or `master`)
- **Folder**: `/docs`

Click **Save**.

### Step 3 — Trigger the first run

Go to **Actions → AgentWallet Monitor → Run workflow** and click **Run workflow**.

After ~1 minute your dashboard will be live!

---

## 🧪 Tests Covered

| Category   | Tests |
|------------|-------|
| Meta       | Skill version check, Heartbeat.md reachable |
| Public     | Network pulse, Wallet connected status |
| Wallet     | Wallet info, Balances, Activity feed, Stats/rank, List wallets |
| Referrals  | Referral count & link |
| Policy     | GET policy, PATCH policy |
| x402       | Dry-run payment cost preview (no real payment) |
| Actions    | Sign message |
| Feedback   | Submit heartbeat feedback entry |

**15 tests total** — all features from the AgentWallet spec covered.

---

## 📁 File Structure

```
.github/
  workflows/
    monitor.yml          # Runs every 5 minutes
scripts/
  monitor.py             # Main test script
docs/
  index.html             # Dashboard (GitHub Pages)
  status.json            # Latest test results (auto-generated)
  history.json           # Last 50 run history (auto-generated)
```

---

## ⚙️ Configuration

Edit `scripts/monitor.py` to:
- Add/remove tests
- Change the feedback message
- Adjust timeouts

Edit `.github/workflows/monitor.yml` to:
- Change the cron schedule (default: every 5 min)
- Add Slack/email notifications on failure

---

## 🔒 Security

- API tokens are stored only in **GitHub Secrets** — never in code
- The `apiToken` is never printed or logged
- x402 tests use `dryRun: true` to avoid spending funds
