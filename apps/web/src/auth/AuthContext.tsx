"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import type { User } from "@meridian/contracts";

type AuthMode = "login" | "signup";

interface AuthValue {
  user: User | null;
  ready: boolean;
  login: (body: object) => Promise<void>;
  signup: (body: object) => Promise<void>;
  logout: () => Promise<void>;
  resetAccount: () => Promise<void>;
  setBalanceCents: (balanceCents: number) => void;
  refreshUser: () => Promise<void>;
  modal: AuthMode | null;
  openAuth: (mode?: AuthMode) => void;
  closeAuth: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [modal, setModal] = useState<AuthMode | null>(null);

  useEffect(() => {
    api
      .me()
      .then(({ user }) => setUser(user))
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, []);

  const openAuth = useCallback((mode: AuthMode = "login") => setModal(mode), []);
  const closeAuth = useCallback(() => setModal(null), []);

  const login = useCallback(async (body: object) => {
    const { user } = await api.login(body);
    setUser(user);
    setModal(null);
  }, []);

  const signup = useCallback(async (body: object) => {
    const { user } = await api.signup(body);
    setUser(user);
    setModal(null);
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  const resetAccount = useCallback(async () => {
    const { user } = await api.resetAccount();
    setUser(user);
  }, []);

  /* fills and settlements change the balance server-side; sync it without
     refetching the whole session */
  const setBalanceCents = useCallback((balanceCents: number) => {
    setUser((u) => (u ? { ...u, balanceCents } : u));
  }, []);

  /* settlement credits arrive outside an order response — pull fresh state */
  const refreshUser = useCallback(async () => {
    try {
      const { user } = await api.me();
      setUser(user);
    } catch {
      /* keep whatever we had */
    }
  }, []);

  const value = useMemo(
    () => ({
      user, ready, login, signup, logout, resetAccount,
      setBalanceCents, refreshUser, modal, openAuth, closeAuth,
    }),
    [user, ready, login, signup, logout, resetAccount, setBalanceCents, refreshUser, modal, openAuth, closeAuth],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
