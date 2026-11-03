const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY || ''
const AUTH_MODE = (import.meta.env.VITE_AUTH_MODE || 'local').toLowerCase()

export const supabaseAuthEnabled = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY && ['hybrid', 'supabase'].includes(AUTH_MODE))
export const supabaseAuthMode = AUTH_MODE === 'supabase' ? 'supabase' : AUTH_MODE === 'hybrid' ? 'hybrid' : 'local'

export type SupabaseSession = {
  access_token: string
  refresh_token: string
  expires_in?: number
  expires_at?: number
}

export async function signInSupabasePassword(email: string, password: string): Promise<SupabaseSession> {
  if (!supabaseAuthEnabled) throw new Error('Supabase Auth is not configured in this frontend build.')
  const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: SUPABASE_ANON_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.msg || body.message || body.error_description || 'Supabase sign-in failed.')
  if (!body.access_token || !body.refresh_token) throw new Error('Supabase did not return a complete session.')
  return body as SupabaseSession
}

export async function refreshSupabaseSession(refreshToken: string): Promise<SupabaseSession> {
  if (!supabaseAuthEnabled) throw new Error('Supabase Auth is not configured.')
  const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
    method: 'POST',
    headers: { apikey: SUPABASE_ANON_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.msg || body.message || 'Supabase session refresh failed.')
  return body as SupabaseSession
}

export async function signOutSupabaseSession(accessToken: string): Promise<void> {
  if (!supabaseAuthEnabled || !accessToken || accessToken.split('.').length !== 3) return
  try {
    await fetch(`${SUPABASE_URL}/auth/v1/logout`, {
      method: 'POST',
      headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${accessToken}` },
    })
  } catch { /* Local token removal still occurs; provider revocation can be retried by the user. */ }
}


export async function requestSupabasePasswordRecovery(email: string): Promise<void> {
  if (!supabaseAuthEnabled) throw new Error('Supabase Auth is not configured.')
  const redirectTo = window.location.origin
  const response = await fetch(`${SUPABASE_URL}/auth/v1/recover?redirect_to=${encodeURIComponent(redirectTo)}`, {
    method: 'POST',
    headers: { apikey: SUPABASE_ANON_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email.trim().toLowerCase() }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.msg || body.message || 'Password recovery could not be requested.')
  }
}

export async function updateSupabasePassword(accessToken: string, password: string): Promise<void> {
  if (!supabaseAuthEnabled || !accessToken) throw new Error('The Supabase recovery session is missing or expired. Request a new recovery link.')
  const response = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    method: 'PUT',
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.msg || body.message || 'Password update failed. Request a new recovery link.')
  }
}
