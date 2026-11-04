import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.join(here, '..')

// The APP id: what a running tab would actually change if it reloaded. The build
// id is the commit, and the price, LoL and anime refresh jobs each commit a data
// file and redeploy, several times a day. That moved the build id with no code
// change, so every open tab was asked to Refresh for a page no reload would alter.
// So the id hashes the INPUTS the bundle is built from (every module's source on
// disk, public/ minus the runtime-fetched public/data/, and the VITE_* settings).
// It cannot hash the output: the output contains this id.
const APP_ID_TOKEN = '__FG_APP_ID__'
function appIdOf(ctx) {
  const rel = (p) => path.relative(repo, p).split(path.sep).join('/')
  const parts = []
  for (const id of ctx.getModuleIds()) {
    if (id.startsWith('\0')) { parts.push([id, ctx.getModuleInfo(id)?.code ?? '']); continue }
    const [file, query] = id.split('?')
    parts.push([rel(file) + (query ? `?${query}` : ''), existsSync(file) ? readFileSync(file) : ''])
  }
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) { if (rel(p) !== 'webapp/public/data') walk(p) }
      else parts.push([rel(p), readFileSync(p)])
    }
  }
  walk(path.join(here, 'public'))
  parts.push(['index.html', readFileSync(path.join(here, 'index.html'))])
  for (const k of Object.keys(process.env).filter((k) => k.startsWith('VITE_')).sort()) parts.push([`env:${k}`, process.env[k]])
  const h = createHash('sha256')
  for (const [k, v] of parts.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))) h.update(k).update('\0').update(v).update('\0')
  return h.digest('hex').slice(0, 16)
}

export default defineConfig({
  // Prod is a GitHub Pages USER site (repo forry4.github.io) served at the domain
  // root https://forry4.github.io/, so the base is '/'. Override with VITE_BASE only
  // if ever served under a sub-path again (e.g. a project-site repo).
  base: process.env.VITE_BASE || '/',
  // Identifies THIS build. In CI it's the commit; locally it's `dev`, which switches
  // the update nudge off (nothing to compare a local build against).
  // The service worker and offline downloads keep keying on it: a data-only deploy
  // still has to refresh an offline copy of that data. __APP_ID__ is a token here,
  // filled in at renderChunk (before chunk file names are hashed) once the module
  // graph is known.
  define: {
    __BUILD_ID__: JSON.stringify(process.env.GITHUB_SHA || 'dev'),
    __APP_ID__: JSON.stringify(APP_ID_TOKEN),
  },
  plugins: [
    react(),
    (() => {
      let appId = null
      return {
        // Emit version.json alongside the bundle carrying the SAME ids compiled into
        // it. A running tab fetches this (cache: no-store) and knows it is stale when
        // the app ids differ — see shared/update-nudge.js.
        name: 'emit-build-version',
        renderChunk(code) {
          if (!code.includes(APP_ID_TOKEN)) return null
          appId ??= appIdOf(this)
          return { code: code.replaceAll(APP_ID_TOKEN, appId), map: null }
        },
        generateBundle() {
          appId ??= appIdOf(this)
          this.emitFile({
            type: 'asset',
            fileName: 'version.json',
            source: JSON.stringify({ build: process.env.GITHUB_SHA || 'dev', app: appId }),
          })
        },
      }
    })(),
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
      '@tiptap/extension-list', '@tiptap/extensions', '@tiptap/extension-text-align', '@tiptap/extension-highlight',
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
