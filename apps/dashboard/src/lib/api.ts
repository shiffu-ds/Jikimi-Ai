// Same-origin JSON client. Cookie session (httpOnly) + the custom header the API requires on
// cookie-authenticated writes (CSRF defence). Errors are RFC 9457 problem+json.

export class ApiError extends Error {
  constructor(
    public status: number,
    public title: string,
    public detail?: string | null,
  ) {
    super(detail ? `${title}: ${detail}` : title);
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? (init.body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "X-Jikimi-Client": "web",
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    signal: init.signal,
    cache: "no-store",
  });
  return parse<T>(res);
}

/** POST a binary body as is (a voice recording). */
export async function upload<T>(path: string, blob: Blob): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json", "X-Jikimi-Client": "web", "Content-Type": blob.type || "application/octet-stream" },
    body: blob,
    cache: "no-store",
  });
  return parse<T>(res);
}

async function parse<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, data?.title ?? res.statusText, data?.detail);
  }
  return data as T;
}

export function qs(params: Record<string, string | number | boolean | undefined | null | string[]>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
