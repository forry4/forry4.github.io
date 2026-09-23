# Notes (site feature — the owner's private notebook)

Nested folders of notes; each note is a flowing rich-text document with inline
screenshots. Built 2026-09-23 for tracking puzzle-game progress (Blue Prince first).
In Extras on the home menu, **shown only to admins**.

- **Owner-only on EVERY route, reads included** — `require_owner` (`core.auth.is_site_owner`)
  behind one `owner` dependency. `tests/test_notes.py` walks the registered routes and fails
  any `/notes` route that does not depend on it, so a new route cannot ship public. The hidden
  home tile is a convenience, never the gate.
- **Backend** (`api.py`) — `setup_notes(...)` with Books' injected deps. Tables `note_folders`
  (nested by `parent_id`, cycle + depth-12 checks), `notes` (`doc` = TipTap JSON as TEXT),
  `note_images` (base64 TEXT, not BLOB — the libsql path can't be tested on Windows). Handlers
  are sync `def` so Turso round-trips and image inserts run in the threadpool, not on the loop.
  CORS allows no PATCH, so metadata edits are `POST .../meta`.
- **Stale-edit guard**: `rev` + `base_rev`; a mismatch is a 409 carrying the server copy
  (the check-and-write is one `UPDATE ... WHERE rev=?`). Only CONTENT saves bump `rev` /
  `updated_at` — moving, pinning or trashing must not 409 an open tab, and Recent means
  "last edited".
- **Deletes are soft** (Trash, purged after 30 days). Images are never deleted directly: a
  throttled sweep drops images no note's `doc` references (`instr` on the id) once they are
  7 days old — keeps editor undo working and lets an image pasted into a second note survive.
- **Frontend** — `Notes.jsx` (page, sidebar tree, Pinned/Recent, Trash, Move dialog) lazily
  loads `NoteEditor.jsx` (TipTap v3, ~135KB gz — only the owner ever downloads it).
  `/notes/<noteId>` and `/notes/trash` are deep links; router.js upper-cases segment 2, and ids
  are lowercase, so the page lower-cases it back.
- **Images**: paste / drop / file picker (camera + gallery on phones) → `images.js` downscales
  to a 1920px long edge, WebP (JPEG where the browser can't encode WebP) → upload → a
  `noteImage` node that references the image BY ID. Loaded via an authenticated fetch → blob
  URL (an `<img src>` cannot send the Bearer header; no tokens in URLs). An image still
  uploading has no id and is stripped from saves.
- **Editor behaviours that were bugs first** (all covered by the e2e): a drop lands BETWEEN
  blocks (at the raw point it split "T" | image | "he clock…"); Enter in the title moves the
  cursor SYNCHRONOUSLY (tiptap's `focus()` waits a frame, so the next key landed in the title);
  inserting while an image is selected goes AFTER it (at the selection it replaced it); a new
  note's title takes focus when its editor MOUNTS (a 250ms timer stole focus mid-sentence).
- **The Image button is FIRST in the toolbar, labelled, and opens the picker on click.** On a
  phone the toolbar scrolls sideways, and at its far end the icon-only button was off-screen —
  the one way to add a picture on a phone was unfindable. `notesEditor` asserts it on screen.
- **Tab / Shift-Tab are always consumed in the note** (`Indent` extension, priority above the
  list items): nest / un-nest a list item, else step a paragraph or heading's `indent` attr
  (0-8, drawn as margin). Left to the browser, Tab moved focus out of the editor. Toolbar
  Indent/Outdent buttons do the same for phones, which have no Tab key.
- **16px floor** on every typing surface (title, prose, folder rename, caption) — the iOS zoom
  footgun. `formControlZoom` can't reach an owner-only page, so `notesEditor` in
  `webapp/test/screens.mjs` measures all four (stubbed API + seeded admin).
- **Deferred** (asked, not chosen for v1): links between notes, per-note status, screenshot
  annotation, full-text search. The data model has room for all four.
- **Tests:** `tests/test_notes.py` (pure functions on a real sqlite file via `core.db._Conn`,
  plus the route-gate walk); `notesEditor` in `screens.mjs` for the frontend.
