import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Login sub-slice L7c (owner answer (a) to Q-2026-10-21-159): when the local certificate of
// `scripts/local/make-certificate.sh` is in the ignored `.local/https` folder, the screen server
// uses HTTPS and lets the Mac mini's `.local` name in, so the iPad on the same Wi-Fi can open it
// too. It forwards `/api` to the API on 127.0.0.1:8000, so the screens and the API share one
// origin and the `__Host-` cookies work. Without the certificate it stays plain HTTP, as before;
// but `npm run dev:local` (PRM_LOCAL_HTTPS=1, open to the Wi-Fi) refuses to start without it, so
// a password never crosses the Wi-Fi in plain HTTP. The proxy adds X-Forwarded-For, which the
// API's server trusts from 127.0.0.1 only, so the sign-in waits count each device on its own.
const httpsFolder = fileURLToPath(new URL("../.local/https/", import.meta.url));
const certificateFile = `${httpsFolder}server.pem`;
const keyFile = `${httpsFolder}server-key.pem`;
const localHttps =
  existsSync(certificateFile) && existsSync(keyFile)
    ? { cert: readFileSync(certificateFile), key: readFileSync(keyFile) }
    : undefined;
if (process.env.PRM_LOCAL_HTTPS === "1" && localHttps === undefined) {
  throw new Error(
    "No local certificate: run sh scripts/local/make-certificate.sh first (README, Local run on the Mac mini).",
  );
}

export default defineConfig({
  plugins: [react()],
  server: {
    ...(localHttps === undefined
      ? {}
      : { https: localHttps, allowedHosts: [".local"] }),
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
        xfwd: true,
      },
    },
    // Vite's own list, and the ignored `.local` folder of the local secrets and certificate.
    fs: {
      deny: [".env", ".env.*", "*.{crt,pem}", "**/.git/**", "**/.local/**"],
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
