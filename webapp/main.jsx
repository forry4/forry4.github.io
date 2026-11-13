import React from 'react'
import { createRoot } from 'react-dom/client'
import SpenderApp from '../games/spender/Spender.jsx'
// Pages caches the bundle ~10 min, so a tab can outlive its deploy. Watches for a
// newer build and offers a refresh. Outside React on purpose: the shell early-returns
// each game's component, so there is no single tree the banner could live in.
import { startUpdateNudge } from '../shared/update-nudge.js'
// Registers the service worker (prod hosts only) so the site is installable to a
// phone home screen and opens offline. Fire-and-forget, outside React, after load.
import { startPwa } from '../shared/pwa.js'
// Is the server up? The first screen no longer waits to find out (see the boot effect
// in Spender.jsx), so the question is asked here, at load, by ONE /health probe that
// holds its request through a cold start; the notice says so on the screens that
// need the server. Plain DOM, outside React, for the same reason as the nudge.
import { startBackendProbe, startWakingNotice } from '../shared/backend.js'

startBackendProbe()

// The crash screen and its boundaries live in shared/CrashScreen.jsx: this root one is
// the last resort for a throw in the SHELL itself (each lazily loaded screen has its own
// boundary in Spender.jsx, so a crash inside one game leaves the way home intact). Both
// report through shared/crashReport.js, which also listens for uncaught errors and
// unhandled rejections — installed before the first render so a throw during it counts.
import { AppBoundary } from '../shared/CrashScreen.jsx'
import { installCrashReporting } from '../shared/crashReport.js'

installCrashReporting()

createRoot(document.getElementById('root')).render(
  React.createElement(React.StrictMode, null,
    React.createElement(AppBoundary, null,
      React.createElement(SpenderApp)
    )
  )
)

startUpdateNudge()
startPwa()
startWakingNotice()
