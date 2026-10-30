export const apiBase = import.meta.env.VITE_API_BASE || ''

export async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  })
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`
    try { detail = (await response.json()).detail || detail } catch { /* keep HTTP status */ }
    throw Object.assign(new Error(detail), { status: response.status })
  }
  return response.status === 204 ? null : response.json()
}

export function wsUrl(path) {
  if (apiBase) return apiBase.replace(/^http/, 'ws') + path
  return `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${path}`
}
