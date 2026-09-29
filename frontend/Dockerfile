FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# The context includes frontend/.env: Vite inlines its VITE_* values (map key)
# at build time. Build args / environment override it, e.g. VITE_DEMO_MODE.
COPY . .

ARG VITE_DEMO_MODE="false"
ENV VITE_DEMO_MODE=$VITE_DEMO_MODE \
    VITE_API_BASE_URL=/api
RUN npm run build


FROM nginx:1.27-alpine

# The official image renders /etc/nginx/templates/*.template with envsubst on
# start; *.envsh scripts are sourced before that (routing key fallback).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 nginx/05-routing-key.envsh /docker-entrypoint.d/05-routing-key.envsh
COPY --from=builder /app/dist /usr/share/nginx/html

ENV BACKEND_URL=http://backend:8000

EXPOSE 80
