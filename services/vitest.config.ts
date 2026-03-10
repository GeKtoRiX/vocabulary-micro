import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['../tests/services/**/*.test.ts'],
    environment: 'node',
  },
})
