import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Favicon is bundled from src so Windows public-directory copying cannot lock the build.
  publicDir: false,
  // Keep the pre-created directory on Windows; Vite still replaces hashed assets.
  build: { emptyOutDir: false },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    clearMocks: true,
  },
});
