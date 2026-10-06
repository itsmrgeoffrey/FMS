# FMS dashboard — Next.js production build
FROM node:24-alpine AS build
WORKDIR /app
# Build-time config. Railway passes matching service variables into these ARGs,
# so Next bakes the correct API-proxy target (BACKEND_URL) and inlines the public
# WebSocket URL (NEXT_PUBLIC_WS_URL) into the production build. Without them the
# build falls back to localhost:8002, which does not exist in the cloud.
ARG BACKEND_URL
ARG NEXT_PUBLIC_WS_URL
ENV BACKEND_URL=$BACKEND_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
