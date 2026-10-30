import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setApiCtx } from "./api";
import { setTenantTz } from "./format";

export type Meta = {
  tenant: {
    id: string;
    name: string;
    market: string;
    is_demo: boolean;
    brand: Record<string, any>;
    timezone: string;
    reporting_currency: string;
    fx: Record<string, number>;
    now: string;
    today: string;
    policy_version: number;
    data_region: string;
  };
  user: { id: number; name: string; role: string; branch_id: number | null; officer_id: number | null } | null;
  users: { id: number; name: string; role: string; branch_id: number | null; officer_id: number | null }[];
  branches: { id: number; name: string; name_local: string }[];
  officers: { id: number; name: string; branch_id: number }[];
};

type AppState = {
  tenant: string;
  role: string;
  userId?: number;
  meta?: Meta;
  version: number; // bump to make pages refetch after demo actions
  setTenant: (t: string) => void;
  setRole: (role: string, userId?: number) => void;
  refresh: () => void;
};

const Ctx = createContext<AppState | null>(null);

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [tenant, setTenantState] = useState<string>(() => load("tenant", "mm-demo"));
  const [role, setRoleState] = useState<string>(() => load("role", "head_of_collections"));
  const [userId, setUserId] = useState<number | undefined>(() => load("userId", undefined));
  const [meta, setMeta] = useState<Meta>();
  const [version, setVersion] = useState(0);

  setApiCtx({ tenant, role, userId });

  useEffect(() => {
    setApiCtx({ tenant, role, userId });
    api
      .get<Meta>("/meta")
      .then((m) => {
        setTenantTz(m.tenant.timezone);
        setMeta(m);
      })
      .catch(() => setMeta(undefined));
  }, [tenant, role, userId, version]);

  const setTenant = useCallback((t: string) => {
    setTenantState(t);
    setUserId(undefined);
    save("tenant", t);
    save("userId", null);
  }, []);
  const setRole = useCallback((r: string, u?: number) => {
    setRoleState(r);
    setUserId(u);
    save("role", r);
    save("userId", u ?? null);
  }, []);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return (
    <Ctx.Provider value={{ tenant, role, userId, meta, version, setTenant, setRole, refresh }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  const c = useContext(Ctx);
  if (!c) throw new Error("AppProvider missing");
  return c;
}

export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const { version, tenant, role, userId } = useApp();
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    if (!path) return;
    setLoading(true);
    api
      .get<T>(path)
      .then((d) => {
        setData(d);
        setError(undefined);
      })
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, version, tenant, role, userId, ...deps]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}
