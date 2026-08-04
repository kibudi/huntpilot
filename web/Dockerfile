# Builds the static bundle, then serves it from nginx. The build tooling does not survive into the
# final image, which is why this is a multi-stage build rather than one that ships node.
FROM node:22-slim AS build

WORKDIR /src

# npm ci installs exactly what the lockfile says and fails if package.json disagrees, which is what
# makes an image reproducible.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Debian-based rather than -alpine: the Alpine variant fails with "exec format error" under this
# host's WSL2 kernel, even for a plain `echo`. The image is larger; it also runs.
FROM nginx:1.27

COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
