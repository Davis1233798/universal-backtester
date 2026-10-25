import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../unibacktest/static/app', emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 700 },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } }
});