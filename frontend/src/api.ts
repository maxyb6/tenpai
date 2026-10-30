// Thin fetch wrapper. The console sends the chosen tenant, role and user as
// headers; the API scopes data from them (demo build, no production auth).

export type Ctx = { tenant: string; role: string; userId?: number };

let ctx: Ctx = { tenant: "mm-demo", role: "head_of_collections" };
export const setApiCtx = (c: Ctx) => (ctx = c);

function headers(extra?: HeadersInit): HeadersInit {
  return { "X-Role": ctx.role, ...(ctx.userId ? { "X-User-Id": String(ctx.userId) } : {}), ...extra };
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json();
}

export const t = (path: string) => `/api/t/${ctx.tenant}${path}`;

export const api = {
  get: <T,>(path: string) => fetch(t(path), { headers: headers() }).then(handle<T>),
  post: <T,>(path: string, body?: unknown) =>
    fetch(t(path), {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body ?? {}),
    }).then(handle<T>),
  put: <T,>(path: string, body?: unknown) =>
    fetch(t(path), {
      method: "PUT",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body ?? {}),
    }).then(handle<T>),
  upload: <T,>(path: string, form: FormData) =>
    fetch(t(path), { method: "POST", headers: headers(), body: form }).then(handle<T>),
  url: (path: string) => t(path),
};

export const mini = {
  get: <T,>(token: string, path = "") => fetch(`/api/mini/${token}${path}`).then(handle<T>),
  post: <T,>(token: string, path: string, body?: unknown) =>
    fetch(`/api/mini/${token}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }).then(handle<T>),
};
