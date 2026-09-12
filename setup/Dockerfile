FROM node:24.16.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build
FROM node:24.16.0-alpine
WORKDIR /app
COPY --from=build --chown=node:node /app/.output ./.output
ENV NODE_ENV=production HOST=0.0.0.0 PORT=8080
USER node
EXPOSE 8080
CMD ["node", ".output/server/index.mjs"]
