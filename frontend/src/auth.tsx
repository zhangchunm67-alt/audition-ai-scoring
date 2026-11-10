import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { get, post, type S } from "./api/client";

type Me = S<"MeOut">;
type Ctx = {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (perm: string) => boolean;
};

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    get<Me>("/auth/me").then(setMe).catch(() => setMe(null)).finally(() => setLoading(false));
  }, []);
  const login = useCallback(async (username: string, password: string) => {
    setMe(await post<Me>("/auth/login", { username, password }));
  }, []);
  const logout = useCallback(async () => {
    await post("/auth/logout").catch(() => undefined);
    setMe(null);
  }, []);
  const refresh = useCallback(async () => {
    setMe(await get<Me>("/auth/me").catch(() => null));
  }, []);
  const can = useCallback((perm: string) => !!me?.permissions.includes(perm), [me]);
  return <AuthContext.Provider value={{ me, loading, login, logout, refresh, can }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Ctx {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 须在 AuthProvider 内使用");
  return ctx;
}
