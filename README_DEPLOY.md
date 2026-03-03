# 🚀 Screener Pro — Deployment Guide

## Overview
This guide gets your screener live on the internet (free) in ~15 minutes.

**Stack:**
- **GitHub** — stores your code (free)
- **Render** — runs your Python backend 24/7 (free tier)
- **Dashboard** — opens in any browser, connects to your live Render URL

---

## STEP 1 — Get your free API keys

### Alpha Vantage (stock data fallback)
1. Go to https://alphavantage.co/support/#api-key
2. Fill in your name and email
3. Copy your API key — you'll need it in Step 4

---

## STEP 2 — Create a GitHub account

1. Go to **https://github.com** → click **Sign up**
2. Choose a username, email, password
3. Verify your email
4. Done — you have GitHub ✓

---

## STEP 3 — Push your code to GitHub

Open Terminal (press `Cmd + Space`, type "Terminal", hit Enter).

Run these commands one at a time:

```bash
# 1. Install Git if you don't have it
# (skip if 'git --version' already works)
xcode-select --install

# 2. Navigate to your project folder
cd /path/to/your/screener-pro
# Example: cd ~/Desktop/screener-pro

# 3. Initialize Git
git init

# 4. Add all files
git add .

# 5. First commit
git commit -m "Initial commit — Screener Pro"

# 6. Go to github.com → click the '+' top right → 'New repository'
#    Name it: screener-pro
#    Set to Public
#    Do NOT add README (you already have files)
#    Click 'Create repository'

# 7. Copy the two lines GitHub shows you under
#    "…or push an existing repository from the command line"
#    They look like this — replace YOUR_USERNAME:
git remote add origin https://github.com/YOUR_USERNAME/screener-pro.git
git branch -M main
git push -u origin main
```

Your code is now on GitHub ✓

---

## STEP 4 — Deploy to Render (free)

1. Go to **https://render.com** → click **Get Started for Free**
2. Click **Sign in with GitHub** → authorize Render
3. Click **New +** → **Web Service**
4. Find your `screener-pro` repo → click **Connect**
5. Render auto-detects your `render.yaml` — settings are pre-filled ✓
6. Scroll to **Environment Variables** → click **Add Environment Variable**:
   - Key: `ALPHA_VANTAGE_KEY`
   - Value: *(paste your key from Step 1)*
7. Click **Create Web Service**

Render will build and deploy your app (~2–3 minutes).

When it says **Live** ✓, copy your URL — it looks like:
```
https://screener-pro.onrender.com
```

---

## STEP 5 — Connect your Dashboard to the live backend

1. Open `config_editor.html` in your browser
2. Go to the **Dashboard** tab
3. There's a **Backend URL** field — paste your Render URL:
   ```
   https://screener-pro.onrender.com
   ```
4. Click **Save Config** — this downloads updated `config.py` and `settings.json`
5. Open `dashboard.html` → toggle **LIVE** → data loads from Render ✓

---

## STEP 6 — Mac Auto-Start (local backup)

If you ever want the app running locally on startup:

```bash
# 1. Edit the plist file — replace REPLACE_WITH_FULL_PATH with your actual path
#    Example: /Users/yourname/Desktop/screener-pro
nano com.screenerpro.app.plist

# 2. Copy it to LaunchAgents
cp com.screenerpro.app.plist ~/Library/LaunchAgents/

# 3. Load it (starts now + on every login)
launchctl load ~/Library/LaunchAgents/com.screenerpro.app.plist

# 4. Check it's running
launchctl list | grep screenerpro

# View logs
tail -f /tmp/screenerpro.log
```

To stop auto-start:
```bash
launchctl unload ~/Library/LaunchAgents/com.screenerpro.app.plist
```

---

## Keeping code updated

Whenever you make changes:
```bash
git add .
git commit -m "Update description"
git push
```
Render auto-deploys within ~1 minute ✓

---

## Free Tier Notes

| Limit | Details |
|---|---|
| Sleep after inactivity | App sleeps after 15 min of no requests |
| Wake time | ~30 seconds to wake when dashboard opens |
| Hours/month | 750 free hours (enough for 24/7) |
| Upgrade | $7/month for always-on (no sleep) |

**Tip:** The dashboard's first load after inactivity may take 30 sec — totally normal on free tier.

---

## Troubleshooting

**"Build failed" on Render:**
- Check that `requirements.txt` is in your repo root
- Check Render logs for specific error

**"No data showing" in dashboard:**
- Check your Alpha Vantage key is set in Render env vars
- Visit `https://your-app.onrender.com/api/status` to see scan status
- First scan takes ~60 seconds on cold start

**"App sleeping" message:**
- Wait 30 seconds and refresh — Render is waking up
- Upgrade to paid tier ($7/mo) to eliminate sleep

**Port errors locally:**
```bash
# Kill anything on port 5000
lsof -ti:5000 | xargs kill -9
python app.py
```

---

## API Endpoints

Once deployed, these URLs are live:

| Endpoint | Description |
|---|---|
| `/` | Dashboard |
| `/config` | Config editor |
| `/api/screening_results.json` | Latest top 5 stocks + cryptos |
| `/api/status` | Health check + scan info |
| `/api/portfolio` | Paper trading portfolio |
| `/api/scan_now` | Force immediate rescan |
| `/api/trade` | Place paper trade (POST) |
| `/api/export_csv` | Download trade history |

---

**You're live! 🎉**
