import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/frontend',
  timeout: 60_000,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8765',
    headless: true,
    browserName: 'firefox',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
