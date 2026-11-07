# FinPilot – Personal Finance Manager

A single-file personal finance web app: transactions, income, dues and EMIs, budgets, dashboard, health score, recurring/unusual-expense detection, CSV and report export, PIN lock.

## Run locally
Open `index.html` in Chrome or Edge. No install and no internet needed.

## Host free with GitHub Pages
Repo **Settings → Pages → Deploy from branch → `main` / root**. For this subfolder layout, configure Pages to deploy from the `finpilot` folder if available, or move these files to the repository root in a dedicated repository.

## Data and privacy
- All data is stored in the browser's localStorage on the device. Nothing is sent to any server.
- Back up regularly with **Data → Backup JSON**. Clearing browser data erases entries.
- The PIN lock deters casual access on a shared device; it does not encrypt data.

## Not included
Bank/SMS auto-sync, multi-device sync, user accounts, AI assistant (offline version shows calculated insights).

## Roadmap
Supabase login and per-user storage, server-side AI via a protected API, PWA/Capacitor mobile builds.

## Disclaimer
Provides information only, not financial advice.
