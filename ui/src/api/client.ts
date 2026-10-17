export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string
  ) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';

export async function apiGet<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) {
        url.searchParams.set(k, String(v));
      }
    });
  }

  const res = await fetch(url.toString(), {
    headers: {
      Accept: 'application/json',
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      // fallback to status text
    }
    throw new ApiError(res.status, detail);
  }

  return res.json();
}

export async function apiPost<T, B = unknown>(path: string, body?: B): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      // fallback
    }
    throw new ApiError(res.status, detail);
  }

  return res.json();
}
