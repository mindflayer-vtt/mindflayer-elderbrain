FROM node:26.11.1-alpine@sha256:143494b1da2945f061539253adc65e4f1569ddf07da2d384c022c791a9d90a4a AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build
FROM node:26.11.1-alpine@sha256:143494b1da2945f061539253adc65e4f1569ddf07da2d384c022c791a9d90a4a
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
