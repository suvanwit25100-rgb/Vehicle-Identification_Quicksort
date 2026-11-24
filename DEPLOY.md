# Deploying ExLex: pages on Vercel, API on a container host

Vercel serves the pages. The Python API, the models and the data run on a host that allows long jobs, big dependencies and a disk that
survives restarts (Render below; Fly or Railway work with the same `Dockerfile`). Vercel cannot run the API itself: the models alone are far past its
size limit, an analysis takes longer than a function may run, and it has no persistent disk.

You do these steps with your own accounts. Nothing here has been deployed yet.

## 1. The API on Render
1. Push this repository to GitHub (private is fine).
2. Render dashboard > **New** > **Blueprint** > pick the repository. It reads `render.yaml`.
3. When asked, fill the three secrets:
   - `EXLEX_OFFICER_KEY`: the master officer key. Make a new long random one (for example `python3 -c "import secrets; print(secrets.token_urlsafe(18))"`); do not reuse the local one.
   - `EXLEX_CORS_ORIGINS`: your Vercel address, for example `https://exlex.vercel.app` (you can set it after step 3).
   - `EXLEX_PUBLIC_URL`: the same Vercel address (used inside password-reset links).
4. The plan in `render.yaml` is `standard` (about 2 GB of memory) with a 10 GB disk. The models need that memory, so the free and starter plans will not run it. This is a paid plan: check Render's current price.
5. First build takes several minutes (it installs PyTorch). Open `https://<service>.onrender.com/api/health`; it should answer `{"status":"ok",...}`.

## 2. The pages on Vercel
1. On your computer, in the repository: `python3 deploy/set_backend.py https://<service>.onrender.com`, then commit and push.
   It edits `vercel.json` (the `/api` rewrites) and `backend/app/static/config.js` (where video uploads go, because a proxy cannot carry large uploads).
2. Vercel dashboard > **Add New** > **Project** > import the repository. Framework preset **Other**; leave the build and install commands empty; the root directory is the repository root. `vercel.json` does the rest.
3. Once it is live, set `EXLEX_CORS_ORIGINS` and `EXLEX_PUBLIC_URL` on Render to the Vercel address and let Render redeploy.

## 3. Sign in
Open `https://<your-project>.vercel.app/officer/`, choose **Master key**, and enter the key you set on Render. Then create an account for yourself under **Team** and turn on two-factor.

## What to expect
- **It starts empty.** Your local analyses, reports and accounts are not uploaded. Analyse a clip on the live site, then use **Load demo reports** on the officer dashboard if you want a populated queue.
- **No CLIP model.** The 577 MB body-type model is not in the image, so body type falls back to the detector's class. Everything else works. To add it, run `python backend/scripts/download_models.py` in a Render shell.
- **Password-reset email** is only queued (admin "Mail queue") unless you also set `EXLEX_SMTP_HOST` and `EXLEX_SMTP_FROM` (and optionally `_PORT`, `_USER`, `_PASSWORD`).
- **Large downloads** (a case ZIP with its video) pass through Vercel's proxy and may be cut off if they are very big; the API address always works directly.
- **The image has not been built here.** There is no Docker on the machine this was written on. The start command and settings were exercised locally, but the first Render build is the first real test of the `Dockerfile`: if a package fails to install, the build log says which.
