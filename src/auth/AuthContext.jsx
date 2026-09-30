import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)
  const [modal, setModal] = useState(null) // 'login' | 'signup' | null

  useEffect(() => {
    api.me()
      .then(({ user }) => setUser(user))
      .catch(() => setUser(null))
      .finally(() => setReady(true))
  }, [])

  const openAuth = useCallback((mode = 'login') => setModal(mode), [])
  const closeAuth = useCallback(() => setModal(null), [])

  const login = useCallback(async (body) => {
    const { user } = await api.login(body)
    setUser(user)
    setModal(null)
  }, [])

  const signup = useCallback(async (body) => {
    const { user } = await api.signup(body)
    setUser(user)
    setModal(null)
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
  }, [])

  const resetAccount = useCallback(async () => {
    const { user } = await api.resetAccount()
    setUser(user)
  }, [])

  /* fills and settlements change the balance server-side; sync it without
     refetching the whole session */
  const setBalanceCents = useCallback((balanceCents) => {
    setUser((u) => (u ? { ...u, balanceCents } : u))
  }, [])

  /* settlement credits arrive outside an order response — pull fresh state */
  const refreshUser = useCallback(async () => {
    try {
      const { user } = await api.me()
      setUser(user)
    } catch {
      /* keep whatever we had */
    }
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, ready, login, signup, logout, resetAccount, setBalanceCents, refreshUser, modal, openAuth, closeAuth }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
