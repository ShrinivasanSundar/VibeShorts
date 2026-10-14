import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  timeout: 120000,
  expect: { timeout: 30000 },
  fullyParallel: false,
  workers: 1,
  outputDir: "../.cache/browser-results",
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command:
        "../node_modules/.bin/firebase emulators:start --only auth --project demo-vibeshorts-browser --config tests/auth-emulator.json",
      url: "http://127.0.0.1:19099",
      timeout: 60000,
      reuseExistingServer: false,
    },
    {
      command: ".venv/bin/python tests/browser_server.py",
      cwd: resolve(__dirname, "../backend"),
      url: "http://127.0.0.1:8100/healthz",
      timeout: 60000,
      reuseExistingServer: false,
      env: {
        PYTHONPATH: ".",
        FIREBASE_AUTH_EMULATOR_HOST: "127.0.0.1:19099",
        GOOGLE_CLOUD_PROJECT: "demo-vibeshorts-browser",
        VIBESHORTS_PROVIDER: "fixture",
        VIBESHORTS_MODE: "emulator",
      },
    },
    {
      command: "npm run build && npm run start -- --port 3100",
      url: "http://127.0.0.1:3100",
      timeout: 120000,
      reuseExistingServer: false,
      env: {
        VIBESHORTS_BROWSER_FIXTURE: "true",
        NEXT_PUBLIC_MODE: "emulator",
        NEXT_PUBLIC_API_URL: "http://127.0.0.1:8100",
        NEXT_PUBLIC_FIREBASE_PROJECT_ID: "demo-vibeshorts-browser",
        NEXT_PUBLIC_FIREBASE_API_KEY: "demo-key",
        NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN:
          "demo-vibeshorts-browser.firebaseapp.com",
        NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL: "http://127.0.0.1:19099",
        NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST: "127.0.0.1:19080",
      },
    },
  ],
});
