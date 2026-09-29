FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

# Vite inlines VITE_* at build time, so browser-side settings are build args.
# The 2GIS routing key is NOT here: nginx adds it server-side at runtime.
ARG VITE_2GIS_KEY=""
ARG VITE_DEMO_MODE="false"
ENV VITE_2GIS_KEY=$VITE_2GIS_KEY \
    VITE_DEMO_MODE=$VITE_DEMO_MODE \
    VITE_API_BASE_URL=/api
RUN npm run build


FROM nginx:1.27-alpine

# The official image renders /etc/nginx/templates/*.template with envsubst on start.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

ENV BACKEND_URL=http://backend:8000 \
    DGIS_ROUTING_KEY=""

EXPOSE 80
