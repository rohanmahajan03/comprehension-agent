No DB tables — this diagram covers deployment topology, not data model.

## Connections

**Browser → ViteDev**
In dev mode, the browser talks directly to the Vite dev server on :5173 for hot-reloaded frontend assets.

**ViteDev → UvicornReload**
Vite proxies `/api` requests to the backend using the `BACKEND_URL` env var (`vite.config.ts`), so the frontend never needs to know the backend's real address.

**EnvFile → UvicornReload**
`docker-compose.yml` sets `env_file: .env` on the backend service — compose fails to start without a `.env` present.

**Browser → Nginx**
In prod-like mode, the browser is served the pre-built `dist/` bundle by Nginx on :5173→80.

**Nginx → FastAPIProd**
Nginx proxies `/api` to `backend:8000` per `frontend/nginx.conf`, replacing Vite's dev-time proxy.

**EnvFile → FastAPIProd**
Same `.env` file backs both the dev and prod-like backend targets.
