# Pinned to the newest patch of each line. The previous pins carried eleven HIGH
# advisories in the alpine base layer alone — c-ares, curl, libcurl, libcrypto3,
# libssl3 — reported by container:scan the first time it managed to read the
# image, on 2026-08-03. The API image was clean; this one was not.
ARG NODE_IMAGE=node:22.23.2-alpine
ARG NGINX_IMAGE=nginx:1.31.3-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /src
COPY apps/web/package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY apps/web ./
RUN npm run lint && npm run build

FROM ${NGINX_IMAGE} AS runtime
COPY apps/web/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /src/dist /usr/share/nginx/html
RUN mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp \
    && chown -R nginx:nginx /tmp/nginx /usr/share/nginx/html \
    && chmod -R a-w /usr/share/nginx/html
USER nginx:nginx
EXPOSE 8080
STOPSIGNAL SIGQUIT
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=4 \
  CMD wget -q -T 2 -O - http://127.0.0.1:8080/healthz >/dev/null || exit 1
