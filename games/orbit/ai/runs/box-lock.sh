#!/usr/bin/env bash
# MUTUAL EXCLUSION FOR THE BOX. Source this; call `claim_box`.
#
# WHY THIS EXISTS, and it is a lesson paid for twice. Every run script in this
# campaign waits for an idle box by polling for a `neural_arena` process. That
# guard was already hardened once, because the gap between two pools of ONE run
# is ten to fifteen seconds and a 60-second poll lands inside it often enough to
# matter. The hardened version requires several CONSECUTIVE idle polls, which
# fixes that case completely.
#
# It does nothing at all for the case that actually happened on 2026-09-13:
#
#   extension:    "box free after 12m"  at 05:12:29
#   serving run:  "box free after  4m"  at 05:12:12
#
# TWO scripts were waiting simultaneously, both observed the same genuinely idle
# box, and both started. No amount of consecutive-idle polling can prevent that,
# because nothing either script observes is different from a box that is about
# to stay free. The measured cost: alpha-beta's mean search depth fell from 6.51
# to 6.21 across otherwise identical pools, because an equal-time arena does not
# slow under contention, it silently loses the work each decision gets done.
#
# Polling observes; it cannot RESERVE. So the fix is a lock, and the lock must
# be atomic: `set -o noclobber` makes `>` fail rather than truncate when the file
# already exists, and that test-and-create is a single filesystem operation, so
# two scripts racing for it cannot both win.
#
# The lock is also STALE-SAFE. A killed run (this campaign has killed several by
# PID) would otherwise leave a lock nothing can clear, and the next unattended
# run would wait out its timeout and abort having measured nothing -- trading a
# contention bug for a silence bug. A lock whose recorded PID is gone is taken.
# THE LOCK MUST BE MACHINE-GLOBAL, NOT WORKTREE-RELATIVE. It serialises one
# physical box. This default was a path relative to the repo, which worked
# only while every run launched from the same worktree. When the AI campaign
# moved to its own worktree (2026-09-13, after a branch switch in the shared
# tree killed search-pending mid-flight) a relative path would have given each
# worktree its OWN lock -- so two runs would each hold "the box" and contend,
# reintroducing the exact race this file exists to remove, in a form no single
# script could observe.
BOX_LOCK="${BOX_LOCK:-$HOME/.orbit-box-lock}"

_lock_holder_alive() {
  local pid
  pid=$(head -1 "$BOX_LOCK" 2>/dev/null | tr -d '
')
  [ -n "$pid" ] || return 1
  # `kill -0`, NOT PowerShell's Get-Process. Under MSYS, `$$` is the MSYS
  # process id and Windows knows nothing about it, so a Get-Process check reads
  # every LIVE holder as dead -- which would clear a valid lock and hand the box
  # to a second run, the exact failure this file exists to prevent. Caught by
  # the three-way liveness test rather than in production.
  kill -0 "$pid" 2>/dev/null
}

arena_running() {
  powershell.exe -NoProfile -Command \
    "if (Get-Process -Name neural_arena -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }" \
    2>/dev/null | tr -d '\r' | grep -q yes
}

# claim_box <label> [minutes]
claim_box() {
  local label="$1"
  local limit="${2:-420}"
  local waited=0
  mkdir -p "$(dirname "$BOX_LOCK")"
  while :; do
    if (set -o noclobber; printf '%s\n%s\n%s\n' "$$" "$label" "$(date)" > "$BOX_LOCK") 2>/dev/null; then
      # The lock is ours. An arena may still be winding down from a run that
      # exited without releasing, so confirm the box really is quiet before
      # returning -- the lock prevents a RACE, not a leftover process.
      local idle=0
      while :; do
        if arena_running; then idle=0; else idle=$((idle + 1)); fi
        [ "$idle" -ge 3 ] && break
        sleep 20
        waited=$((waited + 1))
        [ "$waited" -ge $((limit * 3)) ] && { release_box; return 1; }
      done
      trap release_box EXIT INT TERM
      echo "[$(date '+%H:%M:%S')] box claimed by $label after ${waited}0s"
      return 0
    fi
    if ! _lock_holder_alive; then
      echo "[$(date '+%H:%M:%S')] clearing a stale lock (holder is gone)"
      rm -f "$BOX_LOCK"
      continue
    fi
    sleep 20
    waited=$((waited + 1))
    if [ "$waited" -ge $((limit * 3)) ]; then
      echo "[$(date '+%H:%M:%S')] ABORT: the box was held for over ${limit} minutes"
      return 1
    fi
  done
}

release_box() {
  # Only ever release OUR lock. A script that cleared someone else's on exit
  # would reintroduce exactly the race this file exists to remove.
  if [ -f "$BOX_LOCK" ] && [ "$(head -1 "$BOX_LOCK" 2>/dev/null | tr -d '\r')" = "$$" ]; then
    rm -f "$BOX_LOCK"
  fi
}
