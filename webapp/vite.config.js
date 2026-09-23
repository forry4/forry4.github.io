import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  // Prod is a GitHub Pages USER site (repo forry4.github.io) served at the domain
  // root https://forry4.github.io/, so the base is '/'. Override with VITE_BASE only
  // if ever served under a sub-path again (e.g. a project-site repo).
  base: process.env.VITE_BASE || '/',
  // Identifies THIS build. In CI it's the commit; locally it's `dev`, which switches
  // the update nudge off (nothing to compare a local build against).
  define: { __BUILD_ID__: JSON.stringify(process.env.GITHUB_SHA || 'dev') },
  plugins: [
    react(),
    {
      // Emit version.json alongside the bundle carrying the SAME id compiled into
      // it. A running tab fetches this (cache: no-store) and knows it is stale when
      // the ids differ — see shared/update-nudge.js.
      name: 'emit-build-version',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'version.json',
          source: JSON.stringify({ build: process.env.GITHUB_SHA || 'dev' }),
        })
      },
    },
    {
      // Emit the service worker from webapp/sw.js with __BUILD_ID__ stamped into its
      // cache name, so each deploy's `activate` drops the previous deploy's cache.
      // The source deliberately does NOT live in public/ (which is copied verbatim —
      // an unstamped literal "__BUILD_ID__" cache would never rotate). Read at
      // generateBundle time so watch/rebuild picks up edits.
      name: 'emit-service-worker',
      generateBundle() {
        const src = readFileSync(path.join(here, 'sw.js'), 'utf8')
        this.emitFile({
          type: 'asset',
          fileName: 'sw.js',
          source: src.replaceAll('__BUILD_ID__', process.env.GITHUB_SHA || 'dev'),
        })
      },
    },
  ],
  resolve: {
    // Source outside webapp/ (games/, shared/, books/, notes/) has no node_modules
    // above it — the ONLY node_modules is webapp's. Vite resolves a bare import from
    // the importing file's directory, so `import "@tiptap/react"` in notes/ fails to
    // resolve at all. `react` never hit this only because plugin-react dedupes it,
    // and dedupe resolves from the project root. Every package imported from outside
    // webapp/ must be listed here (the tiptap set is Notes' editor; @tiptap/pm keeps
    // ProseMirror single-copy, which it must be — two copies break instanceof checks).
    dedupe: [
      '@tiptap/react', '@tiptap/core', '@tiptap/pm', '@tiptap/starter-kit',
      '@tiptap/extension-list', '@tiptap/extensions', '@tiptap/extension-text-align',
    ],
  },
  build: {
    // The games' stylesheets are imported with `?inline` and injected by each
    // component's own <style> tag (see any game's .jsx header). They used to be JS
    // template literals, which Vite never touched. Keeping minification OFF means
    // the emitted string is the .css file VERBATIM — so moving them out of JS is a
    // provably behaviour-free change, not "probably fine because esbuild's CSS
    // minifier is usually lossless". Turn this on deliberately, with a visual
    // check, if the ~45KB is ever worth it.
    cssMinify: false,
  },
})
