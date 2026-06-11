import React from 'react'
import { createRoot } from 'react-dom/client'
import SpenderApp from '../Spender.jsx'

createRoot(document.getElementById('root')).render(
  React.createElement(React.StrictMode, null, React.createElement(SpenderApp))
)
