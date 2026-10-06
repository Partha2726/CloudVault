import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Read VITE_* from the repo-root .env so frontend and backend share one file locally.
  envDir: '..',
})
