const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function callBackend(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
}
