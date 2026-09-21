FROM node:26.9.0-alpine@sha256:dbaa92e5758cbbcf85d65d5403fdb530fe3442cbe8c6dbfb7ef23365450d5070 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build
FROM node:26.9.0-alpine@sha256:dbaa92e5758cbbcf85d65d5403fdb530fe3442cbe8c6dbfb7ef23365450d5070
ARG SETUP_VERSION=1.0.0
ARG HOST_API_MIN=1
ARG HOST_API_MAX=1
RUN addgroup -S -g 31338 elderbrain-management
LABEL org.opencontainers.image.version=$SETUP_VERSION \
      io.mindflayer.elderbrain.host-api-min=$HOST_API_MIN \
      io.mindflayer.elderbrain.host-api-max=$HOST_API_MAX
WORKDIR /app
COPY --from=build --chown=node:node /app/.output ./.output
ENV NODE_ENV=production HOST=0.0.0.0 PORT=8080
USER node:elderbrain-management
EXPOSE 8080
CMD ["node", ".output/server/index.mjs"]
