import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './neubrutalism.css'
import './professional.css'
import './interface-styles.css'

// Apply the saved interface style before the first paint (default: Professional).
try {
  const saved = window.localStorage.getItem('contexa_ui_style')
  const styles = ['minimal','retro','blak','clay','bento','editorial','terminal','neobrutalism']
  const legacy: Record<string,string> = { pro:'minimal', neo:'neobrutalism', minimalism:'minimal', vibrant:'bento', claymorphism:'clay', glassmorphism:'minimal', paper:'editorial', nordic:'minimal', cyber:'terminal', soft:'minimal', luxury:'editorial', playful:'clay' }
  document.documentElement.dataset.style = legacy[saved || ''] || (saved && styles.includes(saved) ? saved : 'minimal')
} catch { document.documentElement.dataset.style = 'minimal' }

createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
)
