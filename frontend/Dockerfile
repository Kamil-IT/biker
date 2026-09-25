# Frontend image: Vite build served by nginx, /v1/* proxied to the backend.
# The same image runs under docker compose (BACKEND_URL=http://backend:8000) and on Cloud Run
# (BACKEND_URL=https://<biker-backend>.run.app, PORT injected) — see scripts/deploy.ps1.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# nginx renders /etc/nginx/templates/*.template → conf.d/*.conf at start, substituting only these two.
ENV PORT=8080 \
    BACKEND_URL=http://backend:8000 \
    NGINX_ENVSUBST_FILTER="^(PORT|BACKEND_URL)\$"
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
