import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { PublicView } from './pages/PublicView'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {location.pathname.startsWith('/view') ? <PublicView /> : <App />}
  </StrictMode>,
)
