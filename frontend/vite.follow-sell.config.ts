import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: process.env.FOLLOW_SELL_WEB_OUT || '../follow_sell/web',
    emptyOutDir: false,
    rollupOptions: { input: 'follow-sell.html' },
  },
});
