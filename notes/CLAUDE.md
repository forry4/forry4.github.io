# Notes (site feature — a private notebook per account)

Nested folders of notes; each note is a flowing rich-text document with inline
screenshots. Built 2026-09-23 for tracking puzzle-game progress (Blue Prince first), for
the owner alone; **opened to every signed-in account the same day**. In Extras on the
home menu for everyone (a guest gets a "sign in" page).

- **Signed-in accounts only, on EVERY route** — `require_member` behind one `member`
  dependency; a guest has no session and gets a 401. `tests/test_notes.py` walks the
  registered routes and fails any `/notes` route that does not depend on it.
- **EVERY ROW HAS AN `owner_id` AND EVERY QUERY SCOPES BY IT.** Each pure function takes the
  caller's id as its SECOND argument — reads, writes, `_folder_parents` (so the tree walks,
  depth checks and folder moves only ever see your folders), the image fetch and the search.
  Another account's id behaves exactly like a missing one (404 / "no such folder"). The
  isolation test drives every function from a second account and then asserts the first
  notebook is byte-for-byte untouched — extend it when you add a function.
- **Rows from before owners existed are `owner_id IS NULL`** and invisible to everyone until
  the SITE_OWNER's first request claims them (`claim_unowned`, once per process). SITE_OWNER
  by NAME when set — an admin grant alone must not claim the owner's notebook.
- **Metered — `Meter` (notes/api.py)**, for every account but admins: 25MB (`NOTES_QUOTA_MB`),
  1000 notes (Trash included), 300 folders, and a SITE-WIDE ceiling across all metered
  accounts (`NOTES_SITE_BUDGET_MB`, 1024) so many accounts at quota cannot fill Turso either.
  Only GROWTH is checked, so a full account can always save a note smaller. A refusal is a 413
  whose detail the page shows as-is. `notes.size` (bytes of doc + plain text + title) is
  written on every save and backfilled at boot; usage is summed from it and cached a minute
  per account (Turso bills per row READ, and autosave checks on every save), moved by each
  write's delta in between. Emptying the Trash sweeps that account's unreferenced images with
  a one-hour grace, so the space comes back straight away.
- **Rate limits per account** (the owner too — a stolen session is still a session): 120
  writes/min and 3000/h (autosave is debounced to one save per 1s pause), 120 uploads/h, 60
  searches/min. A 429 and a `notes-rate` owner alert.
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
  throttled sweep drops images no note OF THE SAME ACCOUNT references (`instr` on the id) once
  they are 7 days old — keeps editor undo working and lets an image pasted into a second note
  survive. (Same account: pasting someone else's image id into your note must not keep it alive.)
- **Frontend** — `Notes.jsx` (page, sidebar tree, Pinned/Recent, Trash, Move dialog) lazily
  loads `NoteEditor.jsx` (TipTap v3, ~135KB gz — only a signed-in visitor ever downloads it).
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
- **Alignment (left / center / right)** is `@tiptap/extension-text-align` on paragraphs and
  headings — EXCEPT when an image is selected, where the same buttons set the image node's
  `align` attr (its frame's auto margins). One control, whatever is selected.
- **Search, two kinds.** The SIDEBAR box searches all notes, or one folder and every folder
  inside it (`GET /notes/search`, scope via a folder's "Search in this folder" or the "Only in
  X" link). It reads `notes.body_text` — the note's PLAIN text, one block per line plus image
  captions, written on every save and backfilled at boot by `init_notes_db` — never `doc`,
  where a bolded word is its own node ("reads 3:15" is not a substring of the JSON, and
  "paragraph" would match every note). SQL `instr(lower())` narrows ASCII queries only (sqlite
  folds ASCII alone); the exact filter is Python's. Snippets are text + offsets, never HTML.
  The NOTE's find bar (`find.js`, Ctrl/Cmd+F or the magnifier) is decorations only, so finding
  never edits or saves the note; it matches per text BLOCK across runs, includes captions, and
  scrolls a match below the sticky bars itself (ProseMirror's scrollIntoView put it under them).
  A search hit opens its note with the query already in the find bar, without focusing it (on
  a phone that would throw the keyboard over the match).
- **Right-click menus** (`menu.jsx` = the menu + note picker, `editorMenu.js` = clipboard,
  note links, image copy/download, check-all, selection-as-doc). Context-sensitive: an image,
  a link, a list, a selection each add their own section; the sidebar's rows share one menu
  with their ⋯ button. Shift+right-click and any TOUCH long-press keep the browser's menu.
  Bugs found making it, all covered by the menus e2e: the menu renders `visibility:hidden` for
  one frame while it measures, and a hidden button cannot take focus — focus the first item
  only once it is visible, or arrows/Escape do nothing; scroll events arrive a frame LATE, so
  "close on scroll" must ignore scrolls already in flight when it opened; ProseMirror calls
  `handleClick` for EVERY mouse button (a right-click on a note link opened the note); and
  tiptap's list toggles convert into/out of a checklist for the SELECTION only, so "Convert
  list to" rebuilds the whole list node itself (`rebuildList`).
- **Note links** are ordinary link marks whose href is the note's own URL (`/notes/<id>`) —
  they survive copy/paste and work as plain URLs anywhere. Recognised by the href, never a
  class; a plain click opens a NOTE link, a web link needs Ctrl/Cmd+click. The picker offers
  to create a note that doesn't exist yet. "Move to a new note" round-trips the selection
  through the schema's own HTML serialiser + parser so a half-selected list still becomes a
  valid document. Menu Paste reads the clipboard (Chrome/Edge ask once; Firefox mostly
  refuses, and the menu then says to use Ctrl+V) and goes through `view.pasteHTML/pasteText`,
  the same pipeline as a real paste.
- **A checklist's checkbox floats over its text's left padding; it is not a flex column.**
  The item is `<li><label contenteditable=false>☐</label><div>text</div></li>`. As a flex
  column, every touch in the gutter (under the box, beside it) hit-tested to the LABEL,
  a DOM point ProseMirror cannot hold, so it rewrote the selection and a phone's selection
  handles jumped mid-drag ("selecting text on mobile is pain, especially checklists").
  `notesEditor` samples every point of every list row at 390px and fails any that does not
  land the caret in text, except the checkbox itself — and a bullet's MARKER: Chromium 149
  (CI's) hit-tests it as the `<li>` and carets at `(li, 0)`, the start of that line, where
  141 and WebKit hit nothing. That one case is accepted by name; it failed the first deploy
  of this check because the local Playwright Chromium here was 141.
- **One line rhythm inside a list, and no two lists ever touch.** Every pair of lines in a
  list is `.15em` apart (item to item, text to its nested list, a second paragraph in an
  item); only item-to-item had it, so a nested list hugged its parent. And `JoinLists`
  merges same-type sibling lists after every edit: Backspace / Shift-Tab on a nested item
  and deleting the line between two lists all left two lists touching, spaced as separate
  blocks (a hole mid-list, a numbered list restarting at 1). `notesEditor` replays those
  keystrokes and measures every gap.
- **Leaving a note never drops what was typed.** Three exits did (`notesEditor` covers each
  against the stub's copy): switching notes while a save was on the wire (the follow-up save
  waited on a timer an unmounted editor never runs; a flush that arrives mid-save now runs the
  moment that save returns); and trashing the open note, or deleting its folder (the last save
  landed AFTER the trash, was refused as "no such note", and the page blamed "elsewhere"). The
  page now awaits the editor's `flush()` (handed up through `flushRef`) before either.
- **Read-only is enforced on the document, not the keyboard.** `editable: false` only stops
  typing; toolbar buttons, shortcuts and the image's own controls run COMMANDS, which change
  the document regardless — so a note in the Trash showed edits it could never save.
  `ReadOnlyGuard` refuses any doc-changing transaction while the editor is not editable, and
  a trashed note's toolbar is Find alone.
- **Ticking a checklist box does not focus the note.** tiptap's TaskItem focuses the editor
  before it toggles, and on a phone focus raises the keyboard — every tick while READING a
  list threw it up. A capture-phase `change` listener on the editor toggles the item itself
  and stops the event before tiptap's. (The owner uses Safari on iOS; the e2e is Chromium,
  so it asserts the cause — focus — not the keyboard.)
- **16px floor** on every typing surface (title, prose, folder rename, caption, both search
  boxes) — the iOS zoom footgun. `formControlZoom` can't reach a signed-in-only page, so
  `notesEditor` in `webapp/test/screens.mjs` measures all six (stubbed API + seeded admin).
- **Deferred** (asked, not chosen for v1): links between notes, per-note status, screenshot
  annotation. The data model has room for all three.
- **Tests:** `tests/test_notes.py` (pure functions on a real sqlite file via `core.db._Conn`,
  plus the route-gate walk); `notesEditor` in `screens.mjs` for the frontend.
