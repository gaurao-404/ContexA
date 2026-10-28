const API_URL = (import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/$/, '')
let token = localStorage.getItem('contexa_token') || ''
let unauthorizedHandler: (() => void) | undefined
export function setToken(next: string) { token = next; if (next) localStorage.setItem('contexa_token', next); else localStorage.removeItem('contexa_token') }
export function getToken() { return token }
export function onUnauthorized(handler: () => void) { unauthorizedHandler = handler }

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_URL}${path}`, { ...options, headers })
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') || ''
  if (!response.ok) {
    const body = contentType.includes('application/json') ? await response.json().catch(() => ({})) : {}
    if (response.status === 401 && path !== '/api/auth/login') { setToken(''); unauthorizedHandler?.() }
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  if (contentType.includes('application/json')) return response.json() as Promise<T>
  return response.blob() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; ai_configured: boolean; ai_model: string | null; database: string }>('/api/health'),
  login: (email: string, password: string) => request<{ access_token: string; user: import('./types').User }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request<import('./types').User>('/api/auth/me'),
  dashboard: () => request<import('./types').Dashboard>('/api/dashboard'),
  seedDemo: () => request<{ created_documents: number; documents: import('./types').DocumentRecord[]; ai_mode: string; notice: string }>('/api/demo/seed', { method: 'POST' }),
  checkCopy: (text: string) => request<{ mode: string; characters_checked: number; findings_count: number; findings: Array<{ rule_id: string | null; rule_code: string | null; rule_title: string; severity: 'critical' | 'warning' | 'info'; finding_type: string; flagged_text: string; reasoning: string; suggested_fix: string; source_document?: string | null }>; notice: string; local_ai?: { enabled: boolean; verification_enabled?: boolean; service_available: boolean; model_available: boolean; model: string; install_command: string; start_command: string } }>('/api/check-copy', { method: 'POST', body: JSON.stringify({ text }) }),
  documents: (q = '', status = 'all') => request<import('./types').DocumentRecord[]>(`/api/documents?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`),
  upload: (file: File) => { const body = new FormData(); body.append('file', file); return request<import('./types').DocumentRecord>('/api/documents/upload', { method: 'POST', body }) },
  document: (id: string) => request<import('./types').DocumentDetail>(`/api/documents/${id}`),
  actOnFinding: (id: string, status: string, note?: string, applied_text?: string) => request<{ finding: import('./types').Finding; publish_ready: boolean }>(`/api/findings/${id}/action`, { method: 'POST', body: JSON.stringify({ status, note, applied_text }) }),
  publish: (id: string, override_note?: string) => request<{ document: import('./types').DocumentRecord; message: string }>(`/api/documents/${id}/publish`, { method: 'POST', body: JSON.stringify({ override_note }) }),
  rescan: (id: string) => request<import('./types').DocumentRecord>(`/api/documents/${id}/rescan`, { method: 'POST' }),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: 'DELETE' }),
  rules: (q = '') => request<import('./types').Rule[]>(`/api/rules?q=${encodeURIComponent(q)}`),
  importGuideline: (file: File) => { const body = new FormData(); body.append('file', file); return request<{ source_document: string; created_rules: number; skipped_clauses: number; note: string }>('/api/guidelines/import', { method: 'POST', body }) },
  createRule: (rule: Partial<import('./types').Rule>) => request<import('./types').Rule>('/api/rules', { method: 'POST', body: JSON.stringify(rule) }),
  updateRule: (id: string, payload: Partial<import('./types').Rule>) => request<import('./types').Rule>(`/api/rules/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  insights: () => request<import('./types').InsightData>('/api/insights'),
  audit: (limit = 100) => request<import('./types').Activity[]>(`/api/audit?limit=${limit}`),
  settings: () => request<any>('/api/settings'),
  users: () => request<import('./types').User[]>('/api/users'),
  createUser: (payload: { name: string; email: string; password: string; role: string }) => request<import('./types').User>('/api/users', { method: 'POST', body: JSON.stringify(payload) }),
  preview: async (id: string, page: number) => request<Blob>(`/api/documents/${id}/preview/${page}`),
  exportReport: async (id: string, format: 'json' | 'csv') => request<Blob>(`/api/documents/${id}/export?fmt=${format}`),
}
