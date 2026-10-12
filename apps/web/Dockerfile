# Motivation vs Logic
# Motivation: The staging load balancer was serving only the API, so a browser
# request for / received Starlette's "Not Found".
# Logic: Production Next server on port 3000, linux/arm64, built from the
# repo root: docker build -f apps/web/Dockerfile .

FROM node:22-bookworm-slim

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ .
# Pages read the partner docs two levels above the app directory.
# In this image the app directory is /app, so those files live at /.
COPY MCP.md /MCP.md
COPY API.md /API.md
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
ENV NODE_ENV=production
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
