# Quantro-flow on Vercel

## What this deploy covers
- **Frontend** (CRA under `frontend/`) on Vercel Hobby.
- `frontend/.npmrc` sets `legacy-peer-deps=true` so `react-day-picker@8` installs under React 19.

## Backend
FastAPI (`backend/server:app`) is **not** part of this Vercel project (Hobby / classic build). Host it separately (Railway, Fly, Render, or Emergent) and set:

```
REACT_APP_BACKEND_URL=https://<your-api-host>
```

in the Vercel project Environment Variables (Production + Preview), then redeploy.

## Local install parity
```bash
cd frontend && npm install --legacy-peer-deps
```

## Fly.io backend

App name: `quantro-flow-api` (see `fly.toml`).

```bash
fly auth login
fly apps create quantro-flow-api --org personal
fly secrets set MONGO_URL=... SUPABASE_URL=... SUPABASE_ANON_KEY=... SUPABASE_SERVICE_ROLE_KEY=... FRONTEND_PUBLIC_URL=https://quantro-flow.vercel.app BACKEND_PUBLIC_URL=https://quantro-flow-api.fly.dev
fly deploy
```

Then set `REACT_APP_BACKEND_URL=https://quantro-flow-api.fly.dev` on the Vercel project and redeploy.
