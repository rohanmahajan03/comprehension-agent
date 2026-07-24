# --- deps: install node modules once, shared by dev and build stages ---
FROM node:22-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit

# --- dev: vite dev server with hot reload (used by docker-compose.override.yml) ---
FROM deps AS dev

COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# --- build: production bundle ---
FROM deps AS build

COPY . .
RUN npm run build

# --- prod: static files behind nginx, /api proxied to the backend service ---
FROM nginx:alpine AS prod

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
