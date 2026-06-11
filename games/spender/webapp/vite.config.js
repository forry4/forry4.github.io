import { defineConfig } from 'vite'

export default defineConfig({
  base: '/WebProjects/',
  esbuild: {
    jsx: 'automatic',
    jsxImportSource: 'react',
  },
})
