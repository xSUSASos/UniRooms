async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const res = await fetch(url, init)
  if (!res.ok) {
    let message = `Ошибка ${res.status}`
    try {
      const data = await res.json()
      const d = data.detail
      if (typeof d === 'string') message = d
      else if (d?.errors) message = d.errors.join('\n')
      else if (Array.isArray(d)) message = d.map((e: { loc?: string[]; msg: string }) => `${e.loc?.slice(-1)[0] ?? ''}: ${e.msg}`).join('\n')
    } catch {
      /* not json */
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
}
