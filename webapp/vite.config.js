import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // Prod is a GitHub Pages USER site (repo forry4.github.io) served at the domain
  // root https://forry4.github.io/, so the base is '/'. Override with VITE_BASE only
  // if ever served under a sub-path again (e.g. a project-site repo).
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
})
