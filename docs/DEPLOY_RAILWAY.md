# Deploying FMS to Railway (always-on demo)

Stands up a public, login-gated FMS instance (backend + frontend) whose data
survives redeploys. ~15 minutes of clicking, ~$5–8/month. Render works the same
way (two services from one repo + a persistent disk); Railway is used here
because two always-on services fit its pricing better.

## Topology
- **backend** — FastAPI, built from `Dockerfile.backend`, listens on 8002, case
  store on a persistent **`/data`** volume. Publicly reachable (the browser's
  live-feed WebSocket connects to it directly; ingest is API-key protected, `/ws`
  is token + origin protected).
- **frontend** — Next.js, built from `frontend/Dockerfile`, listens on 3000.
  This is the **reviewer URL**. It proxies REST to the backend server-side
  (`/api/*` → `BACKEND_URL`); the browser opens the WebSocket straight to the
  backend (`NEXT_PUBLIC_WS_URL`).

## 0. Generate your three secrets (run locally — never share these)
```bash
python -c "import secrets; print('FMS_AUTH_SECRET    =', secrets.token_hex(32))"
python -c "import secrets; print('FMS_INGEST_API_KEY =', secrets.token_urlsafe(32))"
python -c "import secrets; print('FMS_SETUP_TOKEN    =', secrets.token_urlsafe(24))"
```
Keep them in your password manager. You paste them into Railway's **Variables**
(its own secret store) — they never go through chat, email, or the repo.

## 1. Create the project + two services
1. railway.com → **New Project** → **Deploy from GitHub repo** → authorize and pick `itsmrgeoffrey/FMS`.
2. The first service is your **backend**: open it → Settings → **Root Directory** `/`, **Dockerfile Path** `Dockerfile.backend`. Rename it **backend**.
3. **New → GitHub Repo** → same repo again for the **frontend**: Settings → **Root Directory** `frontend` (its Dockerfile is `frontend/Dockerfile`). Rename it **frontend**.
4. Leave **auto-deploy on push** on for both.

## 2. Backend: volume + variables
1. backend → **Volumes** → add a volume mounted at **`/data`**. *(This is what makes reviewers' work survive redeploys.)*
2. backend → **Variables**:
   ```
   FMS_DB_PATH=/data/fms.db
   FMS_ALLOW_SIGNUP=false
   FMS_TRUST_X_FORWARDED_FOR=true
   FMS_ENV=demo
   FMS_AUTH_SECRET=<your generated value>
   FMS_INGEST_API_KEY=<your generated value>
   FMS_SETUP_TOKEN=<your generated value>
   ```
3. backend → Settings → Networking → **Generate Domain**. Copy it, e.g. `fms-backend-production.up.railway.app`.

## 3. Frontend: variables (point at the backend domain)
frontend → **Variables**:
```
BACKEND_URL=https://<backend-domain>
NEXT_PUBLIC_WS_URL=wss://<backend-domain>/ws
```
frontend → Settings → Networking → **Generate Domain**, e.g. `fms-production.up.railway.app` — **this is your reviewer link**.

## 4. Close the loop (one cross-reference)
Back on **backend → Variables**, add the frontend origin so CORS + the WebSocket accept it:
```
FMS_CORS_ORIGINS=https://<frontend-domain>
```
Redeploy both (Railway usually redeploys on a variable change; if not, hit **Deploy**). The frontend rebuild bakes in `NEXT_PUBLIC_WS_URL`.

## 5. Send me the two domains
I'll then, against the live instance: bootstrap the first admin with your
`FMS_SETUP_TOKEN`, create **named reviewer logins**, seed sample cases so the
dashboard has content, and re-run the structuring/CTR simulation over HTTPS to
confirm everything works — then hand you the reviewer link, logins, and the two
review guides.

Afterwards, **delete `FMS_SETUP_TOKEN`** from the backend variables — it's only needed for the first-admin bootstrap.

## Environment variable reference
| Service | Variable | Value | Secret? |
|---|---|---|---|
| backend | `FMS_DB_PATH` | `/data/fms.db` | no |
| backend | `FMS_ALLOW_SIGNUP` | `false` | no |
| backend | `FMS_TRUST_X_FORWARDED_FOR` | `true` | no |
| backend | `FMS_ENV` | `demo` | no |
| backend | `FMS_CORS_ORIGINS` | `https://<frontend-domain>` | no |
| backend | `FMS_AUTH_SECRET` | *(generated)* | **yes** |
| backend | `FMS_INGEST_API_KEY` | *(generated)* | **yes** |
| backend | `FMS_SETUP_TOKEN` | *(generated; delete after bootstrap)* | **yes** |
| frontend | `BACKEND_URL` | `https://<backend-domain>` | no |
| frontend | `NEXT_PUBLIC_WS_URL` | `wss://<backend-domain>/ws` | no |

## Updating later
Edit locally → test (`uvicorn backend.main:app` + `npm run dev`) → `git push`.
Railway auto-rebuilds in ~3 min. Data on `/data` and everyone's logins (fixed
`FMS_AUTH_SECRET`) survive. If a deploy misbehaves: service → **Deployments →
Rollback**. For a risky change, push a branch and test it on a Railway PR/preview
environment before it reaches the reviewer instance.

## Cost
Two small always-on services ≈ $5–8/month on Railway's usage billing; this demo
is light and idles cheaply.
