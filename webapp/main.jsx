import React from 'react'
import { createRoot } from 'react-dom/client'
import SpenderApp from '../games/spender/Spender.jsx'

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (this.state.err) {
      return React.createElement('div', {
        style: { padding: 32, fontFamily: 'monospace', color: '#e05555', background: '#0f0e0c', minHeight: '100vh' }
      },
        React.createElement('h2', null, 'App Error'),
        React.createElement('pre', { style: { whiteSpace: 'pre-wrap', fontSize: 13 } },
          String(this.state.err)
        )
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
