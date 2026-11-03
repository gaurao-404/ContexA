import { refreshSupabaseSession, supabaseAuthEnabled } from './supabaseAuth'

const API_URL = (import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/$/, '')
let token = localStorage.getItem('contexa_token') || ''
let unauthorizedHandler: (() => void) | undefined
export function setToken(next: string) { token = next; if (next) { localStorage.setItem('contexa_token', next); if (next.split('.').length !== 3) localStorage.removeItem('contexa_supabase_refresh_token') } else { localStorage.removeItem('contexa_token'); localStorage.removeItem('contexa_supabase_refresh_token') } }
export function setSupabaseSession(accessToken: string, refreshToken: string) { token = accessToken; localStorage.setItem('contexa_token', accessToken); localStorage.setItem('contexa_supabase_refresh_token', refreshToken) }
async function refreshSupabaseTokenIfNeeded() {
  const refreshToken = localStorage.getItem('contexa_supabase_refresh_token')
  if (!supabaseAuthEnabled || !refreshToken || token.split('.').length !== 3) return
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    if (Number(payload.exp || 0) * 1000 > Date.now() + 120000) return
    const session = await refreshSupabaseSession(refreshToken)
    setSupabaseSession(session.access_token, session.refresh_token)
  } catch (error) {
    setToken('')
    unauthorizedHandler?.()
    throw error instanceof Error ? error : new Error('Supabase session refresh failed.')
  }
}
export function getToken() { return token }
export function onUnauthorized(handler: () => void) { unauthorizedHandler = handler }

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const REQUEST_TIMEOUT_MS = 30_000

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  await refreshSupabaseTokenIfNeeded()
  const headers = new Headers(options.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const signal = options.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal
  try {
    let response: Response
    try {
      response = await fetch(`${API_URL}${path}`, { ...options, headers, signal })
    } catch (error) {
      if (controller.signal.aborted) throw new ApiError('The request timed out. Check the connection and try again.', 408)
      if (error instanceof TypeError) throw new ApiError('ContexA could not reach its API. Check the service status and your connection.', 0)
      throw error
    }
    if (response.status === 204) return undefined as T
    const contentType = response.headers.get('content-type') || ''
    if (!response.ok) {
      const body = contentType.includes('application/json') ? await response.json().catch(() => ({})) : {}
      if (response.status === 401 && path !== '/api/auth/login' && path !== '/api/auth/register') { setToken(''); unauthorizedHandler?.() }
      const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`
      throw new ApiError(detail, response.status)
    }
    if (contentType.includes('application/json')) return response.json() as Promise<T>
    return response.blob() as Promise<T>
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export const api = {
  health: () => request<{ status: string; ai_configured: boolean; ai_model: string | null; database: string }>('/api/health'),
  login: (email: string, password: string, turnstile_token?: string) => request<{ access_token: string; user: import('./types').User }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password, turnstile_token }) }),
  register: (payload: { name: string; email: string; password: string; workspace_name?: string; turnstile_token?: string }) => request<{ access_token?: string; user?: import('./types').User; verification_required?: boolean; message?: string; debug_link?: string }>('/api/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  verifyEmail: (token: string) => request<{ verified: boolean; message: string }>('/api/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) }),
  forgotPassword: (email: string) => request<{ message: string; debug_link?: string }>('/api/auth/password/forgot', { method: 'POST', body: JSON.stringify({ email }) }),
  resetPassword: (token: string, password: string) => request<{ reset: boolean; message: string }>('/api/auth/password/reset', { method: 'POST', body: JSON.stringify({ token, password }) }),
  createInvitation: (email: string, role: string) => request<any>('/api/invitations', { method: 'POST', body: JSON.stringify({ email, role }) }),
  acceptInvitation: (token: string, name: string, password: string) => request<{ access_token: string; user: import('./types').User }>('/api/invitations/accept', { method: 'POST', body: JSON.stringify({ token, name, password }) }),
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
  ruleVersions: (id: string) => request<any[]>(`/api/rules/${id}/versions`),
  importGuideline: (file: File) => { const body = new FormData(); body.append('file', file); return request<{ source_document: string; created_rules: number; skipped_clauses: number; note: string }>('/api/guidelines/import', { method: 'POST', body }) },
  createRule: (rule: Partial<import('./types').Rule>) => request<import('./types').Rule>('/api/rules', { method: 'POST', body: JSON.stringify(rule) }),
  updateRule: (id: string, payload: Partial<import('./types').Rule>) => request<import('./types').Rule>(`/api/rules/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  insights: () => request<import('./types').InsightData>('/api/insights'),
  brandIntelligence: () => request<any>('/api/brand-intelligence'),
  assets: () => request<any[]>('/api/assets'),
  downloadAsset: (id: string) => request<Blob>(`/api/assets/${id}/download`),
  searchGuidelines: (query: string) => request<any>('/api/retrieval/search', { method: 'POST', body: JSON.stringify({ query }) }),
  rebuildEmbeddings: () => request<any>('/api/admin/rebuild-embeddings', { method: 'POST' }),
  uploadAsset: (file: File, category: string, name?: string) => { const body = new FormData(); body.append('file', file); return request<any>(`/api/assets/upload?category=${encodeURIComponent(category)}&name=${encodeURIComponent(name || file.name.replace(/\.[^.]+$/, ''))}`, { method: 'POST', body }) },
  approveAsset: (id: string) => request<any>(`/api/assets/${id}/approve`, { method: 'POST' }),
  archiveAsset: (id: string) => request<any>(`/api/assets/${id}/archive`, { method: 'POST' }),
  facts: () => request<any[]>('/api/facts'),
  createFact: (payload: Record<string, unknown>) => request<any>('/api/facts', { method: 'POST', body: JSON.stringify(payload) }),
  approveFact: (id: string) => request<any>(`/api/facts/${id}/approve`, { method: 'POST' }),
  reviseFact: (id: string, payload: Record<string, unknown>) => request<any>(`/api/facts/${id}/revise`, { method: 'POST', body: JSON.stringify(payload) }),
  evidenceLedger: (limit = 20) => request<any[]>(`/api/evidence-ledger?limit=${limit}`),
  seedEvaluation: () => request<{ created: number; total: number }>('/api/evaluation/seed', { method: 'POST' }),
  importEvaluationCases: (file: File) => { const body = new FormData(); body.append('file', file); return request<{ created: number; updated: number; total: number; note: string }>('/api/evaluation/import', { method: 'POST', body }) },
  runEvaluation: () => request<any>('/api/evaluation/run', { method: 'POST' }),
  evaluationRuns: () => request<any[]>('/api/evaluation/runs'),
  simulatePolicy: (rule_id: string, proposed_pattern: string) => request<any>('/api/policy-simulations', { method: 'POST', body: JSON.stringify({ rule_id, proposed_pattern }) }),
  applyPolicySimulation: (id: string, change_note: string) => request<any>(`/api/policy-simulations/${id}/apply`, { method: 'POST', body: JSON.stringify({ change_note }) }),
  audit: (limit = 100) => request<import('./types').Activity[]>(`/api/audit?limit=${limit}`),
  verifyAudit: () => request<any>('/api/audit/verify'),
  // Round 4: collaboration, analytics and search
  notifications: (unreadOnly = false) => request<{ items: any[]; total: number; unread_count: number }>(`/api/notifications?unread_only=${unreadOnly}`),
  unreadCount: () => request<{ unread_count: number }>('/api/notifications/unread-count'),
  markNotificationRead: (id: string) => request<any>(`/api/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request<any>('/api/notifications/read-all', { method: 'POST' }),
  comments: (entity_type: 'document' | 'finding', entity_id: string) => request<{ threads: any[]; total: number; open_threads: number }>(`/api/comments?entity_type=${entity_type}&entity_id=${encodeURIComponent(entity_id)}`),
  addComment: (payload: { entity_type: 'document' | 'finding'; entity_id: string; body: string; parent_id?: string }) => request<any>('/api/comments', { method: 'POST', body: JSON.stringify(payload) }),
  updateComment: (id: string, payload: { body?: string; resolved?: boolean }) => request<any>(`/api/comments/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteComment: (id: string) => request<any>(`/api/comments/${id}`, { method: 'DELETE' }),
  authConfig: () => request<{ auth_mode: string; local_login: boolean; signup_open: boolean; email_verification_required: boolean; password_recovery: boolean; recovery_delivery: 'email' | 'development_link' | 'none'; demo_accounts: boolean }>('/api/auth/config'),
  complianceTrendCsv: (days = 30) => request<Blob>(`/api/analytics/trend?days=${days}&format=csv`),
  documentActivity: (id: string) => request<{ events: any[] }>(`/api/documents/${id}/activity`),
  complianceTrend: (days = 30) => request<{ series: any[]; summary: any }>(`/api/analytics/trend?days=${days}`),
  reviewWorkload: () => request<any>('/api/analytics/workload'),
  search: (q: string) => request<{ total: number; results: Record<string, any[]> }>(`/api/search?q=${encodeURIComponent(q)}`),
  settings: () => request<any>('/api/settings'),
  trustOSOverview: () => request<any>('/api/trust-os/overview'),
  truthSources: () => request<any[]>('/api/truth-drift/sources'),
  createTruthSource: (payload: Record<string, unknown>) => request<any>('/api/truth-drift/sources', { method: 'POST', body: JSON.stringify(payload) }),
  scanTruthSource: (id: string) => request<any>(`/api/truth-drift/sources/${id}/scan`, { method: 'POST' }),
  scanExpiredFacts: () => request<any>('/api/truth-drift/scan-expired-facts', { method: 'POST' }),
  truthDriftEvents: (status?: string) => request<any[]>(`/api/truth-drift/events${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  resolveDrift: (id: string) => request<any>(`/api/truth-drift/events/${id}/resolve`, { method: 'POST' }),
  passports: () => request<any[]>('/api/trust-passports'),
  issuePassport: (payload: Record<string, unknown>) => request<any>('/api/trust-passports', { method: 'POST', body: JSON.stringify(payload) }),
  revokePassport: (id: string) => request<any>(`/api/trust-passports/${id}/revoke`, { method: 'POST' }),
  publicPassport: (id: string) => request<any>(`/api/public/trust-passports/${encodeURIComponent(id)}`),
  passportQr: (id: string) => request<Blob>(`/api/trust-passports/${id}/qr.svg`),
  inspectMedia: (file: File, transcript_text = '') => { const body = new FormData(); body.append('file', file); body.append('transcript_text', transcript_text); return request<any>('/api/multimodal/inspect', { method: 'POST', body }) },
  mediaInspections: () => request<any[]>('/api/multimodal/inspections'),
  runAgents: (payload: Record<string, unknown>) => request<any>('/api/agents/runs', { method: 'POST', body: JSON.stringify(payload) }),
  agentRuns: () => request<any[]>('/api/agents/runs'),
  simulateTwin: (payload: Record<string, unknown>) => request<any>('/api/digital-twin/simulate', { method: 'POST', body: JSON.stringify(payload) }),
  twinScenarios: () => request<any[]>('/api/digital-twin/scenarios'),
  reviewIndic: (payload: Record<string, unknown>) => request<any>('/api/indic/review', { method: 'POST', body: JSON.stringify(payload) }),
  indicReviews: () => request<any[]>('/api/indic/reviews'),
  regulatoryRequirements: () => request<any[]>('/api/regulatory/requirements'),
  assessRegulatory: (payload: { document_id?: string; content_text?: string }) => request<any>('/api/regulatory/assess', { method: 'POST', body: JSON.stringify(payload) }),
  regulatoryAssessments: () => request<any[]>('/api/regulatory/assessments'),
  incidents: (status?: string) => request<any[]>(`/api/incidents${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  createIncident: (payload: Record<string, unknown>) => request<any>('/api/incidents', { method: 'POST', body: JSON.stringify(payload) }),
  updateIncident: (id: string, payload: Record<string, unknown>) => request<any>(`/api/incidents/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  foundationStatus: () => request<any>('/api/foundation/status'),
  trustGraph: () => request<{ nodes: any[]; edges: any[] }>('/api/foundation/graph'),
  rebuildTrustGraph: () => request<any>('/api/foundation/graph/rebuild', { method: 'POST' }),
  decisionTraces: () => request<any[]>('/api/foundation/decision-traces'),
  replayDecisionTrace: (id: string) => request<any>(`/api/foundation/decision-traces/${id}/replay`),
  evidenceArchives: () => request<any[]>('/api/foundation/evidence-archives'),
  auditAnchors: () => request<any[]>('/api/foundation/audit/anchors'),
  createAuditAnchor: () => request<any>('/api/foundation/audit/anchors', { method: 'POST' }),
  verifyAuditAnchor: (id: string) => request<any>(`/api/foundation/audit/anchors/${encodeURIComponent(id)}/verify`),
  exportWorkspace: () => request<Blob>('/api/workspace/export'),
  deleteWorkspace: (password: string, workspace_name_confirmation: string) => request<void>('/api/workspace', { method: 'DELETE', body: JSON.stringify({ password, workspace_name_confirmation }) }),
  users: () => request<import('./types').User[]>('/api/users'),
  createUser: (payload: { name: string; email: string; password: string; role: string }) => request<import('./types').User>('/api/users', { method: 'POST', body: JSON.stringify(payload) }),
  preview: async (id: string, page: number) => request<Blob>(`/api/documents/${id}/preview/${page}`),
  exportReport: async (id: string, format: 'json' | 'csv') => request<Blob>(`/api/documents/${id}/export?fmt=${format}`),
}
