// The API is served from the same origin (Caddy in production, Vite proxy in development),
// so the httpOnly session cookie travels automatically.
const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => {
  onUnauthorized = fn;
};

function messageFrom(body, status) {
  if (!body) return `Request failed (${status}).`;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return `Request failed (${status}).`;
}

export async function request(method, path, body, { raw = false } = {}) {
  const headers = {};
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}/api${path}`, { method, headers, body: payload, credentials: "include" });
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized();
  if (raw) {
    if (!res.ok) throw new Error(messageFrom(await res.json().catch(() => null), res.status));
    return res;
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(messageFrom(data, res.status));
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  put: (p, b) => request("PUT", p, b),
  patch: (p, b) => request("PATCH", p, b),
  del: (p) => request("DELETE", p),
  upload: (p, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("POST", p, fd);
  },
  download: async (p, filename) => {
    const res = await request("GET", p, undefined, { raw: true });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};

export const apiBase = BASE;
