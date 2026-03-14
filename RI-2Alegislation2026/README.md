# RI Firearms Legislation Tracker

Auto-updating interactive chart of all firearms bills introduced in the Rhode Island legislative session.

## Setup Instructions

### 1. Get a LegiScan API Key
- Go to [legiscan.com/legiscan-api](https://legiscan.com/legiscan-api)
- Sign up for a free account
- Copy your API key from the dashboard

### 2. Create this GitHub repo
Create a new repository and add these files:
```
your-repo/
├── index.html          ← the chart (auto-generated, commit your current one first)
├── update_bills.py     ← the scraper script
├── .github/
│   └── workflows/
│       └── update-bills.yml   ← the automation schedule
└── README.md
```

### 3. Add your LegiScan API key as a secret
- Go to your repo → **Settings → Secrets and variables → Actions**
- Click **New repository secret**
- Name: `LEGISCAN_API_KEY`
- Value: your LegiScan API key
- Click **Add secret**

### 4. Enable GitHub Pages
- Go to **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/ (root)**
- Save — your site will be live at `https://yourusername.github.io/your-repo`

### 5. Test the workflow manually
- Go to **Actions** tab in your repo
- Click **Update RI Firearms Bills**
- Click **Run workflow → Run workflow**
- Watch it run — it should update `index.html` and commit

### Schedule
The workflow runs automatically **every Monday at 8:00 AM UTC**.
To change the schedule, edit the `cron` line in `.github/workflows/update-bills.yml`.

### How it works
1. GitHub Actions spins up a free Linux runner on schedule
2. Runs `update_bills.py` which calls the LegiScan API
3. Searches for RI bills containing firearm-related keywords
4. Classifies each bill as restriction / expansion / mixed
5. Regenerates `index.html` with updated data and a "last updated" timestamp
6. Commits and pushes the new file — GitHub Pages redeploys automatically

### Anonymity
- Git commits are configured with `user.name = "anonymous"` in the workflow
- No personal info is embedded in commits
- LegiScan only requires an email to sign up — use a throwaway
