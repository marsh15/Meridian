import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useModalLifecycle } from '../hooks/useModalLifecycle'

function CloseIcon() {
  return (
    <svg viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M2 2l10 10M12 2L2 12"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

export default function AuthModal() {
  const { modal } = useAuth()
  if (!modal) return null
  return <AuthModalBody mode={modal} />
}

function AuthModalBody({ mode }) {
  const { closeAuth, openAuth, login, signup } = useAuth()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { closing, close } = useModalLifecycle(closeAuth)

  const isSignup = mode === 'signup'

  async function submit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    const form = new FormData(e.target)
    try {
      if (isSignup) {
        await signup({
          email: form.get('email'),
          password: form.get('password'),
          displayName: form.get('displayName'),
        })
      } else {
        await login({ email: form.get('email'), password: form.get('password') })
      }
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className={`modal-overlay ${closing ? 'closing' : ''}`} onClick={close}>
      <div
        className="modal card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={isSignup ? 'Create an account' : 'Sign in'}
      >
        <button className="modal-x" onClick={close} aria-label="Close">
          <CloseIcon />
        </button>

        <div
          className={`segmented auth-tabs sentence ${isSignup ? 'alt' : ''}`}
          role="group"
          aria-label="Authentication mode"
        >
          <span className="seg-thumb" aria-hidden="true" />
          <button className={!isSignup ? 'active' : ''} onClick={() => openAuth('login')}>
            Sign in
          </button>
          <button className={isSignup ? 'active' : ''} onClick={() => openAuth('signup')}>
            Create account
          </button>
        </div>

        <h2 className="modal-title">
          {isSignup ? 'Join Meridian' : 'Welcome back'}
        </h2>
        <p className="modal-sub">
          {isSignup
            ? 'Create an account — every trader starts with $1,000 in virtual funds.'
            : 'Sign in to trade, create markets, and track your positions.'}
        </p>

        <form onSubmit={submit} className="form">
          {isSignup && (
            <label className="field">
              <span>Display name</span>
              <input
                name="displayName"
                placeholder="How you appear on markets"
                maxLength={40}
                autoFocus
              />
            </label>
          )}
          <label className="field">
            <span>Email</span>
            <input
              name="email"
              type="email"
              placeholder="you@example.com"
              required
              autoFocus={!isSignup}
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              name="password"
              type="password"
              placeholder="At least 6 characters"
              required
              minLength={6}
            />
          </label>

          {error && <div className="form-error">{error}</div>}

          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy
              ? isSignup
                ? 'Creating account…'
                : 'Signing in…'
              : isSignup
                ? 'Create account'
                : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
