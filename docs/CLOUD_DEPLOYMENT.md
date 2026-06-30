# MedShare — Cloud Deployment Guide

Goal: move the app off your laptop so your group can log in from anywhere and you can run the live demo from a public URL.

You will set up three things:
1. A cloud PostgreSQL database (replaces your local Postgres).
2. A GitHub repository (holds the code Streamlit Cloud will run).
3. A Streamlit Community Cloud app (hosts the app, reads from the cloud database).

All three have free tiers. Total time: about 30–45 minutes the first time.

---

## Part 1 — Cloud database (Neon, free)

Neon gives you a managed Postgres with a connection string. (Supabase works too; steps are similar.)

1. Go to neon.tech and sign up (GitHub login is easiest).
2. Create a new project. Name it `medshare`. Choose the region closest to Nigeria (usually EU; any works for a demo).
3. After it creates, open **Dashboard → Connection Details**. Copy the connection string. It looks like:
   ```
   postgresql://USER:PASSWORD@ep-xxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```
4. You must adapt it slightly for this app — change the scheme to `postgresql+psycopg2://` and keep `?sslmode=require`:
   ```
   postgresql+psycopg2://USER:PASSWORD@ep-xxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```
   Save this somewhere safe — this is your cloud `DATABASE_URL`.

---

## Part 2 — Load your data into the cloud database

You do this once, from your laptop, pointing the app at the cloud DB.

1. In your project, temporarily set the cloud URL. Open `.env` and replace the DATABASE_URL line with your Neon string (the `postgresql+psycopg2://...` one). Keep a copy of your old local line so you can switch back.
2. Run the one-shot initialiser:
   ```
   python cloud_setup.py
   ```
   It applies the schema + both migrations, generates the 150-pharmacy data, seeds the logins, and runs the pipeline — all into the cloud database. Watch for "Cloud database ready."
3. (Optional) switch `.env` back to your local URL for local development. The cloud DB now has everything.

If `cloud_setup.py` reports a connection error, the most common causes are: the scheme isn't `postgresql+psycopg2://`, or `?sslmode=require` is missing. Cloud Postgres requires SSL.

---

## Part 3 — Put the code on GitHub

1. Create a free account at github.com if you don't have one.
2. Create a new **private** repository named `medshare` (private keeps your code and the validation contacts out of public view). Do NOT initialise with a README (you already have one).
3. On your laptop, in the project folder, run:
   ```
   git init
   git add .
   git commit -m "MedShare app"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/medshare.git
   git push -u origin main
   ```
   The included `.gitignore` ensures your `.env`, data files, and trained model are NOT pushed — only code. That is correct and intentional.

If `git` isn't installed, get it from git-scm.com, then reopen your terminal.

---

## Part 4 — Host the app on Streamlit Community Cloud

1. Go to share.streamlit.io and sign in with your GitHub account.
2. Click **New app** → **Deploy a public app from a repo** (or "from existing repo").
3. Fill in:
   - Repository: `YOUR_USERNAME/medshare`
   - Branch: `main`
   - Main file path: `app/streamlit_app.py`
4. Before deploying, click **Advanced settings → Secrets** and paste (using YOUR Neon string):
   ```
   DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@ep-xxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require"
   ```
5. Click **Deploy**. First build takes a few minutes (it installs requirements.txt).
6. When it finishes you get a public URL like `https://medshare.streamlit.app`. Share it with your group.

Everyone can now log in with their pharmacy ID and password `medshare` (or `admin` / `admin123`), from anywhere, and they will see only their own pharmacy's data.

---

## Daily / demo operation

- The app is always on at the public URL. The first visit after idle has a few-seconds cold start — open it a minute before the demo so it's warm.
- The data lives in Neon. To refresh recommendations (e.g. after posting demo requests), run the pipeline against the cloud DB from your laptop: set `.env` to the cloud URL and run `python -m src.pipeline`, or just rely on instant request-matching which runs inside the app.
- To reset to a clean demo state, re-run `python cloud_setup.py` with `.env` pointed at the cloud DB (this regenerates everything).

---

## Honest caveats (worth a line in your limitations / future-work)

- **Security is demo-grade.** Passwords are hashed, but the session token sits in the URL and the shared password is `medshare`. For a real pilot: per-pharmacy passwords, httpOnly cookies, and a rotated secret key.
- **Free tiers sleep.** Neon's free compute and Streamlit's free app both idle out and cold-start. Fine for a demo; a paid tier removes the delay for production.
- **No real-time push.** Updates appear on interaction/refresh, not instantly across users (websockets are future work).
- **Distances are straight-line (Haversine).** A pilot would swap in a maps-API road travel time.

---

## Quick reference — the one cloud setting that matters

Everything hinges on `DATABASE_URL`. Local and cloud differ only by this one value:

| Where | DATABASE_URL source |
|---|---|
| Local dev | `.env` file → local Postgres |
| Cloud app | Streamlit Cloud → Settings → Secrets → Neon URL |

The code reads env first, then Streamlit secrets, so the same codebase runs in both places with no edits.
