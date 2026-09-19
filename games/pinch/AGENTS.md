# Pinch implementation guide

Pinch is a two-player, server-authoritative implementation of the YINSH ruleset with original
branding and presentation. `engine.py` is the only rules authority; the React client renders the
public view and sends one of the exact objects returned by `legal_moves` unchanged.

## Rules and state

- The 85 intersections are stable integer IDs generated from radius-five axial coordinates with the
  six corners removed. Do not reorder `NODES`; persisted positions and browser coordinates depend on
  those IDs.
- `pending_pid`, `pending_kind`, and `pending` are durable state. Row choice and ring removal must
  survive persistence/reconnect and no ordinary move may bypass them.
- Resolve the mover's rows first, rescanning after each row and removed ring, then resolve the other
  color. A run longer than five exposes each legal five-marker window.
- Standard ends at three removed rings. Blitz ends at one. No ongoing RNG state is stored: only the
  randomized starting `order` is persisted.
- State stays JSON-safe. `persist.py` is the only at-rest compaction boundary; live and wire shapes
  remain verbose.

## Rooms and AI

- A socket is registered only after create/join/reconnect proof. `mk_room_state` scopes reconnect
  tokens to the recipient and `player_view` scopes legal moves to the viewer.
- Easy AI uniformly selects from the complete legal-action list. Search/selection runs in the bot
  executor from a detached snapshot, then revalidates the position before applying.
- Database writes are submitted to the single background writer. Never perform bot work or database
  I/O synchronously on the event-loop thread while holding `ROOM_LOCK`.

## Client and visual contract

- The entire board is one SVG coordinate system. Keep pieces, broad hit regions, row targets, score
  rails, and animation transforms inside it.
- Pearl is always `game.order[0]`; obsidian is `game.order[1]`. Rotating the view for the second seat
  changes presentation only, never node IDs.
- New authoritative `event_seq` values may animate; initial load, reconnect, and duplicate broadcasts
  only establish a baseline. Reduced motion must preserve the final state without travel or flips.
- The shared lobby, create modal, waiting room, rules modal, and game menu own their chrome. Pinch's
  graphite/cyan styling begins at the live game surface.
- Acceptance viewports are 320×568, 360×800, 390×844, 430×932, 768×1024, 1920×1080, and 2560×1600.
