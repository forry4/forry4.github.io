import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // Prod (GitHub Pages) serves under /WebProjects/; a staging host that serves at
  // the domain root (e.g. Cloudflare Pages *.pages.dev) sets VITE_BASE=/ instead.
  base: process.env.VITE_BASE || '/WebProjects/',
  plugins: [react()],
})
