import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // `npm run dev` reads data from the Python server (python3 server.py).
  server: { proxy: { '/api': 'http://127.0.0.1:8080' } },
});
