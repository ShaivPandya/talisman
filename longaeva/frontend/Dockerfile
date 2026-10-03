# node:22-bookworm-slim — digest pinned for reproducible frontend builds.
FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS frontend-src

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

FROM frontend-src AS check

FROM frontend-src AS build
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
