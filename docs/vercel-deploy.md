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
