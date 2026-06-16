# webapp

Minimal Vite + React wrapper (repo-root, neutral — not owned by any one game) that
mounts the site shell `games/spender/Spender.jsx`, which in turn routes to Spender,
Castles of Crimson, and Books. Used for local dev; CI builds this for GitHub Pages.

Run:

```powershell
cd webapp
npm install
npm run dev
```

Open http://localhost:5173 and the app will mount the component.
