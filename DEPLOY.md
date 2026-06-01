# Deploying MLB Analytics to the Web

Two services needed — both have free/cheap tiers:
- **Railway** — runs the Python backend + PostgreSQL database (~$5/mo)
- **Vercel** — hosts the Next.js frontend (free)

---

## Step 1 — Push to GitHub

If you haven't already:

```bash
cd /Users/henyhartman/mlb-analytics
git init
git add .
git commit -m "MLB Analytics Platform"
# Create a repo at github.com then:
git remote add origin https://github.com/YOUR_USERNAME/mlb-analytics.git
git push -u origin main
```

---

## Step 2 — Deploy Backend on Railway

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `mlb-analytics` repo
4. Railway asks which directory — type **`backend`**
5. It detects the Dockerfile and starts building

### Add PostgreSQL database
6. In your Railway project, click **"+ New"** → **"Database"** → **"Add PostgreSQL"**
7. Railway automatically adds `DATABASE_URL` to your backend service — nothing to configure

### Add environment variables
8. Click your backend service → **"Variables"** tab → add these:

| Variable | Value |
|----------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic key (sk-ant-...) |
| `SPORTRADAR_API_KEY` | Your Sportradar key (or leave blank) |
| `ALLOWED_ORIGINS` | https://YOUR-APP.vercel.app (add after Step 3) |
| `SECRET_KEY` | Any long random string e.g. `mlb-secret-key-2026-xyz` |

9. Copy the backend URL — it'll look like `https://mlb-analytics-production.up.railway.app`

---

## Step 3 — Deploy Frontend on Vercel

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub
2. Click **"Add New"** → **"Project"**
3. Import your `mlb-analytics` repo
4. Set **"Root Directory"** to `frontend`
5. Add environment variable:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | Your Railway backend URL from Step 2 |

6. Click **Deploy**
7. Vercel gives you a URL like `https://mlb-analytics.vercel.app`

---

## Step 4 — Load your data into Railway PostgreSQL

Once both are deployed, load your MLB data into the Railway database:

```bash
cd backend

# Point at Railway's database (get the URL from Railway → Variables → DATABASE_URL)
export DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@HOST:PORT/railway"

# Run the initial data load
.venv/bin/python3 -m scripts.ingest_minors
```

Or run it as a one-off Railway job:
- Railway → your backend service → **"+ New"** → **"Cron Job"**
- Command: `python -m scripts.ingest_minors`
- Schedule: `0 5 * * *` (5am daily — keeps rosters fresh)

---

## Step 5 — Update CORS

1. Go back to Railway → your backend → **Variables**
2. Set `ALLOWED_ORIGINS` = your Vercel URL (e.g. `https://mlb-analytics.vercel.app`)
3. Railway auto-redeploys

---

## Done!

Share `https://mlb-analytics.vercel.app` with anyone.
They open it in any browser — no install, no setup.

---

## Daily sync (keeps rosters + stats fresh)

Add a Railway cron job:
- Command: `python -m scripts.ingest_minors`  
- Schedule: `0 6 * * *` (6am every day)

This pulls the latest 40-man rosters and season stats every morning automatically.
