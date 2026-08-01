## v1 — 2026-07-30 (scaffolding)
- Added: dev topology — Vite dev server + Uvicorn --reload, bind mounts, override compose file
- Added: prod-like topology — Nginx serving built dist/, FastAPI final image
- Added: .env as shared env_file source for both backend targets
- Why: document the dual dev/prod docker compose setup so the override-vs-base gotcha is visible
