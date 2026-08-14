import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api/client";
import type { User } from "./api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** Redirect the browser to ORCID to begin sign-in. */
  startOrcidLogin: () => Promise<void>;
  /** Complete sign-in after ORCID redirects back with a code. */
  finishOrcidLogin: (code: string) => Promise<void>;
  /** Dev-only: sign in as a seeded demo user by email (localhost testing). */
  devLogin: (email: string) => Promise<void>;
  /** Re-read the signed-in user. Call after changing a self-service setting
   *  (`PATCH /auth/me`) so the copy held here cannot drift from the server's —
   *  the record page seeds its licence picker from `user.default_license`, and
   *  a change made on the Dashboard has to reach it without a reload. */
  refreshUser: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState>(null!);

const STATE_KEY = "tbia_orcid_state";

function randomState(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Guards the OAuth `state` round-trip against CSRF. Throws on mismatch. */
export function consumeOrcidState(returned: string | null): void {
  const saved = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(STATE_KEY);
  if (!saved || !returned || saved !== returned) throw new Error("Invalid ORCID state");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) { setLoading(false); return; }
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);

  const startOrcidLogin = async () => {
    const cfg = await api.orcidConfig();
    const state = randomState();
    sessionStorage.setItem(STATE_KEY, state);
    const params = new URLSearchParams({
      client_id: cfg.client_id,
      response_type: "code",
      scope: cfg.scope,
      redirect_uri: cfg.redirect_uri,
      state,
    });
    window.location.assign(`${cfg.authorize_endpoint}?${params}`);
  };

  const finishOrcidLogin = async (code: string) => {
    const res = await api.orcidCallback(code);
    setToken(res.access_token);
    setUser(res.user);
  };

  const devLogin = async (email: string) => {
    const res = await api.devLogin(email);
    setToken(res.access_token);
    setUser(res.user);
  };

  const refreshUser = async () => {
    if (!getToken()) return;
    setUser(await api.me());
  };

  const logout = () => { setToken(null); setUser(null); };

  return (
    <AuthContext.Provider value={{ user, loading, startOrcidLogin, finishOrcidLogin, devLogin, refreshUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
