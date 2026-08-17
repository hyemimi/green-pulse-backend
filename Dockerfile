# Multi-stage Docker build for the Green-Pulse Nest.js API.
# The image contains only the API server and migration SQL.
# Large local data files such as chemical_process_timeseries.csv and fault_run/ are intentionally excluded.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package*.json ./
COPY tsconfig.json nest-cli.json ./
COPY src ./src
COPY database ./database
RUN npm run build
RUN npm prune --omit=dev

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/database ./database
EXPOSE 10000
CMD ["node", "dist/main.js"]
