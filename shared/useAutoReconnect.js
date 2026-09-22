import { useCallback, useEffect, useRef } from "react";

/* Keep retrying a dropped game socket until it is back.
 *
 * WITHOUT this, "Reconnecting…" is a LIE: four of the six socket games once
 * rendered that word from `!connected` and then did nothing about it, so a
 * dropped socket sat there until the player reloaded the page. Rag Tag was
 * reported that way — "I sometimes see 'reconnecting…' and the game is frozen
 * til I reload". Every socket game with a live room now uses this hook; CoC,
 * Duel, Dontminion and Dissonance each carried an inline copy until 2026-09-22.
 *
 * It is worse than a stale view in a vs-bot game. The bot's turn is only
 * re-driven when a client reconnects (`_handle_reconnect` re-triggers the
 * server-side scheduler), so a socket that never comes back means a bot that
 * never moves. That is the "hung for minutes" bug, and it is why the retry uses
 * the `reconnect` ACTION rather than `join` — only reconnect resumes the bot.
 *
 * Sockets drop for ordinary reasons: Render's free tier cold-starts in 30–50s,
 * phones kill backgrounded sockets, and wifi hiccups. So the loop retries
 * indefinitely with a short backoff rather than giving up after N tries, and a
 * tab coming back into focus fires an immediate attempt — iOS frequently kills a
 * backgrounded socket WITHOUT firing `onclose`, so `connected` can be a stale
 * `true` and the visibility nudge is the only thing that notices.
 *
 * Extracted from Castles of Crimson, which is the one game that had it. Policy
 * stays at the call site (`enabled` decides what counts as a live game; the
 * token lookup differs per game), because that is the part that genuinely
 * differs and the retry machinery is the part that should not.
 */
export function useAutoReconnect({ enabled, connected, connect, socketReady, onAttempt }) {
  const timer = useRef(null);
  const tries = useRef(0);
  const attemptRef = useRef(null);

  const attempt = useCallback(() => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    const rs = socketReady();
    // CONNECTING (0) or OPEN (1): a retry here would abort a socket that is
    // already on its way up. Re-check instead.
    if (rs === 0 || rs === 1) {
      timer.current = setTimeout(() => attemptRef.current(), 3000);
      return;
    }
    connect();
    tries.current += 1;
    // 2s, 4s, 6s … capped at 8s, forever — a cold start alone can take 50s.
    timer.current = setTimeout(() => attemptRef.current(),
      Math.min(2000 * tries.current, 8000));
    if (onAttempt) onAttempt(tries.current);
  }, [connect, socketReady, onAttempt]);
  attemptRef.current = attempt;

  useEffect(() => {
    const clear = () => {
      if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    };
    if (connected || !enabled) {
      clear();
      tries.current = 0;
      return undefined;
    }
    if (!timer.current) attempt();
    return clear;
  }, [connected, enabled, attempt]);

  // A tab coming back to the foreground: try at once rather than waiting out
  // the backoff the player has been staring at.
  //
  // `connected` is NOT trusted here, and that is the case this listener exists
  // for. It used to return early on `connected`, which made it a no-op exactly
  // when iOS had killed the socket without firing `onclose`: the flag was a
  // stale `true`, the backoff loop (keyed on the flag) never started, and the
  // game sat frozen until a reload. The socket's own readyState is the truth.
  // A stale-true socket gets ONE direct attempt rather than the loop: the loop
  // is driven by `connected` changing, and if this attempt fails its socket's
  // `onclose` flips the flag and the loop takes over from there.
  const connectRef = useRef(connect);
  connectRef.current = connect;
  const readyRef = useRef(socketReady);
  readyRef.current = socketReady;
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || !enabled) return;
      if (connected) {
        const rs = readyRef.current();
        if (rs === 2 || rs === 3) connectRef.current();   // CLOSING/CLOSED behind a stale flag
        return;
      }
      tries.current = 0;
      attemptRef.current();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [connected, enabled]);
}
