FROM node:22-slim
RUN corepack enable && corepack prepare pnpm@12.6.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
EXPOSE 5173
CMD ["pnpm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
