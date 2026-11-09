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

// The last-resort screen when a render throws. It used to be the error text and
// NOTHING ELSE: no way to try again and no way out, on a site where every game is
// one lazily-loaded component, so a throw inside any one of them stranded the player
// on a red stack trace until they thought to edit the URL. A game is server-side
// state, so Reload resumes it; "Back to the menu" is for a screen that throws again.
// Inline styles and system fonts on purpose: this renders when the app itself is
// what failed, so it can rely on no stylesheet and no loaded web font.
const errBtn = {
  cursor: 'pointer', padding: '9px 16px', borderRadius: 8, border: '1px solid #e8c96a',
  font: '600 15px/1 Georgia, serif', textDecoration: 'none', display: 'inline-block',
};

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) {
    // Keep the component stack in the console: the screen shows only the message.
    console.error('[app] render failed', err, info && info.componentStack);
  }
  render() {
    if (this.state.err) {
      const base = (import.meta.env && import.meta.env.BASE_URL) || '/';
      return React.createElement('div', {
        role: 'alert',
        style: { padding: 32, color: '#f3e9d2', background: '#0f0e0c', minHeight: '100vh',
                 boxSizing: 'border-box', font: '16px/1.5 Georgia, serif' }
      },
        React.createElement('h2', { style: { margin: '0 0 8px' } }, 'Something went wrong'),
        React.createElement('p', { style: { margin: '0 0 18px', maxWidth: '36em' } },
          'This page hit an error. Reloading usually fixes it, and a game in progress is saved.'),
        React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 } },
          React.createElement('button', {
            type: 'button', onClick: () => window.location.reload(),
            style: { ...errBtn, background: '#e8c96a', color: '#2a1c20' },
          }, 'Reload'),
          React.createElement('a', {
            href: base, style: { ...errBtn, background: 'transparent', color: '#f3e9d2' },
          }, 'Back to the menu')
        ),
        React.createElement('pre', {
          style: { whiteSpace: 'pre-wrap', fontSize: 13, fontFamily: 'monospace', color: '#e05555', margin: 0 }
        }, String(this.state.err))
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')).render(
  React.createElement(React.StrictMode, null,
    React.createElement(ErrorBoundary, null,
      React.createElement(SpenderApp)
    )
  )
)

startUpdateNudge()
startPwa()
