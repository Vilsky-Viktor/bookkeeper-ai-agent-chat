import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    allowedHosts: true, // served through Caddy on localhost:8080, not directly
    watch: {
      // Bind-mounted source (./web:/app) doesn't always propagate inotify events
      // across the Docker Desktop/Colima VM boundary, so HMR can silently miss host
      // edits without this.
      usePolling: true,
      interval: 300,
    },
  },
});
