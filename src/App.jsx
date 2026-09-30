import { useEffect } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import Header from './components/Header'
import TickerTape from './components/TickerTape'
import AuthModal from './components/AuthModal'
import Home from './pages/Home'
import MarketDetail from './pages/MarketDetail'

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

function Logo() {
  return (
    <span className="footer-logo">
      <span className="logo-mark" aria-hidden="true">
        <svg viewBox="0 0 14 14" fill="none">
          <path d="M1 7L7 1l6 6-6 6z" fill="currentColor" />
        </svg>
      </span>
      Meridian
    </span>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ScrollToTop />
        <Header />
        <TickerTape />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/market/:id" element={<MarketDetail />} />
          <Route path="*" element={<Home />} />
        </Routes>
        <footer className="site-footer">
          <div className="wrap footer-inner">
            <Logo />
            <div className="footer-note">
              <span>Prediction market demo — play money only</span>
              <span className="sep">·</span>
              <span>Not financial advice</span>
            </div>
          </div>
        </footer>
        <AuthModal />
      </BrowserRouter>
    </AuthProvider>
  )
}
