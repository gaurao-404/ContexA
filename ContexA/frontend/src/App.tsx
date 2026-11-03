import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ChangeEvent, type ReactNode, type CSSProperties } from 'react'
import {
  Activity, AlertCircle, AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, BadgeCheck,
  BarChart3, Bell, BookOpenText, BriefcaseBusiness, Check, CheckCircle2, ChevronDown, ChevronLeft,
  ChevronRight, CircleHelp, ClipboardCheck, Clock3, Command, Download, Eye, FileCheck2, FileClock,
  FileImage, FileText, Filter, Fingerprint, FolderOpen, Gauge, History, Info, LayoutDashboard, LifeBuoy,
  LockKeyhole, LogOut, MoreHorizontal, PanelLeftClose, Plus, RefreshCw, Search, Settings2, Shield, Copy, ExternalLink, Terminal, Cpu, Palette, Menu,
  ShieldCheck, SlidersHorizontal, Sparkles, UploadCloud, Users, X, XCircle, Zap, Trash2, type LucideIcon,
} from 'lucide-react'
import { api, ApiError, getToken, onUnauthorized, setToken, setSupabaseSession } from './api'
import type { Activity as ActivityItem, Dashboard, DocumentDetail, DocumentRecord, Finding, InsightData, Role, Rule, User } from './types'
import GovernanceScene3D from './GovernanceScene3D'
import { NotificationBell, DiscussionPanel, ComplianceTrendPanel } from './Collaboration'
import TrustOSPage, { PublicPassportPage } from './TrustOSPage'
import TrustFoundationPage from './TrustFoundationPage'
import { requestSupabasePasswordRecovery, signInSupabasePassword, signOutSupabaseSession, supabaseAuthEnabled, supabaseAuthMode, updateSupabasePassword } from './supabaseAuth'

 type RuleDraft = { code: string; title: string; category: string; rule_clause: string; source_document: string; pattern: string; severity: 'critical' | 'warning' | 'info'; suggested_fix: string; is_active: boolean }
type View = 'dashboard' | 'library' | 'review' | 'rules' | 'insights' | 'trustos' | 'foundation' | 'audit' | 'team' | 'settings'
type MotionLevel = 'calm' | 'studio' | 'cinematic'
type UiStyle = 'minimal' | 'retro' | 'blak' | 'clay' | 'bento' | 'editorial' | 'terminal' | 'neobrutalism'

type StyleOption = { id: UiStyle; name: string; description: string; swatch: string[] }

const UI_STYLES: StyleOption[] = [
  { id: 'minimal', name: 'Minimal', description: 'Flat light surfaces, hairline rules and quiet, precise spacing.', swatch: ['#fafaf9', '#e7e5e4', '#18181b'] },
  { id: 'retro', name: 'Retro', description: 'Warm paper, ink borders, serif headings and a print-era feel.', swatch: ['#f3e7cf', '#3f3122', '#b4531a'] },
  { id: 'blak', name: 'Blak', description: 'True black, square edges, mono labels and one sharp signal colour.', swatch: ['#000000', '#171717', '#c8f542'] },
  { id: 'clay', name: 'Clay', description: 'Soft lavender forms with inflated tactile shadows and large radii.', swatch: ['#efe7fb', '#7b5bd6', '#ff9ec7'] },
  { id: 'bento', name: 'Bento', description: 'A modular card grid with strong metrics and dashboard structure.', swatch: ['#f4f4f5', '#ffffff', '#245ed6'] },
  { id: 'editorial', name: 'Editorial', description: 'Ivory page, serif display type, rules and magazine-like hierarchy.', swatch: ['#fbf7ef', '#221d1a', '#9f1239'] },
  { id: 'terminal', name: 'Terminal', description: 'Console-dark workspace with monospace type and green signals.', swatch: ['#07100a', '#0f1d13', '#4ade80'] },
  { id: 'neobrutalism', name: 'Neo-Brutalism', description: 'Thick black outlines, hard offset shadows and graphic flat colour.', swatch: ['#ffd93d', '#111111', '#ff7ab6'] },
]

const DEFAULT_STYLE: UiStyle = 'minimal'
const STYLE_IDS = UI_STYLES.map(option => option.id)
const LEGACY_STYLE_MAP: Record<string, UiStyle> = {
  pro: 'minimal', neo: 'neobrutalism', minimalism: 'minimal', vibrant: 'bento',
  claymorphism: 'clay', glassmorphism: 'minimal', paper: 'editorial', nordic: 'minimal',
  cyber: 'terminal', soft: 'minimal', luxury: 'editorial', playful: 'clay',
}

function readUiStyle(): UiStyle {
  try {
    const saved = window.localStorage.getItem('contexa_ui_style') || ''
    return LEGACY_STYLE_MAP[saved] || (STYLE_IDS.includes(saved as UiStyle) ? saved as UiStyle : DEFAULT_STYLE)
  } catch { return DEFAULT_STYLE }
}

function StyleToggle({ value, onChange }: { value: UiStyle; onChange: (style: UiStyle) => void }) {
  return <div className="style-toggle" role="group" aria-label="Interface style"><span>Style</span>{UI_STYLES.map(option => <button key={option.id} type="button" aria-pressed={value === option.id} className={value === option.id ? 'is-active' : ''} onClick={() => onChange(option.id)}>{option.name}</button>)}</div>
}

type ApiHealthState = 'checking' | 'ready' | 'degraded' | 'offline'

const NAV: { id: View; label: string; icon: LucideIcon; group: string }[] = [
  { id: 'dashboard', label: 'Home', icon: LayoutDashboard, group: 'WORKSPACE' },
  { id: 'library', label: 'Content', icon: FolderOpen, group: 'WORKSPACE' },
  { id: 'review', label: 'Review', icon: ClipboardCheck, group: 'WORKSPACE' },
  { id: 'rules', label: 'Rules', icon: BookOpenText, group: 'GOVERNANCE' },
  { id: 'insights', label: 'Insights', icon: BarChart3, group: 'GOVERNANCE' },
  { id: 'trustos', label: 'Trust OS', icon: ShieldCheck, group: 'GOVERNANCE' },
  { id: 'foundation', label: 'Trust Foundation', icon: Fingerprint, group: 'GOVERNANCE' },
  { id: 'audit', label: 'Audit', icon: Fingerprint, group: 'GOVERNANCE' },
  { id: 'team', label: 'Team', icon: Users, group: 'ADMIN' },
  { id: 'settings', label: 'Settings', icon: Settings2, group: 'ADMIN' },
]

const ROLE_CREDENTIALS: { label: string; email: string; password: string; role: string }[] = [
  { label: 'Brand Admin', email: 'admin@contexa.local', password: 'ContexA!2026', role: 'Full access' },
  { label: 'Manager', email: 'manager@contexa.local', password: 'Manager!2026', role: 'Sign-off' },
  { label: 'SME / Legal', email: 'legal@contexa.local', password: 'Legal!2026', role: 'Legal review' },
  { label: 'Creator', email: 'creator@contexa.local', password: 'Creator!2026', role: 'Submit & review' },
]

function prettyDate(input?: string) {
  if (!input) return '—'
  const d = new Date(input)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}
function timeAgo(input?: string) {
  if (!input) return '—'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(input).getTime()) / 1000))
  if (seconds < 60) return 'Just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`
  return prettyDate(input)
}
function bytesLabel(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
function statusLabel(status: string) {
  return ({ IN_REVIEW: 'In review', READY_FOR_SIGNOFF: 'Ready for sign-off', PUBLISH_READY: 'Publish ready' } as Record<string, string>)[status] || status.replaceAll('_', ' ')
}
function actionLabel(action: string) { return action.replaceAll('.', ' ').replaceAll('_', ' ') }
function initials(name = '') { return name.trim().split(/\s+/).slice(0, 2).map((v) => v[0]).join('').toUpperCase() || 'C' }
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function BrandMark({ compact = false }: { compact?: boolean }) {
  return <div className={`brand-mark ${compact ? 'brand-mark-compact' : ''}`} aria-label="ContexA">
    <svg className="brand-symbol solid-brand-symbol" viewBox="0 0 40 40" role="img" aria-label="ContexA monogram">
      <rect x="1" y="1" width="38" height="38" rx="10" fill="#e6c989" stroke="#fff0cc" strokeWidth="1.2" />
      <text x="20" y="26" textAnchor="middle" fontFamily="Manrope, Arial, sans-serif" fontSize="16.5" fontWeight="900" letterSpacing="-1.1" textLength="27" lengthAdjust="spacingAndGlyphs" fill="#171521">CA</text>
    </svg>
    {!compact && <span className="brand-word">Contex<span>A</span></span>}
  </div>
}

function Toast({ toast, onClose }: { toast: { kind: 'success' | 'error' | 'info'; message: string } | null; onClose: () => void }) {
  if (!toast) return null
  const Icon = toast.kind === 'success' ? CheckCircle2 : toast.kind === 'error' ? AlertCircle : Info
  return <div className={`toast toast-${toast.kind}`} role="status"><Icon size={17} /><span>{toast.message}</span><button className="icon-button toast-close" onClick={onClose} aria-label="Close notification"><X size={14} /></button></div>
}

/** Renders document text with every open finding's flagged passage marked, coloured by severity. */
function MarkedText({ text, findings, selectedId, onSelect }: { text: string; findings: Finding[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const spans: { start: number; end: number; finding: Finding }[] = []
  for (const finding of findings) {
    const needle = (finding.flagged_text || '').trim()
    if (finding.status !== 'open' || needle.length < 3) continue
    let from = 0
    for (let guard = 0; guard < 20; guard++) {
      const at = text.indexOf(needle, from)
      if (at < 0) break
      spans.push({ start: at, end: at + needle.length, finding }); from = at + needle.length
    }
  }
  spans.sort((a, b) => a.start - b.start || b.end - a.end)
  const parts: ReactNode[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start < cursor) continue // overlapping flags: the earlier/longer one wins
    if (span.start > cursor) parts.push(text.slice(cursor, span.start))
    const f = span.finding
    parts.push(<mark key={`${f.id}-${span.start}`} className={`${f.severity === 'critical' ? 'mark-risk' : f.severity === 'info' ? 'mark-price' : ''} ${selectedId === f.id ? 'mark-selected' : ''}`} title={`${f.rule_code || 'Finding'} · ${f.severity}`} onClick={() => onSelect(f.id)} style={{ cursor: 'pointer' }}>{text.slice(span.start, span.end)}</mark>)
    cursor = span.end
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

function LoginProof() {
  return <figure className="login-proof pro-only" aria-label="Illustrative example of a review">
    <div className="proof-doc">
      <div className="proof-meta"><span>Spring_launch_email.docx</span><span>Page 1 · 3 findings</span></div>
      <p className="proof-text">Meet the <mark className="mark-risk">#1 fastest platform</mark> in its class. Teams grow revenue by <mark className="mark-risk">up to 400%</mark> in a quarter, starting at <mark className="mark-price">$19/month</mark>.</p>
      <ol className="proof-notes">
        <li><span className="proof-code">CLM-204</span><span>Ranking claim needs substantiation on file before it can be published.</span></li>
        <li><span className="proof-code">LGL-002</span><span>Quantified outcome requires the approved disclaimer.</span></li>
        <li><span className="proof-code">FACT-PRICE</span><span>Price differs from the approved price book.</span></li>
      </ol>
    </div>
    <figcaption className="proof-caption">Illustrative example. Every flag cites the rule or fact behind it.</figcaption>
  </figure>
}

function LedgerStrip({ dashboard, onNavigate }: { dashboard: Dashboard | null; onNavigate: (view: View) => void }) {
  const total = dashboard?.total_documents ?? 0, inReview = dashboard?.in_review ?? 0, critical = dashboard?.critical_findings ?? 0, ready = dashboard?.publish_ready ?? 0
  return <section className="ledger-strip pro-only-block" aria-label="Workspace status">
    <div>
      {total === 0
        ? <p className="ledger-sentence">Nothing has been submitted yet. Upload a draft and ContexA will check it against your rules.</p>
        : <p className="ledger-sentence"><b>{inReview}</b> {inReview === 1 ? 'document is' : 'documents are'} in review{critical > 0 ? <>, with <b className="is-risk">{critical} critical {critical === 1 ? 'finding' : 'findings'}</b> waiting for an accountable reviewer</> : ' and nothing critical is open'}. <b className="is-ok">{ready}</b> {ready === 1 ? 'is' : 'are'} approved for publication.</p>}
      <p className="ledger-sub">Every decision is recorded in a tamper-evident audit trail.</p>
    </div>
    <div className="ledger-actions"><button className="btn btn-secondary" onClick={() => onNavigate('library')}>Content library</button>{critical > 0 && <button className="btn btn-primary" onClick={() => onNavigate('review')}>Review queue</button>}</div>
  </section>
}

function WorkspaceArrival({ onComplete, motionLevel }: { onComplete: () => void; motionLevel: MotionLevel }) {
  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = window.setTimeout(onComplete, reduced ? 80 : 1900)
    return () => window.clearTimeout(timer)
  }, [onComplete])
  return <div className="workspace-arrival" role="status" aria-label="Opening ContexA workspace">
    <div className="arrival-grid" />
    <div className="arrival-halo arrival-halo-a" /><div className="arrival-halo arrival-halo-b" />
    <div className="arrival-orbit arrival-orbit-a" /><div className="arrival-orbit arrival-orbit-b" /><div className="arrival-orbit arrival-orbit-c" />
    <div className="arrival-scene"><GovernanceScene3D score={100} motionLevel={motionLevel === 'calm' ? 'studio' : motionLevel} /></div>
    <div className="arrival-lockup"><BrandMark /><span className="arrival-ready"><i /> WORKSPACE READY</span></div>
    <div className="arrival-progress"><span /></div>
  </div>
}

declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: { sitekey: string; action?: string; callback: (token: string) => void; 'expired-callback'?: () => void; 'error-callback'?: () => void }) => string
      remove?: (widgetId: string) => void
    }
  }
}

function TurnstileChallenge({ onToken }: { onToken: (token: string) => void }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY || ''
  useEffect(() => {
    if (!siteKey || !containerRef.current) return
    let widgetId: string | undefined
    let cancelled = false
    const render = () => {
      if (cancelled || !window.turnstile || !containerRef.current || widgetId) return
      widgetId = window.turnstile.render(containerRef.current, {
        sitekey: siteKey,
        action: 'auth',
        callback: token => onToken(token),
        'expired-callback': () => onToken(''),
        'error-callback': () => onToken(''),
      })
    }
    if (window.turnstile) render()
    else {
      let script = document.querySelector<HTMLScriptElement>('script[data-contexa-turnstile]')
      if (!script) {
        script = document.createElement('script')
        script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
        script.async = true
        script.defer = true
        script.dataset.contexaTurnstile = 'true'
        document.head.appendChild(script)
      }
      script.addEventListener('load', render)
      if (script.dataset.loaded === 'true') render()
      script.addEventListener('load', () => { script!.dataset.loaded = 'true' }, { once: true })
    }
    return () => {
      cancelled = true
      if (widgetId) window.turnstile?.remove?.(widgetId)
      onToken('')
    }
  }, [siteKey, onToken])
  if (!siteKey) return null
  return <div className="turnstile-area"><div className="turnstile-host" ref={containerRef} /><small>Protected by Cloudflare Turnstile. Verification is checked server-side.</small></div>
}

function Login({ uiStyle, onUiStyleChange, onLogin, onSupabaseLogin, supabaseEnabled = false, onRegister, onForgotPassword, onResetPassword, onAcceptInvitation, error, busy, submissionMode = false, initialMode = 'signin', initialToken = '' }: {
  uiStyle: UiStyle; onUiStyleChange: (style: UiStyle) => void
  onLogin: (email: string, password: string, turnstileToken?: string) => Promise<void>
  onSupabaseLogin: (email: string, password: string) => Promise<void>
  supabaseEnabled?: boolean
  onRegister: (name: string, workspaceName: string, email: string, password: string, turnstileToken?: string) => Promise<void>
  onForgotPassword: (email: string) => Promise<string>
  onResetPassword: (token: string, password: string) => Promise<string>
  onAcceptInvitation: (token: string, name: string, password: string) => Promise<void>
  error: string; busy: boolean; submissionMode?: boolean; initialMode?: 'signin' | 'reset' | 'invite'; initialToken?: string
}) {
  const [mode, setMode] = useState<'signin' | 'register' | 'forgot' | 'reset' | 'invite'>(initialMode)
  const [name, setName] = useState('')
  const [workspaceName, setWorkspaceName] = useState('')
  const [email, setEmail] = useState(submissionMode ? 'admin@contexa.local' : '')
  const [password, setPassword] = useState(submissionMode ? 'ContexA!2026' : '')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [localError, setLocalError] = useState('')
  const [notice, setNotice] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState('')
  const [turnstileReset, setTurnstileReset] = useState(0)
  const onTurnstileToken = useCallback((token: string) => setTurnstileToken(token), [])
  const turnstileEnabled = Boolean(import.meta.env.VITE_TURNSTILE_SITE_KEY)
  const supabaseOnly = import.meta.env.VITE_AUTH_MODE === 'supabase'
  // Ask the server what really works so the form never offers a dead end.
  const [cfg, setCfg] = useState<Awaited<ReturnType<typeof api.authConfig>> | null>(null)
  useEffect(() => {
    let active = true
    api.authConfig().then(value => {
      if (!active) return
      setCfg(value)
      if (value.demo_accounts) { setEmail(v => v || ROLE_CREDENTIALS[0].email); setPassword(v => v || ROLE_CREDENTIALS[0].password) }
      else { setEmail(v => v === ROLE_CREDENTIALS[0].email ? '' : v); setPassword(v => v === ROLE_CREDENTIALS[0].password ? '' : v) }
    }).catch(() => { /* API unreachable: keep the default form; sign-in will report the connection error */ })
    return () => { active = false }
  }, [])
  const demoAvailable = cfg ? cfg.demo_accounts : submissionMode
  const signupAvailable = cfg ? cfg.signup_open : true
  const recoveryAvailable = (supabaseOnly && supabaseEnabled) || (cfg ? cfg.password_recovery : true)
  const isPasswordMode = mode === 'register' || mode === 'reset' || mode === 'invite'
  async function submit(e: FormEvent) {
    e.preventDefault(); setLocalError(''); setNotice('')
    if (mode === 'signin') {
      if (supabaseOnly) { await onSupabaseLogin(email, password); return }
      if (turnstileEnabled && !turnstileToken) { setLocalError('Complete the Cloudflare verification before signing in.'); return }
      await onLogin(email, password, turnstileToken || undefined)
      if (turnstileEnabled) { setTurnstileToken(''); setTurnstileReset(value => value + 1) }
      return
    }
    if (mode === 'forgot') {
      setActionBusy(true)
      try { const message = await onForgotPassword(email); setNotice(message) }
      catch (err) { setLocalError(err instanceof Error ? err.message : 'Could not request password recovery.') }
      finally { setActionBusy(false) }
      return
    }
    if (password.length < 12 || !/[a-zA-Z]/.test(password) || !/\d/.test(password)) {
      setLocalError('Use at least 12 characters with at least one letter and one number.'); return
    }
    if (password !== confirmPassword) { setLocalError('The passwords do not match.'); return }
    if (mode === 'register') {
      if (turnstileEnabled && !turnstileToken) { setLocalError('Complete the Cloudflare verification before creating your workspace.'); return }
      await onRegister(name, workspaceName, email, password, turnstileToken || undefined)
      if (turnstileEnabled) { setTurnstileToken(''); setTurnstileReset(value => value + 1) }
      return
    }
    setActionBusy(true)
    try {
      if (mode === 'reset') { setNotice(await onResetPassword(initialToken, password)); setMode('signin'); setPassword(''); setConfirmPassword('') }
      else { await onAcceptInvitation(initialToken, name, password) }
    } catch (err) { setLocalError(err instanceof Error ? err.message : 'This account action could not be completed.') }
    finally { setActionBusy(false) }
  }
  const title = ({ signin: 'Welcome back', register: 'Create your account', forgot: 'Reset your password', reset: 'Choose a new password', invite: 'Join your workspace' } as const)[mode]
  const kicker = ({ signin: 'YOUR WORKSPACE, IN FOCUS', register: 'A PRIVATE BRAND WORKSPACE', forgot: 'ACCOUNT RECOVERY', reset: 'SECURE PASSWORD UPDATE', invite: 'WORKSPACE INVITATION' } as const)[mode]
  return <div className="login-shell auth-shell">
    <div className="login-art">
      <div className="art-grid" />
      <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" /><div className="art-orbit orbit-three" />
      <div className="auth-orbital-copy"><div className="art-copy"><BrandMark /><div className="eyebrow"><span className="live-dot" /> <span className="neo-only">BRAND INTEGRITY</span><span className="pro-only">Brand integrity</span> {submissionMode && <span className="login-submission-badge"><ShieldCheck size={11} /> OFFLINE DEMO</span>}</div>
        <h1 className="neo-only">Trust every<br /><em>word you publish.</em></h1><p className="neo-only">Find brand risk while content is still a draft.</p>
        <h1 className="pro-only">Check every claim before it ships.</h1><p className="pro-only proof-lede">ContexA compares drafts with your approved rules and facts, routes risky findings to the right reviewer, and records every decision.</p>
        <LoginProof />
        <div className="login-metrics neo-only"><div><strong>01</strong><span>Approved rules</span></div><div><strong>02</strong><span>Grounded review</span></div><div><strong>03</strong><span>Audit trail</span></div></div>
      </div></div>
      <div className="login-footer"><span>CONTEXT. CLARITY. CONFIDENCE.</span><span>CONTEXA STUDIO</span></div>
    </div>
    <div className="login-panel auth-panel"><div className="style-toggle-row"><StyleToggle value={uiStyle} onChange={onUiStyleChange} /></div><div className="login-panel-top"><span>{mode === 'signin' ? 'WELCOME BACK' : mode === 'register' ? 'CREATE YOUR WORKSPACE' : mode === 'invite' ? 'ACCEPT INVITATION' : 'ACCOUNT ACCESS'}</span><span className="auth-secure-indicator"><ShieldCheck size={13}/> Secure session</span></div>
      <div className="auth-form-card" key={mode}>
        {(mode === 'signin' || mode === 'register') && !supabaseOnly && signupAvailable && <div className="auth-mode-switch" role="tablist" aria-label="Account access">
          <button type="button" role="tab" aria-selected={mode === 'signin'} className={mode === 'signin' ? 'is-active' : ''} onClick={() => { setMode('signin'); setLocalError(''); setNotice('') }}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === 'register'} className={mode === 'register' ? 'is-active' : ''} onClick={() => { setMode('register'); setLocalError(''); setNotice('') }}>Create account</button>
        </div>}
        <form className="login-form" onSubmit={submit}>
          <div className="form-kicker">{kicker}</div>
          <h2>{title}</h2>
          <p className="muted-text">{mode === 'signin' && supabaseOnly ? 'Use your verified organization account. Workspace access and permissions are managed by ContexA.' : ({ signin: 'Sign in to continue to your governance workspace.', register: 'Start with your own rules, documents and review history.', forgot: 'Enter your account email. If it exists, we will send a one-time recovery link.', reset: 'Your reset link is time-limited and can only be used once.', invite: 'Set your name and password to join the invited workspace.' } as const)[mode]}</p>
          {(mode === 'register' || mode === 'invite') && <>
            <label className="field-label" htmlFor="register-name">Full name</label>
            <div className="input-wrap"><Users size={16} /><input id="register-name" type="text" autoComplete="name" value={name} onChange={e => setName(e.target.value)} placeholder="Your name" minLength={2} maxLength={140} required /></div>
          </>}
          {mode === 'register' && <>
            <label className="field-label" htmlFor="register-workspace">Workspace name <span className="optional-label">OPTIONAL</span></label>
            <div className="input-wrap"><BriefcaseBusiness size={16} /><input id="register-workspace" type="text" autoComplete="organization" value={workspaceName} onChange={e => setWorkspaceName(e.target.value)} placeholder="e.g. Northstar Creative" maxLength={140} /></div>
          </>}
          {(mode === 'signin' || mode === 'register' || mode === 'forgot') && <>
            <label className="field-label" htmlFor="auth-email">Work email</label><div className="input-wrap"><Users size={16} /><input id="auth-email" type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@company.com" required maxLength={254} /></div>
          </>}
          {(mode === 'signin' || isPasswordMode) && <>
            <label className="field-label" htmlFor="auth-password">{mode === 'reset' ? 'New password' : 'Password'}</label><div className="input-wrap"><LockKeyhole size={16} /><input id="auth-password" type={showPass ? 'text' : 'password'} autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} value={password} onChange={e => setPassword(e.target.value)} required minLength={isPasswordMode ? 12 : 1} maxLength={128} placeholder={mode === 'signin' ? 'Enter your password' : '12+ characters, letters and numbers'} /><button type="button" className="show-pass" onClick={() => setShowPass(v => !v)}>{showPass ? 'Hide' : 'Show'}</button></div>
            {isPasswordMode && <>
              <label className="field-label" htmlFor="auth-confirm-password">Confirm password</label><div className="input-wrap"><LockKeyhole size={16} /><input id="auth-confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required minLength={12} maxLength={128} placeholder="Enter it again" /></div>
              <p className="auth-password-hint"><ShieldCheck size={13}/> At least 12 characters, including a letter and a number.</p>
            </>}
          </>}
          {(mode === 'signin' || mode === 'register') && turnstileEnabled && <TurnstileChallenge key={`${mode}-${turnstileReset}`} onToken={onTurnstileToken} />}
          {notice && <div className="inline-success" role="status"><CheckCircle2 size={15}/>{notice}</div>}
          {(localError || error) && <div className="inline-error" role="alert"><AlertCircle size={15} />{localError || error}</div>}
          <button className="btn btn-primary login-submit" type="submit" disabled={busy || actionBusy}>{busy || actionBusy ? <RefreshCw size={16} className="spin" /> : <span>{mode === 'signin' && supabaseOnly ? 'Sign in securely' : ({ signin: 'Sign in', register: 'Create workspace', forgot: 'Send recovery link', reset: 'Update password', invite: 'Accept invitation' } as const)[mode]}</span>} {!(busy || actionBusy) && <ArrowRight size={17} />}</button>
          {mode === 'signin' && supabaseEnabled && !supabaseOnly && <div className="auth-provider-divider"><span>OR</span></div>}
          {mode === 'signin' && supabaseEnabled && !supabaseOnly && <button type="button" className="btn btn-secondary login-submit" disabled={busy || actionBusy || !email || !password} onClick={() => onSupabaseLogin(email, password)}><ShieldCheck size={15}/> Sign in with organization identity</button>}
          {mode === 'signin' && recoveryAvailable && (!supabaseOnly || supabaseEnabled) && <button type="button" className="auth-link-button" onClick={() => { setMode('forgot'); setLocalError(''); setNotice('') }}>Forgot password?</button>}
          {mode === 'forgot' && <button type="button" className="auth-link-button" onClick={() => { setMode('signin'); setLocalError(''); setNotice('') }}>Back to sign in</button>}
          {mode === 'register' && <p className="auth-account-note">Your workspace starts private. Your first account is its administrator; new public registrations cannot join or view another workspace.</p>}
        </form>
        {demoAvailable && !supabaseOnly && mode === 'signin' && <div className="demo-logins"><div className="demo-label"><span>Demo accounts</span><span>Click one to fill the form</span></div>{ROLE_CREDENTIALS.map((cred) => <button key={cred.email} type="button" className="demo-login" onClick={() => { setEmail(cred.email); setPassword(cred.password); setLocalError('') }}><span className="demo-avatar">{initials(cred.label)}</span><span className="demo-login-text"><strong>{cred.label} <em className="demo-role">· {cred.role}</em></strong><small className="demo-cred">{cred.email}</small><small className="demo-cred">Password: {cred.password}</small></span><ChevronRight size={15} /></button>)}<p className="demo-warning"><Info size={13} />Demo accounts are for local demonstrations only.</p></div>}
      </div>
      <div className="login-bottom">CONTEXA STUDIO <span>{submissionMode ? 'SUBMISSION MODE' : 'PRIVATE WORKSPACE ACCESS'}</span></div>
    </div>
  </div>
}

function App() {
  const [uiStyle, setUiStyle] = useState<UiStyle>(readUiStyle)
  useEffect(() => {
    document.documentElement.dataset.style = uiStyle
    try { window.localStorage.setItem('contexa_ui_style', uiStyle) } catch { /* private mode: style still applies for this session */ }
  }, [uiStyle])
  const [motionLevel, setMotionLevel] = useState<MotionLevel>(() => {
    const saved = window.localStorage.getItem('contexa_motion_level')
    return saved === 'calm' || saved === 'cinematic' || saved === 'studio' ? saved : 'studio'
  })
  useEffect(() => {
    document.documentElement.dataset.motion = motionLevel
    window.localStorage.setItem('contexa_motion_level', motionLevel)
  }, [motionLevel])
  const submissionMode = import.meta.env.VITE_SUBMISSION_MODE === 'true'
  const authQuery = new URLSearchParams(window.location.search)
  const authHash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const supabaseRecoveryToken = authHash.get('type') === 'recovery' ? (authHash.get('access_token') || '') : ''
  const initialAuthToken = authQuery.get('password-reset_token') || authQuery.get('workspace-invite_token') || supabaseRecoveryToken
  const initialAuthMode: 'signin' | 'reset' | 'invite' = (authQuery.has('password-reset_token') || Boolean(supabaseRecoveryToken)) ? 'reset' : authQuery.has('workspace-invite_token') ? 'invite' : 'signin'
  const [user, setUser] = useState<User | null>(null)
  const [serverDemo, setServerDemo] = useState(false)
  useEffect(() => { api.authConfig().then(c => setServerDemo(c.demo_accounts)).catch(() => {}) }, [])
  const demoMode = submissionMode || serverDemo
  const [apiHealthState, setApiHealthState] = useState<ApiHealthState>('checking')
  const [entryReveal, setEntryReveal] = useState(false)
  const dismissEntryReveal = useCallback(() => setEntryReveal(false), [])
  useEffect(() => { if (uiStyle !== 'neobrutalism' && entryReveal) setEntryReveal(false) }, [uiStyle, entryReveal])
  const [view, setView] = useState<View>('dashboard')
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [rules, setRules] = useState<Rule[]>([])
  const [insights, setInsights] = useState<InsightData | null>(null)
  const [audit, setAudit] = useState<ActivityItem[]>([])
  const [settings, setSettings] = useState<any>(null)
  const [team, setTeam] = useState<User[]>([])
  const [docDetail, setDocDetail] = useState<DocumentDetail | null>(null)
  const [search, setSearch] = useState('')
  const [libraryStatus, setLibraryStatus] = useState('all')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number; fileName: string } | null>(null)
  const [demoBusy, setDemoBusy] = useState(false)
  const [loginBusy, setLoginBusy] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [error, setError] = useState('')
  const [toast, setToast] = useState<{ kind: 'success' | 'error' | 'info'; message: string } | null>(null)
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false)
  const [dismissTarget, setDismissTarget] = useState<Finding | null>(null)
  const [dismissNote, setDismissNote] = useState('')
  const [editTarget, setEditTarget] = useState<Finding | null>(null)
  const [editText, setEditText] = useState('')
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishNote, setPublishNote] = useState('')
  const [ruleModal, setRuleModal] = useState<{ open: boolean; rule?: Rule }>({ open: false })
  const [guidelineImportBusy, setGuidelineImportBusy] = useState(false)
  const [teamModal, setTeamModal] = useState(false)
  const [selectedPage, setSelectedPage] = useState(1)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewBusy, setPreviewBusy] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const mobileNavToggleRef = useRef<HTMLButtonElement | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  const canAdmin = user?.role === 'Brand Admin'
  const canSignOff = !!user && ['Manager', 'SME / Legal', 'Brand Admin'].includes(user.role)
  const canRescan = canSignOff
  const activeFindingCount = docDetail?.findings.filter(f => f.status === 'open').length || 0
  const criticalCount = docDetail?.findings.filter(f => f.status === 'open' && f.severity === 'critical').length || 0
  const viewTitle = NAV.find(n => n.id === view)?.label || 'Home'

  const notify = useCallback((message: string, kind: 'success' | 'error' | 'info' = 'success') => {
    setToast({ message, kind }); window.setTimeout(() => setToast(current => current?.message === message ? null : current), 4200)
  }, [])
  const logout = useCallback(() => {
    void signOutSupabaseSession(getToken())
    setToken(''); setUser(null); setDashboard(null); setDocuments([]); setDocDetail(null); setSelectedDocId(null); setMobileNavOpen(false); setView('dashboard')
  }, [])

  useEffect(() => { onUnauthorized(() => { logout(); setLoginError('Your session expired. Please sign in again.') }) }, [logout])
  useEffect(() => {
    const verificationToken = authQuery.get('verify-email_token')
    if (!verificationToken) return
    api.verifyEmail(verificationToken).then(result => setLoginError(result.message)).catch(err => setLoginError(err instanceof Error ? err.message : 'Email verification failed.'))
      .finally(() => { const clean = new URL(window.location.href); clean.searchParams.delete('verify-email_token'); window.history.replaceState({}, '', clean.toString()) })
  // The verification token is captured on the initial page load only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const isTyping = !!target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setGlobalSearchOpen(true); searchInputRef.current?.focus()
      } else if (event.key === '/' && !isTyping) {
        event.preventDefault(); setGlobalSearchOpen(true); searchInputRef.current?.focus()
      } else if (event.key === 'Escape') {
        setGlobalSearchOpen(false)
        setMobileNavOpen(false)
      }
    }
    window.addEventListener('keydown', onShortcut)
    return () => window.removeEventListener('keydown', onShortcut)
  }, [])
  useEffect(() => {
    if (!getToken()) return
    api.me().then(setUser).catch(() => { setToken(''); setUser(null) })
  }, [])
  useEffect(() => {
    if (!mobileNavOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.querySelector<HTMLElement>('#primary-navigation .nav-item')?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      mobileNavToggleRef.current?.focus()
    }
  }, [mobileNavOpen])

  useEffect(() => {
    if (!user) { setApiHealthState('checking'); return }
    let active = true
    let checking = false
    const checkHealth = async () => {
      if (checking) return
      checking = true
      try {
        await api.health()
        if (active) setApiHealthState('ready')
      } catch (error) {
        if (!active) return
        setApiHealthState(error instanceof ApiError && error.status >= 500 ? 'degraded' : 'offline')
      } finally {
        checking = false
      }
    }
    void checkHealth()
    const timer = window.setInterval(() => void checkHealth(), 60_000)
    const onFocus = () => { void checkHealth() }
    window.addEventListener('focus', onFocus)
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('focus', onFocus) }
  }, [user])

  const login = async (email: string, password: string, turnstileToken?: string) => {
    setLoginBusy(true); setLoginError('')
    try { const result = await api.login(email, password, turnstileToken); setToken(result.access_token); setView('dashboard'); setUser(result.user); setEntryReveal(true); notify(`Welcome back, ${result.user.name.split(' ')[0]}.`) }
    catch (e) { setLoginError(e instanceof Error ? e.message : 'Could not sign in.'); }
    finally { setLoginBusy(false) }
  }

  const loginWithSupabase = async (email: string, password: string) => {
    setLoginBusy(true); setLoginError('')
    try {
      const session = await signInSupabasePassword(email, password)
      setSupabaseSession(session.access_token, session.refresh_token)
      const nextUser = await api.me()
      setUser(nextUser); setView('dashboard'); setEntryReveal(true)
      notify(`Authenticated with Supabase, ${nextUser.name.split(' ')[0]}.`)
    } catch (e) { setToken(''); setLoginError(e instanceof Error ? e.message : 'Supabase sign-in failed.') }
    finally { setLoginBusy(false) }
  }

  const registerAccount = async (name: string, workspaceName: string, email: string, password: string, turnstileToken?: string) => {
    setLoginBusy(true); setLoginError('')
    try {
      const result = await api.register({ name, workspace_name: workspaceName.trim() || undefined, email, password, turnstile_token: turnstileToken })
      if (!result.access_token || !result.user) {
        setLoginError(`${result.message || 'Your account was created.'}${result.debug_link ? ` Development verification link: ${result.debug_link}` : ''}`)
        return
      }
      setToken(result.access_token); setView('dashboard'); setUser(result.user); setEntryReveal(true)
      notify(`Your workspace is ready, ${result.user.name.split(' ')[0]}.`)
    } catch (e) { setLoginError(e instanceof Error ? e.message : 'Could not create your account.') }
    finally { setLoginBusy(false) }
  }

  const requestPasswordReset = async (email: string) => {
    if (supabaseAuthMode === 'supabase') {
      await requestSupabasePasswordRecovery(email)
      return 'If an account exists for that email, a secure recovery link has been sent.'
    }
    const result = await api.forgotPassword(email)
    return `${result.message}${result.debug_link ? ` Development link: ${result.debug_link}` : ''}`
  }
  const completePasswordReset = async (tokenValue: string, password: string) => {
    if (supabaseAuthMode === 'supabase') {
      await updateSupabasePassword(tokenValue, password)
      const clean = new URL(window.location.href)
      clean.hash = ''
      clean.searchParams.delete('password-reset_token')
      window.history.replaceState({}, '', clean.toString())
      return 'Your Supabase password has been updated. Sign in with your new password.'
    }
    const result = await api.resetPassword(tokenValue, password)
    const clean = new URL(window.location.href); clean.searchParams.delete('password-reset_token'); window.history.replaceState({}, '', clean.toString())
    return result.message
  }
  const completeInvitation = async (tokenValue: string, name: string, password: string) => {
    const result = await api.acceptInvitation(tokenValue, name, password)
    setToken(result.access_token); setView('dashboard'); setUser(result.user); setEntryReveal(true)
    const clean = new URL(window.location.href); clean.searchParams.delete('workspace-invite_token'); window.history.replaceState({}, '', clean.toString())
    notify(`Welcome to ${result.user.workspace_name || 'the workspace'}, ${result.user.name.split(' ')[0]}.`)
  }

  const refreshCore = useCallback(async (options: { docs?: boolean; dash?: boolean; rules?: boolean; insight?: boolean; audit?: boolean; settings?: boolean; team?: boolean } = {}) => {
    if (!user) return
    try {
      const jobs: Promise<unknown>[] = []
      if (options.dash !== false) jobs.push(api.dashboard().then(setDashboard))
      if (options.docs) jobs.push(api.documents().then(setDocuments))
      if (options.rules) jobs.push(api.rules().then(setRules))
      if (options.insight) jobs.push(api.insights().then(setInsights))
      if (options.audit) jobs.push(api.audit().then(setAudit))
      if (options.settings) jobs.push(api.settings().then(setSettings))
      if (options.team && canAdmin) jobs.push(api.users().then(setTeam))
      await Promise.all(jobs)
      setError('')
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to load workspace data.') }
  }, [user, canAdmin])

  useEffect(() => {
    if (!user) return
    if (view === 'dashboard') void refreshCore({ dash: true, docs: false })
    if (view === 'library' || view === 'review') void refreshCore({ dash: false, docs: true })
    if (view === 'rules') void refreshCore({ dash: false, rules: true })
    if (view === 'insights') void refreshCore({ dash: false, insight: true, rules: true })
    if (view === 'trustos') void refreshCore({ dash: false, docs: true })
    if (view === 'audit') void refreshCore({ dash: false, audit: true })
    if (view === 'settings') void refreshCore({ dash: false, settings: true })
    if (view === 'team') void refreshCore({ dash: false, team: true })
  }, [view, user, refreshCore])

  useEffect(() => {
    if (!user || !selectedDocId || view !== 'review') { setDocDetail(null); return }
    let stale = false
    setLoading(true); setError('')
    api.document(selectedDocId).then(data => { if (!stale) { setDocDetail(data); setSelectedPage(1) } })
      .catch(e => { if (!stale) setError(e instanceof Error ? e.message : 'Unable to load document review.') })
      .finally(() => { if (!stale) setLoading(false) })
    return () => { stale = true }
  }, [user, selectedDocId, view])

  useEffect(() => {
    let revoked = ''
    if (!user || !docDetail || !docDetail.document.filename.toLowerCase().endsWith('.pdf')) { setPreviewUrl(''); return }
    let stale = false
    setPreviewBusy(true)
    api.preview(docDetail.document.id, selectedPage).then(blob => {
      if (stale) return
      revoked = URL.createObjectURL(blob); setPreviewUrl(revoked)
    }).catch(() => { if (!stale) setPreviewUrl('') }).finally(() => { if (!stale) setPreviewBusy(false) })
    return () => { stale = true; if (revoked) URL.revokeObjectURL(revoked) }
  }, [user, docDetail?.document.id, docDetail?.document.filename, selectedPage, docDetail?.findings.length, docDetail?.document.updated_at])

  const refreshAfterMutation = async (docId?: string) => {
    await refreshCore({ dash: true, docs: true, rules: view === 'rules', insight: view === 'insights', audit: view === 'audit' })
    if (docId && view === 'review') {
      try { setDocDetail(await api.document(docId)) } catch { /* show existing review if a refresh fails */ }
    }
  }

  const navigate = (next: View) => { setView(next); setError(''); setMobileNavOpen(false); if (next !== 'review') setSelectedDocId(null) }
  const openReview = (id: string) => { setSelectedDocId(id); setSelectedPage(1); setView('review'); setError('') }

  const handleUpload = async (files: FileList | File[]) => {
    const chosen = Array.from(files).filter(Boolean)
    if (!chosen.length) return
    setUploading(true)
    let last: DocumentRecord | null = null
    let successes = 0
    for (const [index, file] of chosen.entries()) {
      setUploadProgress({ current: index + 1, total: chosen.length, fileName: file.name })
      try { last = await api.upload(file); successes++ }
      catch (e) { notify(`${file.name}: ${e instanceof Error ? e.message : 'Upload failed'}`, 'error') }
    }
    await refreshAfterMutation(last?.id)
    setUploadProgress(null)
    setUploading(false)
    if (last) { setSelectedDocId(last.id); setSelectedPage(1); setView('review'); notify(`${successes} document${successes === 1 ? '' : 's'} uploaded and scanned.`) }
  }

  const loadDemoWorkspace = async () => {
    setDemoBusy(true)
    try {
      const result = await api.seedDemo()
      await refreshCore({ dash: true, docs: true, rules: true, insight: true, audit: true })
      notify(result.created_documents
        ? `${result.created_documents} demo scenarios loaded. All findings were generated by deterministic rules; no AI model was called.`
        : 'Demo scenarios are already loaded. You can open them from Content library.', 'success')
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Could not prepare the demo workspace.', 'error')
    } finally {
      setDemoBusy(false)
    }
  }

  const doFindingAction = async (finding: Finding, status: 'accepted' | 'edited' | 'dismissed', note?: string, appliedText?: string) => {
    if (status === 'edited' && appliedText === undefined) { setEditTarget(finding); setEditText(''); return }
    try {
      await api.actOnFinding(finding.id, status, note, appliedText)
      setDismissTarget(null); setDismissNote('')
      if (status === 'edited') { setEditTarget(null); setEditText('') }
      await refreshAfterMutation(docDetail?.document.id)
      notify(status === 'edited' ? 'Reviewer revision recorded. The original file remains unchanged.' : status === 'accepted' ? 'Finding accepted and added to the review history.' : 'Finding dismissed with rationale recorded.')
    } catch (e) { notify(e instanceof Error ? e.message : 'Could not update finding.', 'error') }
  }

  const publish = async () => {
    if (!docDetail) return
    try {
      const result = await api.publish(docDetail.document.id, publishNote)
      setPublishOpen(false); setPublishNote(''); await refreshAfterMutation(docDetail.document.id)
      notify(result.message)
    } catch (e) { notify(e instanceof Error ? e.message : 'Could not approve publication.', 'error') }
  }

  const removeDocument = async (doc: DocumentRecord) => {
    if (!window.confirm(`Delete “${doc.filename}” and its review history? This cannot be undone.`)) return
    try { await api.deleteDocument(doc.id); await refreshAfterMutation(); if (selectedDocId === doc.id) { setSelectedDocId(null); setView('library') }; notify('Document and findings removed.') }
    catch (e) { notify(e instanceof Error ? e.message : 'Could not delete document.', 'error') }
  }

  const publicPassportId = window.location.pathname.match(/^\/verify\/([a-f0-9]{32})\/?$/i)?.[1]
  if (publicPassportId) return <PublicPassportPage id={publicPassportId} />
  if (!user) return <Login uiStyle={uiStyle} onUiStyleChange={setUiStyle} onLogin={login} onSupabaseLogin={loginWithSupabase} supabaseEnabled={supabaseAuthEnabled} onRegister={registerAccount} onForgotPassword={requestPasswordReset} onResetPassword={completePasswordReset} onAcceptInvitation={completeInvitation} error={loginError} busy={loginBusy} submissionMode={submissionMode} initialMode={initialAuthMode} initialToken={initialAuthToken} />

  const filteredDocuments = documents.filter(doc => `${doc.filename} ${doc.creator_name || ''}`.toLowerCase().includes(search.toLowerCase()) && (libraryStatus === 'all' || doc.status === libraryStatus))
  const visibleFindings = (docDetail?.findings || []).filter(f => f.status === 'open')
  
  return <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${mobileNavOpen ? 'mobile-nav-open' : ''}`}>
    {entryReveal && uiStyle === 'neobrutalism' && <WorkspaceArrival onComplete={dismissEntryReveal} motionLevel={motionLevel} />}
    {mobileNavOpen && <button className="sidebar-backdrop" aria-label="Close navigation menu" onClick={() => setMobileNavOpen(false)} />}
    <aside className="sidebar">
      <div className="sidebar-top"><BrandMark /><button className="icon-button mobile-drawer-close" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation menu"><X size={17} /></button> <button className="icon-button sidebar-collapse" onClick={() => setCollapsed(v => !v)} aria-label="Collapse sidebar"><PanelLeftClose size={17} /></button></div>
      <nav className="nav-groups" id="primary-navigation" aria-label="Primary navigation">
        {['WORKSPACE', 'GOVERNANCE', 'ADMIN'].map(group => <div className="nav-group" key={group}><div className="nav-label">{group}</div>{NAV.filter(n => n.group === group).map(item => {
          const Icon = item.icon; const active = view === item.id || (view === 'review' && item.id === 'library')
          if (item.id === 'team' && !canAdmin) return null
          return <button key={item.id} className={`nav-item ${active ? 'active' : ''}`} onClick={() => navigate(item.id)} title={item.label}><Icon size={17} strokeWidth={1.8} /><span>{item.label}</span>{item.id === 'review' && dashboard?.critical_findings ? <span className="nav-count">{dashboard.critical_findings}</span> : null}</button>
        })}</div>)}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-user"><div className="avatar">{initials(user.name)}</div><div className="user-meta"><strong>{user.name}</strong><small>{user.role}</small></div><button onClick={logout} className="icon-button logout-button" aria-label="Sign out" title="Sign out"><LogOut size={16} /></button></div></div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="topbar-left"><button ref={mobileNavToggleRef} className="icon-button mobile-nav-toggle" onClick={() => setMobileNavOpen(value => !value)} aria-label={mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'} aria-controls="primary-navigation" aria-expanded={mobileNavOpen}>{mobileNavOpen ? <X size={18} /> : <Menu size={18} />}</button><div className="topbar-page-name"><span className="topbar-status-dot" title={submissionMode ? 'Submission mode · deterministic rules only' : 'Local workspace'} /><strong>{viewTitle}</strong></div></div>
        <div className="topbar-right"><div className={`api-health-pill api-health-${apiHealthState}`} role="status" aria-live="polite" title={apiHealthState === 'ready' ? 'API and application database are responding' : apiHealthState === 'degraded' ? 'The API responded, but a required service is unavailable' : apiHealthState === 'offline' ? 'ContexA API is not reachable' : 'Checking ContexA service health'}><i /><span>{apiHealthState === 'ready' ? 'Connected' : apiHealthState === 'degraded' ? 'Degraded' : apiHealthState === 'offline' ? 'Offline' : 'Checking'}</span></div><div className="global-search"><Search size={16} /><input ref={searchInputRef} aria-label="Search" placeholder="Search…" value={search} onChange={e => setSearch(e.target.value)} onFocus={() => setGlobalSearchOpen(true)} onKeyDown={e => { if (e.key === 'Escape') setGlobalSearchOpen(false); if (e.key === 'Enter') { navigate('library'); setGlobalSearchOpen(false) } }} /><kbd>⌘K</kbd>{globalSearchOpen && search && <button className="search-jump" onClick={() => { navigate('library'); setGlobalSearchOpen(false) }}>View results <ArrowRight size={13} /></button>}</div><NotificationBell onOpenDocument={openReview} /><div className="topbar-avatar" title={user.role}>{initials(user.name)}</div></div>
      </header>
      <div className="content-scroll">
        <div key={view} className={`view-transition view-transition-${view}`}>
        {error && <div className="error-banner"><AlertCircle size={16} /><span>{error}</span><button className="icon-button" onClick={() => setError('')}><X size={15} /></button></div>}
        {view === 'dashboard' && <DashboardPage uiStyle={uiStyle} motionLevel={motionLevel} dashboard={dashboard} busy={loading} onUpload={handleUpload} uploading={uploading} onOpenReview={openReview} onNavigate={navigate} onRefresh={() => void refreshCore({ dash: true, docs: false })} uploadProgress={uploadProgress} canAdmin={canAdmin} demoBusy={demoBusy} onLoadDemo={() => void loadDemoWorkspace()} submissionMode={demoMode} />}
        {view === 'library' && <LibraryPage docs={filteredDocuments} status={libraryStatus} setStatus={setLibraryStatus} search={search} setSearch={setSearch} uploading={uploading} uploadProgress={uploadProgress} onUpload={handleUpload} onOpenReview={openReview} onRemove={removeDocument} role={user.role} />}
        {view === 'review' && <ReviewPage user={user} detail={docDetail} loading={loading} selectedPage={selectedPage} setSelectedPage={setSelectedPage} previewUrl={previewUrl} previewBusy={previewBusy} canSignOff={canSignOff} canRescan={canRescan} activeCount={activeFindingCount} criticalCount={criticalCount} onBack={() => navigate('library')} onAction={doFindingAction} onDismiss={f => { setDismissTarget(f); setDismissNote('') }} onPublish={() => setPublishOpen(true)} publishing={publishOpen} onRescan={async () => { if (!docDetail) return; setLoading(true); try { await api.rescan(docDetail.document.id); await refreshAfterMutation(docDetail.document.id); notify('Document rescanned against the active guideline set.') } catch (e) { notify(e instanceof Error ? e.message : 'Rescan failed.', 'error') } finally { setLoading(false) } }} onExport={async (fmt) => { if (!docDetail) return; try { const blob = await api.exportReport(docDetail.document.id, fmt); saveBlob(blob, `contexa-${docDetail.document.id.slice(0, 8)}-${fmt === 'csv' ? 'findings.csv' : 'report.json'}`); notify('Governance report exported.') } catch (e) { notify(e instanceof Error ? e.message : 'Export failed.', 'error') } }} />}
        {view === 'rules' && <RulesPage rules={rules} role={user.role} importing={guidelineImportBusy} onImport={async file => { setGuidelineImportBusy(true); try { const result = await api.importGuideline(file); await refreshCore({ dash: false, rules: true, audit: true }); notify(`${result.created_rules} guideline candidate${result.created_rules === 1 ? '' : 's'} imported from ${file.name}. Candidates are paused until reviewed.`) } catch (e) { notify(e instanceof Error ? e.message : 'Could not import guideline.', 'error') } finally { setGuidelineImportBusy(false) } }} onCreate={() => setRuleModal({ open: true })} onEdit={rule => setRuleModal({ open: true, rule })} onToggle={async rule => { try { await api.updateRule(rule.id, { is_active: !rule.is_active }); await refreshCore({ dash: false, rules: true }); notify(`${rule.code} ${rule.is_active ? 'paused' : 'activated'}.`) } catch (e) { notify(e instanceof Error ? e.message : 'Could not update rule.', 'error') } }} />}
        {view === 'insights' && <InsightsPage data={insights} role={user.role} rules={rules} onChanged={() => void refreshCore({ dash: false, insight: true, rules: true, audit: true })} onNotify={notify} />}
        {view === 'trustos' && <TrustOSPage role={user.role} />}
        {view === 'foundation' && <TrustFoundationPage role={user.role} />}
        {view === 'audit' && <AuditPage audit={audit} />}
        {view === 'team' && <TeamPage team={team} role={user.role} onAdd={() => setTeamModal(true)} />}
        {view === 'settings' && <SettingsPage uiStyle={uiStyle} onUiStyleChange={setUiStyle} settings={settings} user={user} motionLevel={motionLevel} onMotionLevelChange={setMotionLevel} onLogout={logout} />}
        </div>
      </div>
    </main>

    {dismissTarget && <Modal title="Dismiss finding" eyebrow={dismissTarget.rule_code || 'AUDIT RATIONALE'} onClose={() => setDismissTarget(null)}><div className="modal-body-copy"><div className={`severity-icon severity-${dismissTarget.severity}`}><AlertTriangle size={18} /></div><p>You're overriding <strong>{dismissTarget.rule_title}</strong>. A rationale is mandatory and will be retained in the audit trail.</p><div className="quote-box">“{dismissTarget.flagged_text}”</div></div><label className="field-label">Dismissal rationale <span className="required">*</span></label><textarea className="form-textarea" rows={4} placeholder="Explain why this finding does not require a change..." value={dismissNote} onChange={e => setDismissNote(e.target.value)} /><div className="modal-actions"><button className="btn btn-secondary" onClick={() => setDismissTarget(null)}>Cancel</button><button className="btn btn-danger" disabled={!dismissNote.trim()} onClick={() => void doFindingAction(dismissTarget, 'dismissed', dismissNote)}>Dismiss with rationale <ArrowRight size={15} /></button></div></Modal>}

    {publishOpen && docDetail && <Modal title="Publication sign-off" eyebrow="GOVERNANCE GATE" onClose={() => { setPublishOpen(false); setPublishNote('') }}><div className="publish-modal-icon"><ShieldCheck size={25} /></div><p className="modal-body-copy">You are marking <strong>{docDetail.document.filename}</strong> as Publish Ready. ContexA records approval; it does not publish to an external platform.</p><div className="signoff-checks"><div><CheckCircle2 size={16} /><span>Critical findings addressed</span><strong>{criticalCount === 0 ? 'PASS' : 'BLOCKED'}</strong></div><div><FileCheck2 size={16} /><span>Review record preserved</span><strong>YES</strong></div><div><Fingerprint size={16} /><span>Audit event generated</span><strong>YES</strong></div></div>{docDetail.findings.some(f => f.severity === 'critical' && f.status === 'dismissed') && <><label className="field-label">Final override / sign-off note <span className="required">*</span></label><textarea className="form-textarea" rows={3} placeholder="Explain why the dismissed critical finding is approved..." value={publishNote} onChange={e => setPublishNote(e.target.value)} /></>}{criticalCount > 0 && <div className="inline-error"><AlertCircle size={15} />Resolve or dismiss all critical findings before sign-off.</div>}<div className="modal-actions"><button className="btn btn-secondary" onClick={() => setPublishOpen(false)}>Cancel</button><button className="btn btn-primary" disabled={criticalCount > 0 || (docDetail.findings.some(f => f.severity === 'critical' && f.status === 'dismissed') && !publishNote.trim())} onClick={() => void publish()}>Confirm sign-off <ShieldCheck size={16} /></button></div></Modal>}

    {editTarget && <Modal title="Record applied revision" eyebrow={editTarget.rule_code || 'REVIEWER EDIT'} onClose={() => { setEditTarget(null); setEditText('') }}><div className="revision-context"><div><span className="section-eyebrow small">FLAGGED COPY</span><p>{editTarget.flagged_text}</p></div><div><span className="section-eyebrow small">GUIDANCE</span><p>{editTarget.suggested_fix}</p></div></div><label className="field-label">Revised copy <span className="required">*</span></label><textarea className="form-textarea" rows={5} value={editText} onChange={e => setEditText(e.target.value)} placeholder="Enter the exact replacement copy after making the correction..." /><div className="revision-warning"><Info size={14} /><span>The exact revised text will be attached to this finding and included in the governance export. The original uploaded file is never silently overwritten.</span></div><div className="modal-actions"><button className="btn btn-secondary" onClick={() => { setEditTarget(null); setEditText('') }}>Cancel</button><button className="btn btn-primary" disabled={!editText.trim()} onClick={() => void doFindingAction(editTarget, 'edited', 'Revision recorded by reviewer', editText)}>Save revision <Check size={15} /></button></div></Modal>}
    {ruleModal.open && <RuleModal rule={ruleModal.rule} onClose={() => setRuleModal({ open: false })} onSaved={async (message) => { setRuleModal({ open: false }); await refreshCore({ dash: false, rules: true }); notify(message) }} onError={message => notify(message, 'error')} />}
    {teamModal && <TeamModal onClose={() => setTeamModal(false)} onSaved={async (message) => { setTeamModal(false); await refreshCore({ dash: false, team: true, audit: true }); notify(message) }} onError={message => notify(message, 'error')} />}
    <Toast toast={toast} onClose={() => setToast(null)} />
  </div>
}

function PageTitle({ eyebrow, title, subtitle, right }: { eyebrow?: string; title: string; subtitle?: string; right?: ReactNode }) {
  return <div className="page-title-row"><div>{eyebrow && <div className="section-eyebrow">{eyebrow}</div>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{right && <div className="page-title-actions">{right}</div>}</div>
}
function StatCard({ label, value, note, icon: Icon, accent, trend, series }: { label: string; value: string | number; note: string; icon: LucideIcon; accent: string; trend?: string; series?: number[] }) {
  // The line is drawn only from real stored history (daily compliance snapshots); with fewer than two points it is omitted rather than faked.
  const pts = (series || []).filter(v => Number.isFinite(v))
  let path = ''
  if (pts.length >= 2) {
    const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo
    path = pts.map((v, k) => `${k ? 'L' : 'M'}${(2 + (k * 70) / (pts.length - 1)).toFixed(1)} ${(span === 0 ? 12 : 22 - ((v - lo) / span) * 20).toFixed(1)}`).join(' ')
  }
  const last = pts.length >= 2 ? (path.split(' ').slice(-2)) : []
  return <div className={`stat-card stat-card-${accent}`}><div className="stat-top"><span>{label}</span><span className={`stat-icon ${accent}`}><Icon size={17} /></span></div><div className="stat-value">{value}</div>{path && <svg className="stat-sparkline" viewBox="0 0 74 24" role="img" aria-label={`${label}: last ${pts.length} daily snapshots`}><path className="sparkline-underlay" d={`${path} L72 24 L2 24 Z`} /><path className="sparkline-path" d={path} /><circle className="sparkline-dot" cx={last[0]?.replace('L', '')} cy={last[1]} r="2" /></svg>}<div className="stat-bottom"><span>{note}</span>{trend && <span className="stat-trend">{trend.startsWith('+') && <ArrowUpRight size={13} />}{trend}</span>}</div></div>
}
function EmptyState({ icon: Icon, title, copy, action }: { icon: LucideIcon; title: string; copy: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={24} /></div><h3>{title}</h3><p>{copy}</p>{action}</div>
}
function UploadButton({ onFiles, busy, large = false, multiple = true, label = 'Upload content' }: { onFiles: (files: FileList | File[]) => void; busy: boolean; large?: boolean; multiple?: boolean; label?: string }) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)
  return <div className={`upload-control ${large ? 'upload-large' : ''} ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); if (!busy) onFiles(e.dataTransfer.files) }} aria-busy={busy}>
    <input ref={inputRef} disabled={busy} type="file" accept=".pdf,.docx,.pptx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff,.bmp" multiple={multiple} onChange={e => { if (e.target.files?.length) onFiles(e.target.files); e.currentTarget.value = '' }} hidden />
    <button className={`btn ${large ? 'btn-primary' : 'btn-secondary'}`} disabled={busy} onClick={() => inputRef.current?.click()}>{busy ? <RefreshCw className="spin" size={16} /> : <UploadCloud size={16} />}{busy ? 'Scanning...' : label}</button>
  </div>
}

function DashboardPage({ uiStyle, motionLevel, dashboard, busy, onUpload, uploading, uploadProgress, onOpenReview, onNavigate, onRefresh, canAdmin, demoBusy, onLoadDemo, submissionMode }: { uiStyle: UiStyle; motionLevel: MotionLevel; dashboard: Dashboard | null; busy: boolean; onUpload: (files: FileList | File[]) => void; uploading: boolean; uploadProgress: { current: number; total: number; fileName: string } | null; onOpenReview: (id: string) => void; onNavigate: (view: View) => void; onRefresh: () => void; canAdmin: boolean; demoBusy: boolean; onLoadDemo: () => void; submissionMode: boolean }) {
  const [history, setHistory] = useState<any[]>([])
  useEffect(() => { let on = true; api.complianceTrend(30).then(r => { if (on) setHistory(r.series) }).catch(() => { /* no history yet: cards simply omit the line */ }); return () => { on = false } }, [dashboard?.total_documents, dashboard?.critical_findings, dashboard?.in_review])
  if (!dashboard && busy) return <div className="loading-state"><RefreshCw className="spin" size={22} /><span>Loading governance workspace…</span></div>
  const score = dashboard?.integrity_score ?? 100
  const hist = (key: string) => history.map(point => Number(point[key]))
  const delta = history.length >= 2 ? history[history.length - 1].integrity_score - history[0].integrity_score : null
  return <div className="page-container">
    <PageTitle title="Workspace" subtitle="Review content, risks and approvals." right={<><button className="btn btn-secondary" onClick={onRefresh}><RefreshCw size={15} /> Refresh</button><UploadButton onFiles={onUpload} busy={uploading} label={uploadProgress ? `Scanning ${uploadProgress.current}/${uploadProgress.total}` : 'Upload content'} /></>} />
    {uiStyle !== 'neobrutalism' ? <LedgerStrip dashboard={dashboard} onNavigate={onNavigate} /> : <div className="welcome-strip premium-hero"><div className="welcome-icon"><ShieldCheck size={19} /></div><div className="hero-copy"><div className="hero-kicker"><span className="hero-pulse" /> BRAND GOVERNANCE</div><strong>Confidence, before publish.</strong><p>Catch unsupported claims, outdated pricing, off-tone copy and accessibility gaps while content is still a draft.</p><div className="hero-feature-row"><span><ShieldCheck size={13} /> Source-backed claims</span><span><Fingerprint size={13} /> Auditable decisions</span></div></div><div className="hero-visual hero-visual-3d"><GovernanceScene3D score={score} motionLevel={motionLevel} /></div></div>}
    {submissionMode && canAdmin && !dashboard?.total_documents && <section className="submission-demo-card"><div className="submission-demo-icon"><Sparkles size={20} /></div><div className="submission-demo-copy"><strong>Submission mode · no local AI required</strong><p>Prepare a realistic walkthrough with sample campaign, product-naming and pricing documents. The demo uses the real rule engine and review workflow, labels sample assets clearly, and never calls Ollama or a cloud AI provider.</p><div className="submission-demo-meta"><ShieldCheck size={12} /> Offline-friendly · repeatable · auditable</div></div><button className="btn btn-primary" onClick={onLoadDemo} disabled={demoBusy || busy}>{demoBusy ? <RefreshCw className="spin" size={15} /> : <Sparkles size={15} />}{demoBusy ? 'Preparing workspace…' : 'Prepare demo workspace'} <ArrowRight size={14} /></button></section>}
    <div className="write-time-grid"><QuickCopyCheck /><BrandRiskMap onNavigate={onNavigate} /></div>
    <div className="stat-grid four"><StatCard label="Brand integrity score" value={`${score}%`} note="Workspace average" icon={Gauge} accent="teal" series={hist('integrity_score')} trend={delta === null ? undefined : `${delta >= 0 ? '+' : ''}${delta} pts`} /><StatCard label="Documents in review" value={dashboard?.in_review ?? 0} note="Awaiting checks or action" icon={FileClock} accent="purple" /><StatCard label="Critical findings" value={dashboard?.critical_findings ?? 0} note="Require accountable review" icon={AlertCircle} accent="red" series={hist('critical_findings')} /><StatCard label="Publish ready" value={dashboard?.publish_ready ?? 0} note="Signed off in this workspace" icon={BadgeCheck} accent="green" series={hist('publish_ready')} /></div>
    <div className="dashboard-grid"><section className="panel integrity-panel"><PanelHeading title="Governance health" action={<span className="live-label"><span /> Live</span>} /><div className="integrity-content"><div className="integrity-ring" style={{ background: `conic-gradient(var(--ring-fill, var(--nb-green)) ${score * 3.6}deg, var(--ring-track, #ffffff) 0deg)` }}><div><strong>{score}<small>%</small></strong><span>INTEGRITY</span></div></div><div className="integrity-details"><div className="integrity-description"><strong>{score >= 90 ? 'A clear standard.' : score >= 70 ? 'Needs a little attention.' : 'Review required.'}</strong><p>{dashboard?.total_documents ? 'Your current score reflects unresolved findings across uploaded content.' : 'Upload an asset to establish your first workspace baseline.'}</p></div><div className="severity-meter-row"><div><span className="legend-dot critical-dot" />Critical</div><strong>{dashboard?.severity_counts?.critical ?? 0}</strong><div className="meter"><span className="meter-critical" style={{ width: `${Math.min(100, (dashboard?.severity_counts?.critical || 0) * 12)}%` }} /></div></div><div className="severity-meter-row"><div><span className="legend-dot warning-dot" />Warning</div><strong>{dashboard?.severity_counts?.warning ?? 0}</strong><div className="meter"><span className="meter-warning" style={{ width: `${Math.min(100, (dashboard?.severity_counts?.warning || 0) * 12)}%` }} /></div></div><div className="severity-meter-row"><div><span className="legend-dot info-dot" />Informational</div><strong>{dashboard?.severity_counts?.info ?? 0}</strong><div className="meter"><span className="meter-info" style={{ width: `${Math.min(100, (dashboard?.severity_counts?.info || 0) * 12)}%` }} /></div></div></div></div><div className="panel-footer-line"><span><ShieldCheck size={14} /> Scoring uses open finding severity.</span><button className="text-link" onClick={() => onNavigate('insights')}>Explore insights <ArrowRight size={14} /></button></div></section>
      <section className="panel activity-panel"><PanelHeading title="Review activity" /><div className="activity-chart">{(dashboard?.weekly_activity || []).map(d => { const max = Math.max(1, ...(dashboard?.weekly_activity || []).map(i => i.count)); return <div className="chart-col" key={d.date}><div className="chart-value">{d.count || ''}</div><div className="chart-bar-track"><div className={`chart-bar ${d.date === new Date().toISOString().slice(0, 10) ? 'today' : ''}`} style={{ height: `${Math.max(4, d.count / max * 100)}%` }} /></div><span>{d.day}</span></div> })}</div><div className="chart-footer"><span><span className="legend-dot teal-dot" />Review, upload & sign-off events</span><strong>{(dashboard?.weekly_activity || []).reduce((n, d) => n + d.count, 0)} <small>events</small></strong></div></section></div>
    <ComplianceTrendPanel />
    <div className="lower-grid"><section className="panel table-panel"><PanelHeading title="Recent content" action={<button className="text-link" onClick={() => onNavigate('library')}>View library <ArrowRight size={14} /></button>} />
      {dashboard?.recent_documents.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>ASSET</th><th>OWNER</th><th>STATUS</th><th>INTEGRITY</th><th /></tr></thead><tbody>{dashboard.recent_documents.map(doc => <tr key={doc.id} onClick={() => onOpenReview(doc.id)} className="clickable-row"><td><div className="asset-cell"><span className="file-type-icon"><FileText size={17} /></span><span><strong>{doc.filename}</strong><small>{doc.page_count} page{doc.page_count === 1 ? '' : 's'} · {bytesLabel(doc.size_bytes)}</small></span></div></td><td><span className="owner-cell"><span className="tiny-avatar">{initials(doc.creator_name)}</span>{doc.creator_name}</span></td><td><StatusPill status={doc.status} /></td><td><ScoreLabel score={doc.compliance_score} /></td><td><ChevronRight size={15} className="table-chevron" /></td></tr>)}</tbody></table></div> : <EmptyState icon={FolderOpen} title="Your content library is waiting" copy="Upload a PDF, presentation or document to run its first governance review." action={<UploadButton onFiles={onUpload} busy={uploading} label={uploadProgress ? `Scanning ${uploadProgress.current}/${uploadProgress.total}` : 'Upload your first asset'} large />} />}</section>
      <section className="panel shortcuts-panel"><PanelHeading title="Quick actions" /><button className="shortcut-row" onClick={() => onNavigate('library')}><span className="shortcut-icon shortcut-teal"><UploadCloud size={17} /></span><span><strong>Submit new content</strong><small>Run a compliance scan</small></span><ArrowUpRight size={16} /></button><button className="shortcut-row" onClick={() => onNavigate('rules')}><span className="shortcut-icon shortcut-purple"><BookOpenText size={17} /></span><span><strong>Review brand rules</strong><small>{dashboard?.rule_count ?? 0} active guideline clauses</small></span><ArrowUpRight size={16} /></button><button className="shortcut-row" onClick={() => onNavigate('audit')}><span className="shortcut-icon shortcut-blue"><Fingerprint size={17} /></span><span><strong>Inspect audit trail</strong><small>Trace accountable decisions</small></span><ArrowUpRight size={16} /></button><div className="shortcut-note"><Sparkles size={14} /><span>AI verification is grounded in approved rules and is optional. Deterministic checks run independently.</span></div></section></div>
  </div>
}

function QuickCopyCheck() {
  const sample = 'We are the #1 fastest platform to boost revenue by 400%. Our revolutionary plan is only $19/month — save 30% today!';
  const [draft, setDraft] = useState(sample)
  const [busy, setBusy] = useState(false)
  const [checked, setChecked] = useState(false)
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.checkCopy>> | null>(null)
  const [localError, setLocalError] = useState('')
  const runCheck = async () => {
    if (!draft.trim()) { setLocalError('Paste or write copy first.'); return }
    setBusy(true); setLocalError('')
    try { setResult(await api.checkCopy(draft)); setChecked(true) }
    catch (error) { setLocalError(error instanceof Error ? error.message : 'The copy check could not run.') }
    finally { setBusy(false) }
  }
  return <section className="panel write-check-panel">
    <div className="write-check-head"><div><div className="section-eyebrow small">01 / WRITE-TIME GUARDRAIL</div><h3>Check the copy before it ships.</h3><p>Paste a headline, product description, campaign message or AI-generated draft. Scan against active workspace rules without leaving the writing flow.</p></div><span className="live-label"><span /> RULES ALWAYS ON</span></div>
    <label className="copy-label" htmlFor="copy-draft">Draft content <span>{draft.length.toLocaleString()} / 15,000</span></label>
    <textarea id="copy-draft" className="copy-draft" maxLength={15000} value={draft} onChange={event => { setDraft(event.target.value); setChecked(false); setLocalError('') }} placeholder="Paste campaign copy, landing-page text or a product claim…" />
    <div className="copy-tools"><span><ShieldCheck size={13} /> Uses active, approved workspace rules</span><button className="btn btn-primary" onClick={() => void runCheck()} disabled={busy || !draft.trim()}>{busy ? <RefreshCw size={15} className="spin" /> : <Sparkles size={15} />}{busy ? 'Checking…' : 'Check this copy'} <ArrowRight size={15} /></button></div>
    {localError && <div className="inline-error copy-error"><AlertCircle size={14} />{localError}</div>}
    {checked && result && <div className="copy-results" aria-live="polite"><div className="copy-results-top"><div><span className={`copy-result-mark ${result.findings_count ? 'has-findings' : 'is-clear'}`}>{result.findings_count ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}</span><div><strong>{result.findings_count ? `${result.findings_count} review signal${result.findings_count === 1 ? '' : 's'} found` : 'No direct rule matches found'}</strong><small>{result.characters_checked.toLocaleString()} characters scanned · {result.mode === 'local_ai_plus_rules' ? 'local AI + deterministic rules' : result.mode === 'local_ai_error_plus_rules' ? 'local AI error · rules still ran' : result.mode === 'cloud_ai_plus_rules' ? 'configured cloud AI + rules' : 'deterministic rules-only mode'}</small></div></div><span className="copy-mode-pill">{result.mode === 'local_ai_plus_rules' ? 'LOCAL AI + RULES' : result.mode === 'local_ai_error_plus_rules' ? 'LOCAL AI ISSUE' : result.mode === 'cloud_ai_plus_rules' ? 'CLOUD AI + RULES' : 'RULES ONLY'}</span></div>
      {result.findings.length > 0 && <div className="copy-finding-list">{result.findings.slice(0, 5).map((finding, index) => <div className="copy-finding" key={`${finding.rule_code || finding.finding_type}-${index}`}><span className={`severity-chip severity-chip-${finding.severity}`}>{finding.severity}</span><div className="copy-finding-body"><div><strong>{finding.rule_title}</strong><small>{finding.rule_code || finding.finding_type} · {finding.source_document || 'Workspace rule'}</small></div><p>{finding.reasoning}</p><div className="copy-fix"><span>Suggested next step</span>{finding.suggested_fix}</div></div></div>)}</div>}
      <p className="copy-limit-note"><Info size={13} /> {result.notice}</p>
    </div>}
  </section>
}

function BrandRiskMap({ onNavigate }: { onNavigate: (view: View) => void }) {
  const risks = [
    { id: 'claims', number: '01', title: 'Claims without proof', detail: 'Rankings, guarantees, quantified outcomes and missing disclaimers.', tag: 'RULE SCAN', tone: 'risk-lime' },
    { id: 'pricing', number: '02', title: 'Stale prices & offers', detail: 'Flag money and discount references for comparison with the current price book.', tag: 'VERIFY SOURCE', tone: 'risk-violet' },
    { id: 'voice', number: '03', title: 'Off-tone or wrong names', detail: 'Unapproved superlatives, pressure language and known product-name variants.', tag: 'RULE SCAN', tone: 'risk-coral' },
    { id: 'visual', number: '04', title: 'Visual & access gaps', detail: 'PDF contrast checks and missing PowerPoint image alt text; verify logos and text over imagery.', tag: 'MIXED CHECK', tone: 'risk-blue' },
  ]
  return <section className="panel risk-map-panel"><div className="risk-map-head"><div><h3>What ContexA checks</h3></div></div><div className="risk-map-list">{risks.map(item => <div className="risk-map-item" key={item.id}><span className={`risk-number ${item.tone}`}>{item.number}</span><div className="risk-map-copy"><strong>{item.title}</strong><p>{item.detail}</p></div><span className={`risk-tag ${item.tone}`}>{item.tag}</span></div>)}</div><div className="risk-map-footer"><div><span className="mini-orbit"/><span>Rules define the standard. Evidence and visual review close the loop.</span></div><button className="text-link" onClick={() => onNavigate('rules')}>Manage standards <ArrowRight size={14}/></button></div></section>
}

function PanelHeading({ title, eyebrow, action }: { title: string; eyebrow?: string; action?: ReactNode }) {
  return <div className="panel-heading"><div>{eyebrow && <div className="section-eyebrow small">{eyebrow}</div>}<h3>{title}</h3></div>{action && <div>{action}</div>}</div>
}
function StatusPill({ status }: { status: string }) {
  const cls = status === 'PUBLISH_READY' ? 'status-publish' : status === 'READY_FOR_SIGNOFF' ? 'status-ready' : 'status-review'
  return <span className={`status-pill ${cls}`}><i />{statusLabel(status)}</span>
}
function ScoreLabel({ score }: { score: number }) { return <span className={`score-label ${score < 60 ? 'score-low' : score < 85 ? 'score-mid' : 'score-high'}`}><span />{score}%</span> }

function LibraryPage({ docs, status, setStatus, search, setSearch, uploading, uploadProgress, onUpload, onOpenReview, onRemove, role }: {
  docs: DocumentRecord[]; status: string; setStatus: (v: string) => void; search: string; setSearch: (v: string) => void
  uploading: boolean; uploadProgress: { current: number; total: number; fileName: string } | null; onUpload: (files: FileList | File[]) => void; onOpenReview: (id: string) => void; onRemove: (doc: DocumentRecord) => void; role: Role
}) {
  const [dragging, setDragging] = useState(false)
  return <div className="page-container"><PageTitle eyebrow="ASSET CONTROL / DOCUMENTS" title="Content library" subtitle="One governed place for every file submitted for review." right={<UploadButton onFiles={onUpload} busy={uploading} label={uploadProgress ? `Scanning ${uploadProgress.current}/${uploadProgress.total}` : 'Upload content'} />} />
    <div className={`drop-zone ${dragging ? 'drop-active' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); if (!uploading) onUpload(e.dataTransfer.files) }}><div className="drop-icon"><UploadCloud size={22} /></div><div className="drop-copy"><strong>{uploading ? `Scanning ${uploadProgress?.current || 1} of ${uploadProgress?.total || 1}: ${uploadProgress?.fileName || 'Preparing file'}…` : 'Drop a document here to start a review'}</strong><span>PDF · DOCX · PPTX · TXT · MD · Images with Tesseract OCR</span></div><span className="drop-size">UP TO 35 MB</span></div>
    <div className="library-toolbar"><div className="library-tabs">{[{v:'all', label:'All assets'}, {v:'IN_REVIEW', label:'In review'}, {v:'READY_FOR_SIGNOFF', label:'Ready for sign-off'}, {v:'PUBLISH_READY', label:'Publish ready'}].map(tab => <button key={tab.v} className={status === tab.v ? 'selected' : ''} onClick={() => setStatus(tab.v)}>{tab.label}{tab.v === 'all' && <small>{docs.length}</small>}</button>)}</div><div className="library-controls"><div className="table-search"><Search size={15} /><input placeholder="Filter files..." value={search} onChange={e => setSearch(e.target.value)} /><kbd>/</kbd></div><button className="btn btn-secondary btn-compact" onClick={() => { setSearch(''); setStatus('all') }}><Filter size={14} /> Reset</button></div></div>
    <section className="panel library-table-panel">{docs.length ? <div className="table-scroll"><table className="data-table library-table"><thead><tr><th>DOCUMENT</th><th>SUBMITTED BY</th><th>DATE ADDED</th><th>FINDINGS</th><th>INTEGRITY</th><th>STATUS</th><th /></tr></thead><tbody>{docs.map(doc => <tr key={doc.id} className="clickable-row" onClick={() => onOpenReview(doc.id)}><td><div className="asset-cell"><span className={`file-type-icon ${doc.filename.endsWith('.pdf') ? 'pdf' : doc.filename.endsWith('.pptx') ? 'ppt' : ''}`}>{doc.filename.endsWith('.pdf') ? <FileText size={17} /> : doc.filename.endsWith('.pptx') ? <FileImage size={17} /> : <FileText size={17} />}</span><span><strong>{doc.filename}</strong><small>{bytesLabel(doc.size_bytes)} · {doc.page_count} page{doc.page_count === 1 ? '' : 's'}</small></span></div></td><td><span className="owner-cell"><span className="tiny-avatar">{initials(doc.creator_name)}</span>{doc.creator_name || 'Unknown'}</span></td><td><span className="date-cell">{prettyDate(doc.created_at)}</span><small className="date-relative">{timeAgo(doc.created_at)}</small></td><td>{doc.critical_count > 0 ? <span className="finding-count count-critical"><AlertCircle size={13} />{doc.critical_count} critical</span> : doc.findings_count > 0 ? <span className="finding-count count-warning"><AlertTriangle size={13} />{doc.findings_count} open</span> : <span className="finding-count count-clear"><CheckCircle2 size={13} />Clear</span>}</td><td><ScoreLabel score={doc.compliance_score} /></td><td><StatusPill status={doc.status} /></td><td><button className="icon-button row-more" title="Delete document" onClick={e => { e.stopPropagation(); if (role === 'Manager' || role === 'Brand Admin') onRemove(doc) }} disabled={role !== 'Manager' && role !== 'Brand Admin'}><MoreHorizontal size={17} /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={FolderOpen} title="No matching content" copy={search ? 'Try a different search or clear the active filters.' : 'Upload a document to populate the content library and start your first compliance review.'} action={search ? <button className="btn btn-secondary" onClick={() => { setSearch(''); setStatus('all') }}>Clear filters</button> : <UploadButton onFiles={onUpload} busy={uploading} large label="Upload content" />} />}</section>
    <div className="library-bottom-note"><Info size={14} /><span>Original uploads are preserved. Suggested fixes are recorded as review decisions; the original file is not silently rewritten.</span></div>
  </div>
}

function ReviewPage({ user, detail, loading, selectedPage, setSelectedPage, previewUrl, previewBusy, canSignOff, canRescan, activeCount, criticalCount, onBack, onAction, onDismiss, onPublish, onRescan, onExport }: {
  user: User; detail: DocumentDetail | null; loading: boolean; selectedPage: number; setSelectedPage: (n: number) => void; previewUrl: string; previewBusy: boolean
  canSignOff: boolean; canRescan: boolean; activeCount: number; criticalCount: number; onBack: () => void
  onAction: (f: Finding, status: 'accepted' | 'edited' | 'dismissed', note?: string) => void; onDismiss: (f: Finding) => void
  onPublish: () => void; publishing: boolean; onRescan: () => void; onExport: (fmt: 'json' | 'csv') => void
}) {
  const [filter, setFilter] = useState('open')
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const selectedFinding = detail?.findings.find(f => f.id === selectedFindingId) || null
  const findings = (detail?.findings || []).filter(f => filter === 'all' || f.status === filter)
  useEffect(() => { setSelectedFindingId(null); setFilter('open') }, [detail?.document.id])
  if (!detail && loading) return <div className="loading-state"><RefreshCw className="spin" size={22} /><span>Preparing spatial review…</span></div>
  if (!detail) return <div className="page-container"><PageTitle eyebrow="CONTENT GOVERNANCE" title="Pre-publication review" subtitle="Select a document from the content library to start reviewing." right={<button className="btn btn-secondary" onClick={onBack}><ChevronLeft size={15} /> Content library</button>} /><EmptyState icon={ClipboardCheck} title="No document selected" copy="Open an uploaded asset from the content library to inspect findings and sign-off status." action={<button className="btn btn-primary" onClick={onBack}>Browse content <ArrowRight size={15} /></button>} /></div>
  const doc = detail.document
  const pages = detail.pages || []
  const currentPage = pages.find(p => p.page === selectedPage) || pages[0]
  const isPdf = doc.filename.toLowerCase().endsWith('.pdf')
  const isPublished = doc.status === 'PUBLISH_READY'
  const sevOrder: Record<string, number> = { critical: 0, warning: 1, info: 2 }
  findings.sort((a, b) => (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3))
  return <div className="review-page">
    <div className="review-heading"><button className="back-link" onClick={onBack}><ChevronLeft size={15} /> Content library</button><div className="review-title-row"><div className="review-file-icon"><FileText size={23} /></div><div className="review-title-copy"><div className="section-eyebrow">PRE-PUBLICATION REVIEW / {doc.id.slice(0, 8).toUpperCase()}</div><h1>{doc.filename}</h1><div className="review-meta"><span>{bytesLabel(doc.size_bytes)}</span><i /><span>{doc.page_count} page{doc.page_count === 1 ? '' : 's'}</span><i /><span>Submitted by {doc.creator_name || 'workspace user'}</span><i /><span>{prettyDate(doc.created_at)}</span></div></div><div className="review-heading-actions"><StatusPill status={doc.status} /><ScoreLabel score={doc.compliance_score} /></div></div>
      <div className="review-actionbar"><div className="review-totals"><span><span className="legend-dot critical-dot" />{criticalCount} critical</span><span><span className="legend-dot warning-dot" />{detail.findings.filter(f => f.status === 'open' && f.severity === 'warning').length} warnings</span><span><span className="legend-dot info-dot" />{detail.findings.filter(f => f.status === 'open' && f.severity === 'info').length} info</span></div><div className="review-buttons">{canRescan && !isPublished && <button className="btn btn-ghost btn-compact" onClick={onRescan}><RefreshCw size={14} /> Re-scan</button>}<div className="export-dropdown"><button className="btn btn-secondary btn-compact" onClick={() => setExportOpen(v => !v)}><Download size={14} /> Export <ChevronDown size={13} /></button>{exportOpen && <div className="dropdown-menu"><button onClick={() => { setExportOpen(false); onExport('json') }}><FileText size={14} /> Governance JSON</button><button onClick={() => { setExportOpen(false); onExport('csv') }}><Download size={14} /> Findings CSV</button></div>}</div>{canSignOff && !isPublished && <button className="btn btn-primary btn-compact" onClick={onPublish} disabled={criticalCount > 0}><ShieldCheck size={14} /> Sign off</button>}{isPublished && <span className="published-lock"><LockKeyhole size={13} /> Approved</span>}</div></div>
    </div>
    <div className="review-layout">
      <aside className="review-left panel"><div className="review-col-head"><div><div className="section-eyebrow small">DOCUMENT OUTLINE</div><h3>Pages <span className="muted-count">{doc.page_count}</span></h3></div><button className="icon-button" title="Document details" onClick={() => { const page = pages[0]; window.alert(`File: ${doc.filename}\nStatus: ${statusLabel(doc.status)}\nText characters: ${detail.content_text.length}\nAI contextual verification: ${detail.ai_configured ? 'Configured' : 'Not configured'}`) }}><Info size={15} /></button></div>
        <div className="page-list">{pages.map((page, index) => <button key={page.page} className={`page-list-item ${selectedPage === page.page ? 'current' : ''}`} onClick={() => setSelectedPage(page.page)}><span className="page-thumb"><FileText size={16} /><small>{String(index + 1).padStart(2, '0')}</small></span><span className="page-list-copy"><strong>Page {page.page}</strong><small>{page.text.trim().slice(0, 50) || 'No extracted text'}{page.text.trim().length > 50 ? '…' : ''}</small></span><span className="page-finding-count">{detail.findings.filter(f => f.page_number === page.page && f.status === 'open').length || '—'}</span></button>)}</div>
        <div className="review-left-bottom"><div className="submitter-identity"><span className="tiny-avatar">{initials(doc.creator_name)}</span><span><small>SUBMITTED BY</small><strong>{doc.creator_name || 'Workspace user'}</strong></span></div><div className="review-left-note"><ShieldCheck size={14} /><span>Source document preserved</span></div></div>
      </aside>
      <section className="document-preview-panel panel"><div className="preview-topbar"><div><span className="preview-dot red" /><span className="preview-dot amber" /><span className="preview-dot green" /><span className="preview-title">{doc.filename}</span></div><div className="preview-tools"><span>PAGE {selectedPage} / {doc.page_count}</span><button className="icon-button" onClick={() => setSelectedPage(Math.max(1, selectedPage - 1))} disabled={selectedPage <= 1}><ChevronLeft size={16} /></button><button className="icon-button" onClick={() => setSelectedPage(Math.min(doc.page_count, selectedPage + 1))} disabled={selectedPage >= doc.page_count}><ChevronRight size={16} /></button></div></div>
        <div className={`document-stage ${isPdf ? 'pdf-stage' : 'text-stage'}`}>{isPdf ? previewUrl ? <img src={previewUrl} alt={`Page ${selectedPage} with active finding overlays`} className="pdf-page-image" /> : previewBusy ? <div className="preview-loading"><RefreshCw size={22} className="spin" /><span>Rendering page & finding overlays…</span></div> : <div className="preview-loading"><FileText size={28} /><span>Preview could not be rendered. Findings remain available at right.</span></div> : <div className="extracted-page"><div className="extracted-page-head"><div className="section-eyebrow">EXTRACTED DOCUMENT TEXT</div><span>{doc.filename.split('.').pop()?.toUpperCase()}</span></div><pre>{(currentPage?.text || detail.content_text) ? <MarkedText text={currentPage?.text || detail.content_text} findings={detail.findings} selectedId={selectedFindingId} onSelect={setSelectedFindingId} /> : 'No readable text extracted.'}</pre></div>}</div>
        <div className="preview-footer"><span><Info size={13} /> {isPdf ? 'Overlay colors represent active findings on this page.' : currentPage?.note || 'Extracted text is shown because precise layout is unavailable for this format.'}</span><div className="preview-legend"><span><i className="critical-rect" />Critical</span><span><i className="warning-rect" />Warning</span><span><i className="info-rect" />Info</span></div></div>
      </section>
      <aside className="findings-panel panel"><div className="findings-heading"><div><div className="section-eyebrow small">RULE-BASED ANALYSIS</div><h3>Active findings <span className="muted-count">{activeCount}</span></h3></div><button className="icon-button" title="Refresh view" onClick={() => setSelectedFindingId(null)}><SlidersHorizontal size={15} /></button></div><div className="findings-filter">{[{v:'open', label:'Open'}, {v:'accepted', label:'Accepted'}, {v:'dismissed', label:'Dismissed'}, {v:'all', label:'All'}].map(tab => <button key={tab.v} className={filter === tab.v ? 'selected' : ''} onClick={() => setFilter(tab.v)}>{tab.label}{tab.v === 'open' && activeCount ? <span>{activeCount}</span> : null}</button>)}</div>
        <div className="findings-scroll">{findings.length ? findings.map(finding => <FindingCard key={finding.id} finding={finding} selected={selectedFindingId === finding.id} onSelect={() => { setSelectedFindingId(finding.id); if (finding.page_number) setSelectedPage(finding.page_number) }} onAction={onAction} onDismiss={onDismiss} canSignOff={canSignOff} isPublished={isPublished} />) : <EmptyState icon={findingFilterIcon(filter)} title={filter === 'open' ? 'No active findings' : `No ${filter} findings`} copy={filter === 'open' ? 'Every rule currently passed or its finding has been resolved. This document can proceed to sign-off.' : 'Review actions will appear here as the team works through findings.'} />}</div>
        <div className="findings-panel-footer"><div><span className={`gate-dot ${criticalCount ? 'gate-blocked' : 'gate-clear'}`} /><span>{criticalCount ? 'Publication blocked' : 'Critical gate passed'}</span></div><small>{criticalCount ? `${criticalCount} critical item${criticalCount === 1 ? '' : 's'} open` : 'Sign-off permissions apply'}</small></div>
      </aside>
    </div>
    <DiscussionPanel documentId={doc.id} user={user} isPublished={isPublished} />
    <div className="review-bottom-hint"><ShieldCheck size={15} /><span>Grounded governance: each confirmed finding maps to an approved rule. A missing/invalid citation is labeled Unverifiable and never treated as a confirmed violation.</span><button className="text-link" onClick={() => window.alert('Scoring: 22 points deducted per open critical finding, 8 per warning and 2 per info finding. PDF contrast checks assume a white background and require human verification when page backgrounds are colored or image-based.')}>How scoring works <ArrowUpRight size={13} /></button></div>
  </div>
}
function findingFilterIcon(filter: string): LucideIcon { return filter === 'accepted' ? CheckCircle2 : filter === 'dismissed' ? XCircle : ClipboardCheck }
function FindingCard({ finding, selected, onSelect, onAction, onDismiss, canSignOff, isPublished }: { finding: Finding; selected: boolean; onSelect: () => void; onAction: (f: Finding, status: 'accepted' | 'edited' | 'dismissed', note?: string) => void; onDismiss: (f: Finding) => void; canSignOff: boolean; isPublished: boolean }) {
  const resolved = finding.status !== 'open'
  const icon = finding.severity === 'critical' ? AlertCircle : finding.severity === 'warning' ? AlertTriangle : Info
  const Icon = icon
  return <article className={`finding-card finding-${finding.severity} ${selected ? 'finding-selected' : ''} ${resolved ? 'finding-resolved' : ''}`} onClick={onSelect}><div className="finding-card-top"><div className="finding-category"><span className={`severity-icon severity-${finding.severity}`}><Icon size={14} /></span><span className={`severity-label severity-text-${finding.severity}`}>{finding.severity}</span><span className="finding-code">{finding.rule_code || 'UNVERIFIABLE'}</span></div>{resolved && <span className={`finding-status status-${finding.status}`}>{finding.status}</span>}</div><h4>{finding.rule_title || 'Unverifiable AI result'}</h4><div className="finding-quote">{finding.flagged_text}</div><p className="finding-reasoning">{finding.reasoning}</p><div className="rule-citation"><BookOpenText size={13} /><span>{finding.rule_code ? `Approved source · ${finding.rule_code}` : 'No verified source citation'}{finding.page_number ? ` · p.${finding.page_number}` : ''}</span><button title="View page" onClick={e => { e.stopPropagation(); onSelect() }}><Eye size={13} /></button></div>
    {!resolved && !isPublished && <div className="finding-suggestion"><div className="suggestion-title"><Sparkles size={13} /> SUGGESTED FIX</div><p>{finding.suggested_fix}</p><div className="finding-actions">{(finding.finding_type === 'claim' || finding.finding_type === 'legal') && finding.severity === 'critical' && !canSignOff ? <span className="permission-note"><LockKeyhole size={12} /> Legal / manager review required</span> : <><button className="btn btn-primary btn-mini" onClick={e => { e.stopPropagation(); onAction(finding, 'edited') }}><Check size={13} /> Record revision</button><button className="btn btn-ghost btn-mini" onClick={e => { e.stopPropagation(); onAction(finding, 'accepted') }} title="Accept finding without applying a rewrite">Accept</button><button className="btn btn-ghost btn-mini dismiss-action" onClick={e => { e.stopPropagation(); onDismiss(finding) }}>Dismiss</button></>}</div></div>}
    {resolved && finding.status === 'dismissed' && finding.dismissal_reason && <div className="dismissal-note"><strong>Dismissal rationale</strong><span>{finding.dismissal_reason}</span></div>}
    {resolved && finding.status === 'edited' && finding.applied_text && <div className="applied-revision"><strong><CheckCircle2 size={13} /> Reviewer revision recorded</strong><span>{finding.applied_text}</span></div>}
  </article>
}

function RulesPage({ rules, role, onCreate, onEdit, onToggle, onImport, importing }: { rules: Rule[]; role: Role; onCreate: () => void; onEdit: (rule: Rule) => void; onToggle: (rule: Rule) => void; onImport: (file: File) => void; importing: boolean }) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [historyRule, setHistoryRule] = useState<Rule | null>(null)
  const [historyRows, setHistoryRows] = useState<any[]>([])
  const [historyBusy, setHistoryBusy] = useState(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)
  const filtered = rules.filter(rule => `${rule.code} ${rule.title} ${rule.rule_clause}`.toLowerCase().includes(query.toLowerCase()) && (category === 'all' || rule.category === category))
  const categories = [...new Set(rules.map(rule => rule.category))].sort()
  const openHistory = async (rule: Rule) => { setHistoryRule(rule); setHistoryRows([]); setHistoryBusy(true); try { setHistoryRows(await api.ruleVersions(rule.id)) } catch { setHistoryRows([]) } finally { setHistoryBusy(false) } }
  return <div className="page-container"><input ref={importInputRef} type="file" accept=".pdf,.docx,.pptx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff,.bmp" hidden onChange={event => { const file = event.target.files?.[0]; if (file) onImport(file); event.currentTarget.value = '' }} /><PageTitle eyebrow="GOVERNANCE / APPROVED GUIDELINES" title="Brand guidelines" subtitle="Turn policies trapped in PDFs and slide decks into reviewable, source-linked rule candidates." right={role === 'Brand Admin' ? <><button className="btn btn-secondary" disabled={importing} onClick={() => importInputRef.current?.click()}>{importing ? <RefreshCw size={15} className="spin" /> : <UploadCloud size={15} />}{importing ? 'Importing guide…' : 'Import PDF / deck'}</button><button className="btn btn-primary" onClick={onCreate}><Plus size={16} /> New rule</button></> : <span className="readonly-pill"><LockKeyhole size={13} /> Read-only access</span>} />
    <div className="guide-import-callout"><span className="guide-import-icon"><BookOpenText size={18} /></span><div><strong>Bring the rules out of the PDF.</strong><p>Import a brand, legal, product or pricing guideline. ContexA extracts candidate clauses and source names. Every imported rule starts paused so a Brand Admin can review wording and enforcement before it affects content.</p></div><span className="guide-import-status">REVIEW FIRST</span></div>
    <div className="rules-summary-grid"><div className="rules-summary-card"><span className="summary-card-icon teal"><ShieldCheck size={18} /></span><div><strong>{rules.filter(r => r.is_active).length}</strong><span>Active rules</span></div><span className="summary-card-foot">ENFORCED</span></div><div className="rules-summary-card"><span className="summary-card-icon red"><AlertCircle size={18} /></span><div><strong>{rules.filter(r => r.is_active && r.severity === 'critical').length}</strong><span>Critical controls</span></div><span className="summary-card-foot">HARD GATE</span></div><div className="rules-summary-card"><span className="summary-card-icon purple"><Sparkles size={18} /></span><div><strong>{rules.filter(r => r.is_active && ['claim', 'tone'].includes(r.category)).length}</strong><span>AI-eligible rules</span></div><span className="summary-card-foot">RAG CANDIDATES</span></div></div>
    <div className="rules-toolbar"><div className="table-search"><Search size={15} /><input placeholder="Search guideline clauses..." value={query} onChange={e => setQuery(e.target.value)} /></div><select value={category} onChange={e => setCategory(e.target.value)} className="select-control"><option value="all">All categories</option>{categories.map(c => <option value={c} key={c}>{c}</option>)}</select><span className="result-count">{filtered.length} rules</span></div>
    <div className="rules-list">{filtered.map(rule => <article className={`rule-row ${!rule.is_active ? 'rule-inactive' : ''}`} key={rule.id}><div className="rule-priority"><span className={`rule-severity-dot ${rule.severity}`} /><span>{rule.severity}</span></div><div className="rule-main"><div className="rule-row-top"><span className="rule-code-pill">{rule.code}</span><span className="category-pill">{rule.category}</span><span className={`rule-state ${rule.is_active ? 'active' : 'paused'}`}><i />{rule.is_active ? 'Active' : 'Paused'}</span></div><h3>{rule.title}</h3><p>{rule.rule_clause}</p><div className="rule-source"><BookOpenText size={13} /><span>{rule.source_document}</span>{rule.pattern ? <><span className="source-divider">·</span><code>Deterministic check</code></> : rule.code.startsWith('IMP-') ? <><span className="source-divider">·</span><code className="needs-pattern">Needs pattern / AI</code></> : null}</div></div><div className="rule-row-actions">{role === 'Brand Admin' && <><button className="btn btn-ghost btn-compact" onClick={() => void openHistory(rule)}><History size={14} /> History</button><button className="btn btn-ghost btn-compact" onClick={() => onEdit(rule)}><Settings2 size={14} /> Edit</button><button className={`toggle-switch ${rule.is_active ? 'on' : ''}`} onClick={() => onToggle(rule)} aria-label={rule.is_active ? 'Deactivate rule' : 'Activate rule'}><i /></button></>}</div></article>)}{!filtered.length && <EmptyState icon={BookOpenText} title="No rules found" copy="Try a different search term or category." />}</div>
    <div className="rules-footnote"><Info size={14} /><span>Imported clauses start paused. Review the source, edit the rule and add a precise deterministic pattern where applicable before activating. Rule changes are audited; re-scan existing content after updates.</span></div>
    {historyRule && <Modal title={`${historyRule.code} · Version history`} eyebrow="APPROVED POLICY RECORD" onClose={() => setHistoryRule(null)}>{historyBusy ? <div className="loading-state"><RefreshCw size={18} className="spin"/> Loading versions…</div> : <div className="rule-version-list">{historyRows.map(version => <article className="rule-version-item" key={version.id}><div><strong>Version {version.version_number}</strong><span>{prettyDate(version.created_at)}</span></div><p>{version.change_note || 'No change note recorded.'}</p><small>{version.snapshot?.title || historyRule.title} · {version.snapshot?.severity || historyRule.severity} · {version.snapshot?.is_active ? 'Active' : 'Paused'}</small></article>)}{!historyRows.length && <p className="empty-inline">No version snapshots have been recorded for this rule yet.</p>}</div>}</Modal>}
  </div>
}

function InsightsPage({ data, role, rules, onChanged, onNotify }: { data: InsightData | null; role: Role; rules: Rule[]; onChanged: () => void; onNotify: (message: string, kind?: 'success' | 'error' | 'info') => void }) {
  const [lab, setLab] = useState<any>(null)
  const [facts, setFacts] = useState<any[]>([])
  const [evidence, setEvidence] = useState<any[]>([])
  const [runs, setRuns] = useState<any[]>([])
  const [sourceDocuments, setSourceDocuments] = useState<any[]>([])
  const [assets, setAssets] = useState<any[]>([])
  const [assetFile, setAssetFile] = useState<File | null>(null)
  const [assetCategory, setAssetCategory] = useState('logo')
  const [assetName, setAssetName] = useState('')
  const [assetBusy, setAssetBusy] = useState(false)
  const [knowledgeQuery, setKnowledgeQuery] = useState('')
  const [knowledgeResults, setKnowledgeResults] = useState<any[]>([])
  const [knowledgeBusy, setKnowledgeBusy] = useState(false)
  const [labBusy, setLabBusy] = useState(false)
  const [evalImportBusy, setEvalImportBusy] = useState(false)
  const evalCsvInputRef = useRef<HTMLInputElement | null>(null)
  const [labError, setLabError] = useState('')
  const [factFormOpen, setFactFormOpen] = useState(false)
  const [factDraft, setFactDraft] = useState({ fact_key: '', fact_type: 'price', entity_name: '', canonical_value: '', currency: 'INR', source_document: '', source_document_id: '', source_quote: '' })
  const [factSaving, setFactSaving] = useState(false)
  const [selectedRuleId, setSelectedRuleId] = useState('')
  const [proposedPattern, setProposedPattern] = useState('')
  const [simulation, setSimulation] = useState<any>(null)
  const [simulationBusy, setSimulationBusy] = useState(false)
  const [applyNote, setApplyNote] = useState('')
  const canAdmin = role === 'Brand Admin'
  const canRunEval = role === 'Brand Admin' || role === 'Manager'

  const loadLab = async () => {
    const [intelligence, factRows, evidenceRows, evaluationRows, sourceRows, assetRows] = await Promise.all([
      api.brandIntelligence(), api.facts(), api.evidenceLedger(8), api.evaluationRuns(), api.documents('', 'all'), api.assets(),
    ])
    setLab(intelligence); setFacts(factRows); setEvidence(evidenceRows); setRuns(evaluationRows); setSourceDocuments(sourceRows); setAssets(assetRows)
  }
  useEffect(() => { let active = true; Promise.all([api.brandIntelligence(), api.facts(), api.evidenceLedger(8), api.evaluationRuns(), api.documents('', 'all'), api.assets()])
    .then(([intelligence, factRows, evidenceRows, evaluationRows, sourceRows, assetRows]) => { if (active) { setLab(intelligence); setFacts(factRows); setEvidence(evidenceRows); setRuns(evaluationRows); setSourceDocuments(sourceRows); setAssets(assetRows) } })
    .catch(error => { if (active) setLabError(error instanceof Error ? error.message : 'Could not load the intelligence lab.') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!selectedRuleId && rules.length) {
      const initial = rules.find(rule => rule.code === 'TERM-001' && rule.pattern) || rules.find(rule => rule.pattern)
      if (initial) { setSelectedRuleId(initial.id); setProposedPattern(initial.pattern || '') }
    }
  }, [rules, selectedRuleId])

  const importEvaluationLabels = async (file: File) => {
    setEvalImportBusy(true); setLabError('')
    try {
      const result = await api.importEvaluationCases(file)
      onNotify(`Evaluation labels imported: ${result.created} new, ${result.updated} updated. Total ${result.total}.`)
      await loadLab()
    } catch (error) { setLabError(error instanceof Error ? error.message : 'Evaluation label import failed.') }
    finally { setEvalImportBusy(false) }
  }

  const runBenchmark = async () => {
    setLabBusy(true); setLabError('')
    try {
      if (canAdmin) await api.seedEvaluation()
      const result = await api.runEvaluation()
      await loadLab()
      setLab((prev: any) => prev ? { ...prev, latest_evaluation: { id: result.id, precision: result.precision, recall: result.recall, f1_score: result.f1_score, case_count: result.case_count, created_at: new Date().toISOString() } } : prev)
    } catch (error) { setLabError(error instanceof Error ? error.message : 'Benchmark could not run.') }
    finally { setLabBusy(false) }
  }

  const uploadBrandAsset = async (event: FormEvent) => {
    event.preventDefault(); if (!assetFile) return
    setAssetBusy(true); setLabError('')
    try { await api.uploadAsset(assetFile, assetCategory, assetName || undefined); setAssetFile(null); setAssetName(''); await loadLab(); onChanged() }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Asset upload failed.') }
    finally { setAssetBusy(false) }
  }
  const approveBrandAsset = async (id: string) => {
    setLabError(''); try { await api.approveAsset(id); await loadLab(); onChanged() }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Asset approval failed.') }
  }
  const downloadBrandAsset = async (asset: any) => {
    try { const blob = await api.downloadAsset(asset.id); saveBlob(blob, asset.filename || `${asset.name}.asset`) }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Asset download failed.') }
  }
  const searchKnowledge = async (event: FormEvent) => {
    event.preventDefault(); if (!knowledgeQuery.trim()) return
    setKnowledgeBusy(true); setLabError('')
    try { const result = await api.searchGuidelines(knowledgeQuery); setKnowledgeResults(result.results || []) }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Guideline search failed.') }
    finally { setKnowledgeBusy(false) }
  }
  const rebuildEmbeddings = async () => {
    setLabBusy(true); setLabError('')
    try { const result = await api.rebuildEmbeddings(); onNotify(`${result.rules_rebuilt} rules and ${result.chunks_rebuilt} guideline chunks re-indexed using ${result.embedding_model}.`); await loadLab() }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Embedding rebuild failed.') }
    finally { setLabBusy(false) }
  }

  const saveFact = async (event: FormEvent) => {
    event.preventDefault(); setFactSaving(true); setLabError('')
    try {
      const payload = { ...factDraft, source_document_id: factDraft.source_document_id || undefined }
      await api.createFact(payload)
      setFactDraft({ fact_key: '', fact_type: 'price', entity_name: '', canonical_value: '', currency: 'INR', source_document: '', source_document_id: '', source_quote: '' })
      setFactFormOpen(false); await loadLab(); onChanged()
    } catch (error) { setLabError(error instanceof Error ? error.message : 'Could not save approved fact.') }
    finally { setFactSaving(false) }
  }

  const approveFact = async (id: string) => {
    setLabError('')
    try { await api.approveFact(id); await loadLab(); onChanged() }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Could not approve fact.') }
  }

  const simulate = async () => {
    if (!selectedRuleId || !proposedPattern.trim()) return
    setSimulationBusy(true); setLabError('')
    try { setSimulation(await api.simulatePolicy(selectedRuleId, proposedPattern)) }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Policy simulation failed.') }
    finally { setSimulationBusy(false) }
  }

  const applySimulation = async () => {
    if (!simulation || applyNote.trim().length < 8) return
    setSimulationBusy(true); setLabError('')
    try { await api.applyPolicySimulation(simulation.id, applyNote); setSimulation(null); setApplyNote(''); onChanged(); await loadLab() }
    catch (error) { setLabError(error instanceof Error ? error.message : 'Could not apply simulated policy.') }
    finally { setSimulationBusy(false) }
  }

  if (!data) return <div className="loading-state"><RefreshCw className="spin" size={22} /><span>Calculating governance insights…</span></div>
  const maxCategory = Math.max(1, ...Object.values(data.findings_by_category))
  const latestEval = lab?.latest_evaluation || runs[0]
  return <div className="page-container">
    <PageTitle eyebrow="GOVERNANCE / MEASUREMENT" title="Insights & rule clarity" subtitle="Understand recurring risks, evidence quality and brand-policy health." right={<span className="live-label"><span /> LIVE WORKSPACE DATA</span>} />

    <section className="intelligence-lab panel">
      <div className="intelligence-lab-heading"><div><div className="section-eyebrow">CONTEXTA INTELLIGENCE</div><h2>Brand Intelligence Lab</h2><p>Source-of-truth coverage, evidence quality and measured detection performance.</p></div><div className="intelligence-heading-actions"><span className="quiet-badge">{lab ? 'Connected to workspace data' : 'Loading workspace data'}</span>{canAdmin && <><input ref={evalCsvInputRef} type="file" accept=".csv,text/csv" hidden onChange={event => { const file = event.currentTarget.files?.[0]; if (file) void importEvaluationLabels(file); event.currentTarget.value = '' }} /><button className="btn btn-secondary btn-compact" disabled={evalImportBusy} onClick={() => evalCsvInputRef.current?.click()}>{evalImportBusy ? <RefreshCw size={14} className="spin"/> : <UploadCloud size={14}/>} {evalImportBusy ? 'Importing…' : 'Import labels'}</button></>}<button className="btn btn-secondary btn-compact" onClick={() => { setLabError(''); void loadLab().catch(e => setLabError(e instanceof Error ? e.message : 'Refresh failed.')) }}><RefreshCw size={14}/> Refresh</button></div></div>
      {labError && <div className="inline-error intelligence-error"><AlertCircle size={14}/>{labError}</div>}
      <div className="intelligence-metrics">
        <div className="intelligence-metric"><span>Approved facts</span><strong>{lab?.facts?.approved ?? '—'}</strong><small>{lab?.facts?.draft ?? 0} awaiting approval · {lab?.facts?.expired_or_stale ?? 0} stale</small></div>
        <div className="intelligence-metric"><span>Evidence links</span><strong>{lab?.evidence?.total ?? '—'}</strong><small>{lab?.evidence?.grounding_rate == null ? 'No evidence records yet' : `${lab.evidence.grounding_rate}% grounded or linked`}</small></div>
        <div className="intelligence-metric"><span>Open review tasks</span><strong>{lab?.review_tasks?.open ?? '—'}</strong><small>Automatically routed by risk category</small></div>
        <div className="intelligence-metric"><span>Latest benchmark</span><strong>{latestEval ? `${Math.round(latestEval.f1_score * 100)}%` : '—'}</strong><small>{latestEval ? `${latestEval.case_count} test cases · F1 score` : 'No evaluation run yet'}</small></div>
      </div>
      <div className="intelligence-lab-footer"><div className="evaluation-summary"><span>Precision <b>{latestEval ? `${Math.round(latestEval.precision * 100)}%` : '—'}</b></span><span>Recall <b>{latestEval ? `${Math.round(latestEval.recall * 100)}%` : '—'}</b></span><span>F1 <b>{latestEval ? `${Math.round(latestEval.f1_score * 100)}%` : '—'}</b></span></div><button className="btn btn-primary" onClick={() => void runBenchmark()} disabled={!canRunEval || labBusy}>{labBusy ? <RefreshCw size={14} className="spin"/> : <Activity size={14}/>} {labBusy ? 'Evaluating…' : 'Run benchmark'}</button></div>
      {!canAdmin && !runs.length && <p className="intelligence-hint">A Brand Admin must initialize the benchmark cases before a Manager can run the evaluation.</p>}
    </section>

    <div className="intelligence-tools-grid">
      <section className="panel intelligence-tool-card">
        <div className="tool-card-heading"><div><div className="section-eyebrow">SOURCE OF TRUTH</div><h3>Approved fact registry</h3></div><button className="btn btn-secondary btn-compact" onClick={() => setFactFormOpen(v => !v)} disabled={!canAdmin}><Plus size={14}/>{factFormOpen ? 'Close' : 'Add fact'}</button></div>
        <p className="tool-card-copy">Approved prices, product names and claims become comparison sources during document scans.</p>
        {factFormOpen && <form className="fact-create-form" onSubmit={saveFact}>
          <div className="form-grid-two"><label className="field-label">Fact key<input required value={factDraft.fact_key} onChange={e => setFactDraft(v => ({ ...v, fact_key: e.target.value }))} placeholder="product.pro.monthly_price"/></label><label className="field-label">Type<select value={factDraft.fact_type} onChange={e => setFactDraft(v => ({ ...v, fact_type: e.target.value }))}><option value="price">Price</option><option value="product_name">Product name</option><option value="claim">Approved claim</option><option value="campaign">Campaign</option><option value="other">Other</option></select></label></div>
          <div className="form-grid-two"><label className="field-label">Entity<input value={factDraft.entity_name} onChange={e => setFactDraft(v => ({ ...v, entity_name: e.target.value }))} placeholder="Product / campaign name"/></label><label className="field-label">Approved value<input required value={factDraft.canonical_value} onChange={e => setFactDraft(v => ({ ...v, canonical_value: e.target.value }))} placeholder="₹54,999/month"/></label></div>
          <label className="field-label">Link an uploaded source document<select value={factDraft.source_document_id} onChange={e => { const id = e.target.value; const doc = sourceDocuments.find((item: any) => item.id === id); setFactDraft(v => ({ ...v, source_document_id: id, source_document: doc?.filename || (id ? v.source_document : '') })) }}><option value="">Manual source attestation (no uploaded document)</option>{sourceDocuments.map((doc: any) => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label>
          {!factDraft.source_document_id && <label className="field-label">Source name<input required value={factDraft.source_document} onChange={e => setFactDraft(v => ({ ...v, source_document: e.target.value }))} placeholder="Approved FY27 price book"/></label>}
          <label className="field-label">Supporting quotation<textarea required minLength={8} rows={2} value={factDraft.source_quote} onChange={e => setFactDraft(v => ({ ...v, source_quote: e.target.value }))} placeholder={factDraft.source_document_id ? "Paste an exact quotation from the selected document. It will be checked against extracted text…" : "Paste the approved source wording and record it as a manual attestation…"}/></label>
          {factDraft.source_document_id && <small className="field-hint">The quotation must appear in the selected document's extracted text. Manually attested sources are not automatically verified.</small>}
          <button className="btn btn-primary" disabled={factSaving}>{factSaving ? 'Saving…' : 'Save as draft fact'}</button>
        </form>}
        <div className="fact-list">{facts.slice(0, 6).map(fact => <div className="fact-row" key={fact.id}><div className="fact-main"><strong>{fact.entity_name || fact.fact_key}</strong><span>{fact.fact_key} · v{fact.version_number}</span><small>{fact.canonical_value} · {fact.source_document}</small><small className={fact.source_verified ? "source-proof verified" : "source-proof manual"}>{fact.source_verified ? "Source quotation verified" : "Manual source attestation"}</small></div><span className={`fact-status fact-${fact.status}`}>{fact.status}</span>{fact.status === 'draft' && canAdmin && <button className="btn btn-secondary btn-compact" onClick={() => void approveFact(fact.id)}>Approve</button>}</div>)}{!facts.length && <p className="empty-inline">No source facts yet. Add a price, product name or approved claim.</p>}</div>
      </section>

      <section className="panel intelligence-tool-card">
        <div className="tool-card-heading"><div><div className="section-eyebrow">POLICY CHANGE CONTROL</div><h3>Simulate before applying</h3></div><span className="quiet-badge">No live change</span></div>
        <p className="tool-card-copy">Test a proposed rule pattern against the workspace's existing documents before changing active policy.</p>
        <label className="field-label">Rule<select value={selectedRuleId} onChange={e => { const rule = rules.find(item => item.id === e.target.value); setSelectedRuleId(e.target.value); setProposedPattern(rule?.pattern || ''); setSimulation(null) }}><option value="">Select a rule</option>{rules.map(rule => <option key={rule.id} value={rule.id}>{rule.code} · {rule.title}</option>)}</select></label>
        <label className="field-label">Proposed regular expression<input value={proposedPattern} onChange={e => { setProposedPattern(e.target.value); setSimulation(null) }} placeholder={String.raw`\bexample\b`}/></label>
        <button className="btn btn-secondary" onClick={() => void simulate()} disabled={!canAdmin || !selectedRuleId || !proposedPattern.trim() || simulationBusy}>{simulationBusy ? 'Simulating…' : 'Run impact simulation'} <ArrowRight size={14}/></button>
        {simulation && <div className="simulation-result"><div><span>Documents affected</span><strong>{simulation.documents_affected} / {simulation.documents_scanned}</strong></div><div><span>Matched occurrences</span><strong>{simulation.matches_found}</strong></div>{simulation.sample_matches?.slice(0, 3).map((item: any, index: number) => <p key={index}><b>{item.filename}</b><small>{item.excerpt}</small></p>)}{canAdmin && <><label className="field-label">Change note required to apply<input value={applyNote} onChange={e => setApplyNote(e.target.value)} placeholder="Explain the policy change…"/></label><button className="btn btn-primary" disabled={applyNote.trim().length < 8 || simulationBusy} onClick={() => void applySimulation()}>Apply as new rule version</button></>}</div>}
      </section>
    </div>

    <div className="intelligence-tools-grid">
      <section className="panel intelligence-tool-card">
        <div className="tool-card-heading"><div><div className="section-eyebrow">APPROVED IDENTITY</div><h3>Brand asset registry</h3></div><span className="quiet-badge">{assets.length} assets</span></div>
        <p className="tool-card-copy">Store approved logos, campaign assets, fonts and reference artwork with version and approval history.</p>
        {canAdmin && <form className="fact-create-form" onSubmit={uploadBrandAsset}>
          <div className="form-grid-two"><label className="field-label">Asset name<input value={assetName} onChange={e => setAssetName(e.target.value)} placeholder="Primary logo / campaign lockup"/></label><label className="field-label">Category<select value={assetCategory} onChange={e => setAssetCategory(e.target.value)}>{['logo','color_palette','font','template','campaign','product_image','other'].map(value => <option key={value} value={value}>{value.replaceAll('_',' ')}</option>)}</select></label></div>
          <label className="field-label">Asset file<input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.pptx,.ttf,.otf,.woff,.woff2" onChange={e => setAssetFile(e.target.files?.[0] || null)}/></label>
          <button className="btn btn-primary" disabled={!assetFile || assetBusy}>{assetBusy ? <RefreshCw size={14} className="spin"/> : <UploadCloud size={14}/>} Upload as draft asset</button>
        </form>}
        <div className="fact-list">{assets.slice(0,8).map(asset => <div className="fact-row" key={asset.id}><div className="fact-main"><strong>{asset.name}</strong><span>{asset.category} · v{asset.version_number}</span><small>{asset.filename} · {bytesLabel(asset.size_bytes || 0)}</small><small className="source-proof">SHA-256: {(asset.sha256 || '').slice(0,16)}…</small></div><span className={`fact-status fact-${asset.status}`}>{asset.status}</span><button className="btn btn-secondary btn-compact" onClick={() => void downloadBrandAsset(asset)}><Download size={13}/></button>{asset.status === 'draft' && (canAdmin || role === 'SME / Legal') && <button className="btn btn-secondary btn-compact" onClick={() => void approveBrandAsset(asset.id)}>Approve</button>}</div>)}{!assets.length && <p className="empty-inline">No approved brand assets yet. Upload a logo, font or template.</p>}</div>
      </section>
      <section className="panel intelligence-tool-card">
        <div className="tool-card-heading"><div><div className="section-eyebrow">RETRIEVAL QUALITY</div><h3>Guideline knowledge search</h3></div><span className="quiet-badge">Hybrid search</span></div>
        <p className="tool-card-copy">Search imported guideline chunks with source page references, heading context and lexical/vector relevance.</p>
        <form className="fact-create-form" onSubmit={searchKnowledge}><label className="field-label">Search approved guidance<input value={knowledgeQuery} onChange={e => setKnowledgeQuery(e.target.value)} placeholder="e.g. discount claims must include terms"/></label><div className="form-actions"><button className="btn btn-secondary" disabled={knowledgeBusy || knowledgeQuery.trim().length < 2}>{knowledgeBusy ? <RefreshCw size={13} className="spin"/> : <Search size={13}/>} Search guidelines</button>{canAdmin && <button type="button" className="btn btn-secondary" disabled={labBusy} onClick={() => void rebuildEmbeddings()}><RefreshCw size={13}/> Rebuild embeddings</button>}</div></form>
        <div className="evidence-ledger-list">{knowledgeResults.slice(0,6).map(item => <div className="evidence-ledger-row" key={item.id}><span className="evidence-dot verified"/><div><strong>{item.heading || item.source_document}</strong><p>{item.content}</p><small>{item.source_document} · page {item.page_number} · score {item.score} · {item.embedding_model}</small></div></div>)}{!knowledgeResults.length && <p className="empty-inline">Import a guideline and search its indexed clauses here.</p>}</div>
      </section>
    </div>

    <div className="intelligence-tools-grid evidence-eval-grid">
      <section className="panel intelligence-tool-card"><div className="tool-card-heading"><div><div className="section-eyebrow">PROVENANCE</div><h3>Evidence ledger</h3></div><span className="quiet-badge">Latest links</span></div>
        <div className="evidence-ledger-list">{evidence.slice(0, 6).map(item => <div className="evidence-ledger-row" key={item.id}><span className={`evidence-dot ${item.verification_status === 'grounded' || item.verification_status === 'linked' ? 'verified' : 'unverified'}`} /><div><strong>{item.source_label}</strong><p>“{item.content_quote}”</p><small>{item.verification_status} · source v{item.source_version ?? '—'}</small></div></div>)}{!evidence.length && <p className="empty-inline">Evidence links appear after documents are scanned.</p>}</div>
      </section>
      <section className="panel intelligence-tool-card"><div className="tool-card-heading"><div><div className="section-eyebrow">QUALITY MEASUREMENT</div><h3>Evaluation history</h3></div><span className="quiet-badge">Deterministic benchmark</span></div>
        <div className="evaluation-history-list">{runs.slice(0, 5).map(run => <div className="evaluation-history-row" key={run.id}><span>{prettyDate(run.created_at)}</span><strong>{Math.round(run.f1_score * 100)}% F1</strong><small>{run.case_count} cases · P {Math.round(run.precision * 100)}% · R {Math.round(run.recall * 100)}%</small></div>)}{!runs.length && <p className="empty-inline">Run the benchmark to establish a reproducible baseline.</p>}</div>
      </section>
    </div>

    <div className="insights-hero"><div className="insights-hero-left"><div className="section-eyebrow">GOVERNANCE CLARITY INDEX</div><div className="gci-value">{data.rule_clarity_index}<small>/100</small></div><p>Workspace clarity score based on how often triggered findings are dismissed.</p><div className="gci-bar"><span style={{ width: `${data.rule_clarity_index}%` }} /></div><div className="gci-formula"><code>GCI = 100 − (dismissed ÷ triggered × 100)</code><span>Directional signal</span></div></div><div className="insights-hero-stats"><div><strong>{data.total_findings}</strong><span>Total triggered findings</span></div><div><strong>{data.dismissed_findings}</strong><span>Dismissed with rationale</span></div><div><strong>{data.rules.filter(r => r.status === 'Candidate for clarification').length}</strong><span>Rules flagged for clarity</span></div></div></div>
    <div className="insights-grid"><section className="panel"><PanelHeading eyebrow="FINDINGS MIX" title="Findings by category" /><div className="category-bars">{Object.entries(data.findings_by_category).sort((a, b) => b[1] - a[1]).map(([key, value]) => <div className="category-bar-row" key={key}><div className="category-bar-title"><span>{key}</span><strong>{value}</strong></div><div className="wide-meter"><span style={{ width: `${value / maxCategory * 100}%` }} /></div></div>)}{!Object.keys(data.findings_by_category).length && <p className="empty-inline">Category trends appear after the first document scan.</p>}</div></section><section className="panel"><PanelHeading eyebrow="CLARIFICATION SIGNALS" title="How to read the index" /><div className="clarity-guide"><div><span className="clarity-marker good"><Check size={14} /></span><span><strong>80–100 · Healthy</strong><small>Low dismissal rate suggests consistent interpretation of the rule.</small></span></div><div><span className="clarity-marker watch"><AlertTriangle size={14} /></span><span><strong>60–79 · Monitor</strong><small>Review recurring overrides and add examples where needed.</small></span></div><div><span className="clarity-marker bad"><AlertCircle size={14} /></span><span><strong>Below 60 · Clarify</strong><small>Candidate for brand owner review. A low score is not proof the rule itself is incorrect.</small></span></div></div></section></div>
    <section className="panel insight-rules"><PanelHeading eyebrow="RULE-LEVEL SIGNAL" title="Guideline clarity by clause" action={<span className="quiet-badge">{data.rules.length} rules tracked</span>} /><div className="table-scroll"><table className="data-table"><thead><tr><th>RULE</th><th>TRIGGERED</th><th>DISMISSED</th><th>GCI</th><th>ASSESSMENT</th></tr></thead><tbody>{data.rules.map(rule => <tr key={rule.id}><td><div className="rule-table-cell"><span>{rule.code}</span><div><strong>{rule.title}</strong><small>{rule.category}</small></div></div></td><td>{rule.triggered}</td><td>{rule.dismissed}</td><td><ScoreLabel score={rule.gci} /></td><td><span className={`clarity-status ${rule.status === 'Candidate for clarification' ? 'clarity-alert' : rule.status === 'Healthy' ? 'clarity-good' : 'clarity-empty'}`}><i />{rule.status}</span></td></tr>)}</tbody></table></div></section>
    <div className="insight-disclaimer"><Info size={14} /><span>Only approved fact records are used for source comparisons. The benchmark measures deterministic rule detection against its labelled cases; it does not measure contextual AI or prove external claims. Rule and fact citations preserve historical versions.</span></div>
  </div>
}

function AuditPage({ audit }: { audit: ActivityItem[] }) {
  const [query, setQuery] = useState('')
  const [integrity, setIntegrity] = useState<any>(null)
  const [verifying, setVerifying] = useState(false)
  const filtered = audit.filter(a => `${a.actor_name} ${a.action} ${a.entity_type} ${a.entity_id} ${JSON.stringify(a.detail)}`.toLowerCase().includes(query.toLowerCase()))
  async function verifyChain() { setVerifying(true); try { setIntegrity(await api.verifyAudit()) } catch (error) { setIntegrity({ valid: false, error: error instanceof Error ? error.message : 'Verification failed.' }) } finally { setVerifying(false) } }
  return <div className="page-container"><PageTitle eyebrow="GOVERNANCE / TRACEABILITY" title="Audit trail" subtitle="A traceable history of submissions, reviewer decisions, rule changes and sign-offs." right={<button className="btn btn-secondary btn-compact" onClick={() => void verifyChain()} disabled={verifying}>{verifying ? <RefreshCw size={13} className="spin" /> : <ShieldCheck size={13} />}{verifying ? 'Verifying…' : 'Verify integrity'}</button>} />
    {integrity && <div className={`audit-integrity-result ${integrity.valid ? 'valid' : 'invalid'}`} role="status"><ShieldCheck size={17}/><span><strong>{integrity.valid ? 'Audit hash chain verified' : 'Audit verification needs attention'}</strong><small>{integrity.error || `${integrity.events_verified} chained events verified · ${integrity.legacy_events_unhashed} legacy events without historical hashes`}</small></span></div>}
    <div className="audit-callout"><span className="audit-callout-icon"><ShieldCheck size={20} /></span><div><strong>Accountability by design</strong><p>Each new event is linked to the preceding event with a SHA-256 hash. This is tamper-evident application logging, not an external immutable ledger.</p></div><span className="audit-encrypted"><LockKeyhole size={13} /> ROLE-GATED</span></div>
    <div className="audit-toolbar"><div className="table-search"><Search size={15} /><input placeholder="Search by actor, action or target..." value={query} onChange={e => setQuery(e.target.value)} /></div><span className="result-count">{filtered.length} events</span></div>
    <section className="panel audit-table-panel">{filtered.length ? <div className="table-scroll"><table className="data-table audit-table"><thead><tr><th>EVENT</th><th>ACTOR</th><th>TARGET</th><th>DETAIL</th><th>TIMESTAMP</th></tr></thead><tbody>{filtered.map(event => <tr key={event.id}><td><div className="audit-event-cell"><span className={`audit-action-icon ${event.action.includes('dismiss') ? 'danger' : event.action.includes('publish') ? 'success' : ''}`}><Activity size={15} /></span><span><strong>{actionLabel(event.action)}</strong><small>{event.entity_type}</small></span></div></td><td><span className="owner-cell"><span className="tiny-avatar">{initials(event.actor_name)}</span>{event.actor_name}</span></td><td><code className="entity-code">{event.entity_id.slice(0, 12)}</code></td><td><span className="audit-detail">{Object.entries(event.detail || {}).map(([k, v]) => `${k}: ${String(v)}`).join(' · ') || '—'}</span></td><td><span className="date-cell">{prettyDate(event.created_at)}</span><small className="date-relative">{new Date(event.created_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</small></td></tr>)}</tbody></table></div> : <EmptyState icon={Fingerprint} title="No audit events found" copy={query ? 'Try broadening your search.' : 'Events will appear here when users upload documents or make governance decisions.'} />}</section>
    <div className="audit-bottom"><span><LockKeyhole size={13} /> Audit records are restricted to authenticated workspace members.</span><span>RETENTION / APPLICATION DEFAULT</span></div>
  </div>
}

function TeamPage({ team, role, onAdd }: { team: User[]; role: Role; onAdd: () => void }) {
  const roleInfo: Record<string, string> = { 'Brand Admin': 'Manage rules, people, settings and sign-off.', Manager: 'Review findings and provide final sign-off.', 'SME / Legal': 'Review high-risk claims and legal gates.', Creator: 'Submit content and work through findings.' }
  return <div className="page-container"><PageTitle eyebrow="ADMINISTRATION / ACCESS CONTROL" title="Team & access" subtitle="Workspace identities and role-based governance permissions." right={role === 'Brand Admin' ? <button className="btn btn-primary" onClick={onAdd}><Plus size={16} /> Invite member</button> : <span className="readonly-pill"><LockKeyhole size={13} /> Admin only</span>} />
    <div className="team-banner"><div className="team-banner-icon"><Users size={22} /></div><div><strong>Least-privilege access</strong><p>High-risk claims require Manager, SME / Legal, or Brand Admin review. Final publication sign-off is restricted to authorized roles.</p></div><span className="role-count">{team.length} MEMBERS</span></div>
    <div className="role-grid">{[{role:'Creator', icon:FileText, className:'blue'}, {role:'Manager', icon:BriefcaseBusiness, className:'purple'}, {role:'SME / Legal', icon:ShieldCheck, className:'amber'}, {role:'Brand Admin', icon:LockKeyhole, className:'teal'}].map(item => { const Icon = item.icon; return <div className="role-card" key={item.role}><span className={`role-card-icon ${item.className}`}><Icon size={18} /></span><strong>{item.role}</strong><p>{roleInfo[item.role]}</p><span className="role-card-foot"><CheckCircle2 size={13} /> Permission set enforced</span></div> })}</div>
    <section className="panel team-list-panel"><PanelHeading eyebrow="WORKSPACE DIRECTORY" title="Members" action={<span className="quiet-badge">{team.length} active accounts</span>} />{team.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>MEMBER</th><th>ROLE</th><th>ACCOUNT STATUS</th><th>ACCESS DESCRIPTION</th></tr></thead><tbody>{team.map(member => <tr key={member.id}><td><div className="team-member-cell"><span className={`avatar team-avatar role-${member.role.toLowerCase().replaceAll(/[^a-z]/g, '')}`}>{initials(member.name)}</span><span><strong>{member.name}</strong><small>{member.email}</small></span></div></td><td><span className="team-role-pill">{member.role}</span></td><td><span className="status-pill status-publish"><i />Active</span></td><td><span className="role-description-cell">{roleInfo[member.role] || 'Workspace member'}</span></td></tr>)}</tbody></table></div> : <EmptyState icon={Users} title="Team directory unavailable" copy="Sign in as Brand Admin to manage members." />}</section>
    {role !== 'Brand Admin' && <p className="admin-only-note"><LockKeyhole size={14} /> Only a Brand Admin can invite members or change roles.</p>}
  </div>
}

function SettingsPage({ uiStyle, onUiStyleChange, settings, user, motionLevel, onMotionLevelChange, onLogout }: { uiStyle: UiStyle; onUiStyleChange: (style: UiStyle) => void; settings: any; user: User; motionLevel: MotionLevel; onMotionLevelChange: (level: MotionLevel) => void; onLogout: () => void }) {
  const backend = settings?.backend
  const localAI = backend?.local_ai
  const modelInstalled = Boolean(localAI?.model_available)
  const localReady = Boolean(modelInstalled && localAI?.verification_enabled !== false)
  const verificationDisabled = localAI?.verification_enabled === false
  const serviceUp = Boolean(localAI?.service_available)
  const modelName = localAI?.model || 'nemotron-mini:4b'
  const installCommand = `ollama pull ${modelName}`
  const [copiedCommand, setCopiedCommand] = useState(false)
  const [exportingWorkspace, setExportingWorkspace] = useState(false)
  const [workspacePassword, setWorkspacePassword] = useState('')
  const [workspaceConfirmation, setWorkspaceConfirmation] = useState('')
  const [workspaceActionMessage, setWorkspaceActionMessage] = useState('')
  const [deletingWorkspace, setDeletingWorkspace] = useState(false)
  async function exportWorkspace() {
    setExportingWorkspace(true); setWorkspaceActionMessage('')
    try { const blob = await api.exportWorkspace(); saveBlob(blob, 'contexa-workspace-export.zip'); setWorkspaceActionMessage('Workspace export downloaded.') }
    catch (error) { setWorkspaceActionMessage(error instanceof Error ? error.message : 'Workspace export failed.') }
    finally { setExportingWorkspace(false) }
  }
  async function deleteWorkspace() {
    if (!settings?.workspace?.name || workspaceConfirmation !== settings.workspace.name) return
    setDeletingWorkspace(true); setWorkspaceActionMessage('')
    try { await api.deleteWorkspace(workspacePassword, workspaceConfirmation); onLogout() }
    catch (error) { setWorkspaceActionMessage(error instanceof Error ? error.message : 'Workspace deletion failed.') }
    finally { setDeletingWorkspace(false) }
  }
  async function copyInstallCommand() {
    try {
      await navigator.clipboard.writeText(installCommand)
      setCopiedCommand(true)
      window.setTimeout(() => setCopiedCommand(false), 1800)
    } catch {
      setCopiedCommand(false)
    }
  }
  return <div className="page-container"><PageTitle eyebrow="ADMINISTRATION / WORKSPACE" title="Settings" subtitle="Style, motion and local verification." />
    <div className="offline-mode-note"><ShieldCheck size={16} /><span><strong>Offline-ready.</strong> Rules, review, audit and exports work without AI. Local contextual analysis is optional and clearly labelled when unavailable.</span></div>
    <section className="panel settings-panel style-picker-panel"><PanelHeading eyebrow="VISUAL SYSTEM / INTERFACE" title="Interface style" action={<span className="quiet-badge"><Palette size={12} /> Saved in this browser</span>} /><p className="theme-picker-description">Each option changes the workspace structure, typography, surfaces and component treatment—not only its colours.</p><div className="theme-options style-options">{UI_STYLES.map(option => <button key={option.id} className={`theme-option style-option-${option.id} ${uiStyle === option.id ? 'selected' : ''}`} aria-pressed={uiStyle === option.id} onClick={() => onUiStyleChange(option.id)}><span className="theme-swatches">{option.swatch.map(color => <i key={color} style={{ background: color }} />)}</span><strong>{option.name}</strong><span className="style-desc">{option.description}</span>{uiStyle === option.id && <span className="theme-active-dot" aria-label="Active"><Check size={12} /></span>}</button>)}</div></section>
    <div className="settings-grid">
      <section className="panel settings-panel motion-profile-panel"><PanelHeading eyebrow="MOTION SYSTEM / ACCESSIBILITY" title="Choose your motion profile" action={<span className="quiet-badge"><Activity size={12} /> Saved in this browser</span>} /><p className="theme-picker-description">Set the intensity of scene and page transitions. Reduced-motion preferences always apply.</p><div className="motion-profile-options">{([{id:'calm',name:'Calm',sub:'Slow spatial motion, quieter transitions',icon:Activity},{id:'studio',name:'Studio',sub:'Balanced object motion and UI feedback',icon:Sparkles},{id:'cinematic',name:'Cinematic',sub:'More pronounced orbital movement and depth',icon:Zap}] as const).map(profile => { const MotionIcon = profile.icon; return <button key={profile.id} className={`motion-profile ${motionLevel === profile.id ? 'selected' : ''}`} aria-pressed={motionLevel === profile.id} onClick={() => onMotionLevelChange(profile.id)}><span className="motion-profile-icon"><MotionIcon size={18} /></span><strong>{profile.name}</strong><small>{profile.sub}</small>{motionLevel === profile.id && <span className="theme-selected-label"><CheckCircle2 size={12} /> Active profile</span>}</button> })}</div><div className="motion-system-footer"><span className="motion-bars"><i/><i/><i/><i/><i/></span><span>Scene motion and interface transitions</span></div></section>
      <section className="panel settings-panel glass-panel">
        <PanelHeading eyebrow="WORKSPACE CONFIGURATION" title="Environment" />
        <div className="setting-row"><div className="setting-icon"><BriefcaseBusiness size={17} /></div><div className="setting-copy"><strong>{settings?.workspace?.name || 'ContexA Studio'}</strong><small>Workspace name</small></div><span className="setting-value">{settings?.workspace?.id || 'ws-contexa-demo'}</span></div>
        <div className="setting-row"><div className="setting-icon"><Activity size={17} /></div><div className="setting-copy"><strong>Local development</strong><small>Runtime environment</small></div><span className="setting-value status-live"><i />{settings?.workspace?.environment || 'development'}</span></div>
        <div className="setting-row"><div className="setting-icon"><DatabaseIcon /></div><div className="setting-copy"><strong>{backend?.database || 'Loading database…'}</strong><small>Persistence layer</small></div><span className="setting-value">CONNECTED</span></div>
        <div className="setting-row"><div className="setting-icon"><UploadCloud size={17} /></div><div className="setting-copy"><strong>Maximum upload size</strong><small>Per document</small></div><span className="setting-value">{backend?.upload_limit_mb ?? 35} MB</span></div>
      </section>

      <section className="panel settings-panel cloudflare-panel">
        <PanelHeading eyebrow="EDGE / STORAGE / ANTI-ABUSE" title="Cloudflare control plane" action={<span className={`connection-pill ${settings?.cloudflare?.edge_gateway_enabled ? 'connected' : 'not-connected'}`}><i />{settings?.cloudflare?.edge_gateway_enabled ? 'Edge configured' : 'Optional'}</span>} />
        <p className="theme-picker-description">Cloudflare can front the static app and API, throttle abusive traffic, validate signup/login challenges, store private uploads, and observe optional model requests. These indicators show configured environment variables—not a live connectivity test.</p>
        <div className="cloudflare-status-grid">
          {[{label:'Workers API edge',value:settings?.cloudflare?.edge_gateway_enabled,detail:'API reverse proxy + per-location throttles'},{label:'Origin lock',value:settings?.cloudflare?.origin_auth_enabled,detail:'Blocks direct origin API bypass'},{label:'R2 object storage',value:settings?.cloudflare?.r2_enabled,detail:'Private S3-compatible document and asset storage'},{label:'Turnstile',value:settings?.cloudflare?.turnstile_enabled,detail:'Server-validated login and signup bot checks'},{label:'AI Gateway',value:settings?.cloudflare?.ai_gateway_enabled,detail:'Optional Claude request observability'}].map(item => <div className="cloudflare-status-item" key={item.label}><span className={`cloudflare-status-indicator ${item.value ? 'is-on' : ''}`} /><div><strong>{item.label}</strong><small>{item.detail}</small></div><b>{item.value ? 'CONFIGURED' : 'NOT SET'}</b></div>)}
        </div>
        <div className="cloudflare-setup-foot"><span>{settings?.cloudflare?.api_url || 'Set PUBLIC_API_URL after deploying the edge gateway.'}</span><a href="https://developers.cloudflare.com/" target="_blank" rel="noreferrer">Cloudflare docs <ExternalLink size={12}/></a></div>
      </section>
      <section className="panel settings-panel cloudflare-panel">
        <PanelHeading eyebrow="TRUST OS / GOVERNANCE READINESS" title="Signed evidence & scheduled monitoring" action={<span className={`connection-pill ${settings?.trust_os?.enabled ? 'connected' : 'not-connected'}`}><i />{settings?.trust_os?.enabled ? 'Modules available' : 'Unavailable'}</span>} />
        <p className="theme-picker-description">These indicators confirm backend configuration only. They do not prove that a Cloudflare Cron has fired, a source is reachable, or a legal rule is current.</p>
        <div className="cloudflare-status-grid">
          {[{label:'Trust Passport signing key',value:settings?.trust_os?.passport_signing_key_configured,detail:'Stable HMAC-SHA256 attestation key'},{label:'Truth Drift scheduler token',value:settings?.trust_os?.scheduled_monitoring_configured,detail:'Worker Cron bearer token configured'},{label:'Trust OS modules',value:settings?.trust_os?.enabled,detail:'Drift, passport, media, agents, twin, Indic, regulatory and incidents'}].map(item => <div className="cloudflare-status-item" key={item.label}><span className={`cloudflare-status-indicator ${item.value ? 'is-on' : ''}`} /><div><strong>{item.label}</strong><small>{item.detail}</small></div><b>{item.value ? 'CONFIGURED' : 'NOT SET'}</b></div>)}
        </div>
      </section>
      <section className="panel settings-panel local-ai-panel">
        <PanelHeading eyebrow="OPTIONAL / NO API KEY REQUIRED" title="Local AI engine" action={<span className={`connection-pill ${localReady ? 'connected' : 'not-connected'}`}><i />{localReady ? 'Model ready' : verificationDisabled ? 'AI disabled' : serviceUp ? 'Model missing' : 'Not running'}</span>} />
        <div className="local-ai-hero">
          <div className="local-ai-emblem"><Cpu size={24} /></div>
          <div className="local-ai-copy"><div className="local-ai-titleline"><strong>Ollama · {modelName}</strong><span className="privacy-tag"><LockKeyhole size={11} /> LOCAL FIRST</span></div>
            <p>{localReady ? 'Local contextual checks are available. Your draft and guideline excerpts are sent to the local model service on this machine, not to a hosted AI provider.' : verificationDisabled && modelInstalled ? 'The local model is installed, but contextual verification is switched off in the backend environment. Enable AI_VERIFICATION_ENABLED to use it.' : serviceUp ? 'Ollama is responding, but the selected model is not installed yet. Pull the model below to enable contextual checks.' : 'No local model is connected right now. ContexA still runs its built-in deterministic rule checks; local contextual AI can be enabled without an API key.'}</p>
          </div>
        </div>
        <div className="local-ai-status-grid">
          <div className="local-ai-status-item"><span>Inference provider</span><strong>Ollama local runtime</strong></div>
          <div className="local-ai-status-item"><span>Configured model</span><strong>{modelName}</strong></div>
          <div className="local-ai-status-item"><span>Cloud API key</span><strong className="no-key-state"><CheckCircle2 size={13} /> Not required</strong></div>
          <div className="local-ai-status-item"><span>Rules engine</span><strong className="always-on-state"><CheckCircle2 size={13} /> Always available</strong></div>
        </div>
        <div className="local-ai-setup">
          <div className="local-ai-setup-head"><div><div className="section-eyebrow small">ONE-TIME SETUP</div><strong>Enable contextual review locally</strong></div><a className="btn btn-secondary btn-compact setup-download" href="https://ollama.com/download" target="_blank" rel="noreferrer">Get Ollama <ExternalLink size={13} /></a></div>
          <ol className="local-ai-steps">
            <li><span>01</span><div><strong>Install Ollama</strong><small>Download the installer for your operating system and finish setup.</small></div></li>
            <li><span>02</span><div><strong>Download the model once</strong><small>Open a terminal and run this command. It may download a few GB depending on the model.</small><div className="command-glass"><code>{installCommand}</code><button className="btn btn-ghost btn-compact" type="button" onClick={() => void copyInstallCommand()}><Copy size={13} />{copiedCommand ? 'Copied' : 'Copy'}</button></div></div></li>
            <li><span>03</span><div><strong>Start or keep Ollama running</strong><small>Ollama Desktop usually starts its local service. If needed, run <code>ollama serve</code>, then reopen Settings.</small></div></li>
          </ol>
          <div className={`local-ai-alert ${localReady ? 'ready' : ''}`}><Info size={15} /><span>{localReady ? `Ready: ${modelName} is installed. New copy checks can use local contextual analysis alongside deterministic rules.` : 'Until the model is available, ContexA reports deterministic rule matches only. It will not pretend that AI tone analysis or contextual verification ran.'}</span></div>
        </div>
        {backend?.ai_configured && backend?.ai_provider === 'Claude API' && <div className="optional-provider-note">An existing cloud provider is configured, but it is optional. Ollama remains the recommended no-key path.</div>}
      </section>

      <section className="panel settings-panel"><PanelHeading eyebrow="ACTIVE IDENTITY" title="Your session" /><div className="profile-card"><div className="avatar profile-avatar">{initials(user.name)}</div><div><strong>{user.name}</strong><p>{user.email}</p><span className="team-role-pill">{user.role}</span></div></div><div className="setting-row"><div className="setting-copy"><strong>Role-based access control</strong><small>Actions are validated server-side</small></div><span className="setting-value status-live"><i />ENABLED</span></div><button className="btn btn-secondary settings-logout" onClick={onLogout}><LogOut size={15} /> Sign out of ContexA</button></section>
      <section className="panel settings-panel"><PanelHeading eyebrow="DATA & TRUST" title="Workspace data" /><p className="theme-picker-description">Export your workspace records and source files. Workspace deletion requires the current password and exact workspace name.</p><div className="setting-row"><div className="setting-icon"><Download size={17} /></div><div className="setting-copy"><strong>Export workspace</strong><small>Download a ZIP containing workspace records and uploaded originals. Password hashes are never included.</small></div><button className="btn btn-secondary btn-compact" type="button" onClick={() => void exportWorkspace()} disabled={exportingWorkspace}>{exportingWorkspace ? <RefreshCw size={13} className="spin" /> : <Download size={13} />}{exportingWorkspace ? 'Preparing…' : 'Export ZIP'}</button></div>{workspaceActionMessage && <p className="field-hint" role="status">{workspaceActionMessage}</p>}{user.role === 'Brand Admin' && <div className="workspace-danger-zone"><div className="section-eyebrow small">DESTRUCTIVE ACTION</div><strong>Delete this workspace</strong><small>This permanently removes its members, documents, findings, facts, rules, evidence, assets and audit history. Export first. This cannot be undone.</small><label className="field-label">Type workspace name: {settings?.workspace?.name}</label><input className="form-input" value={workspaceConfirmation} onChange={e => setWorkspaceConfirmation(e.target.value)} autoComplete="off" /><label className="field-label">Confirm your password</label><input className="form-input" type="password" value={workspacePassword} onChange={e => setWorkspacePassword(e.target.value)} autoComplete="current-password" /><button className="btn btn-danger" type="button" disabled={deletingWorkspace || !workspacePassword || workspaceConfirmation !== settings?.workspace?.name} onClick={() => void deleteWorkspace()}>{deletingWorkspace ? <RefreshCw size={14} className="spin" /> : <Trash2 size={14} />}Delete workspace permanently</button></div>}</section>
      <section className="panel settings-panel"><PanelHeading eyebrow="DATA & TRUST" title="Processing notes" /><div className="setting-note-list"><div><CheckCircle2 size={16} /><span><strong>Private object storage</strong><small>Use S3-compatible storage for durable uploads across multiple deployment instances.</small></span></div><div><CheckCircle2 size={16} /><span><strong>Review actions are auditable</strong><small>Dismissal reasons and sign-off notes are captured alongside the acting account.</small></span></div><div><AlertTriangle size={16} /><span><strong>Publication is a governance state</strong><small>ContexA does not automatically post approved files to public channels.</small></span></div></div></section>
    </div>
  </div>
}
function DatabaseIcon() { return <Activity size={17} /> }

function Modal({ title, eyebrow, onClose, children }: { title: string; eyebrow?: string; onClose: () => void; children: ReactNode }) {
  const dialogRef = useRef<HTMLElement | null>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusable = () => Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])') || [])
    focusable()[0]?.focus()
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) { event.preventDefault(); dialogRef.current?.focus(); return }
      const first = items[0], last = items[items.length - 1]
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', listener)
    return () => { window.removeEventListener('keydown', listener); previouslyFocused?.focus() }
  }, [])
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><section ref={dialogRef} className="modal-card" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}><div className="modal-header"><div><div className="section-eyebrow small">{eyebrow || 'WORKSPACE ACTION'}</div><h2>{title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={17} /></button></div><div className="modal-content">{children}</div></section></div>
}

function RuleModal({ rule, onClose, onSaved, onError }: { rule?: Rule; onClose: () => void; onSaved: (message: string) => void; onError: (message: string) => void }) {
  const [form, setForm] = useState<RuleDraft>({ code: rule?.code || '', title: rule?.title || '', category: rule?.category || 'terminology', rule_clause: rule?.rule_clause || '', source_document: rule?.source_document || 'Brand Governance Handbook', pattern: rule?.pattern || '', severity: rule?.severity || 'warning', suggested_fix: rule?.suggested_fix || '', is_active: rule?.is_active ?? true })
  const [saving, setSaving] = useState(false)
  const update = (key: keyof RuleDraft, value: string | boolean) => setForm(prev => ({ ...prev, [key]: value } as RuleDraft))
  async function submit(e: FormEvent) { e.preventDefault(); setSaving(true); try { const payload = { ...form, pattern: form.pattern.trim() || null }; if (rule) { await api.updateRule(rule.id, payload); onSaved(`${rule.code} updated. Existing documents should be rescanned to apply changes.`) } else { await api.createRule(payload); onSaved(`${form.code.toUpperCase()} created and added to the active guideline set.`) } } catch (e) { onError(e instanceof Error ? e.message : 'Could not save rule.') } finally { setSaving(false) } }
  return <Modal title={rule ? 'Edit guideline rule' : 'Create guideline rule'} eyebrow="BRAND ADMIN / RULE EDITOR" onClose={onClose}><form className="form-stack" onSubmit={submit}><div className="form-grid two"><div><label className="field-label">Rule code <span className="required">*</span></label><input className="form-input" required disabled={!!rule} value={form.code} onChange={e => update('code', e.target.value.toUpperCase())} placeholder="e.g. TERM-014" /></div><div><label className="field-label">Category <span className="required">*</span></label><select className="form-input" value={form.category} onChange={e => update('category', e.target.value)}>{['claim', 'legal', 'terminology', 'tone', 'contrast', 'asset', 'other'].map(c => <option key={c}>{c}</option>)}</select></div></div><div><label className="field-label">Rule title <span className="required">*</span></label><input className="form-input" required minLength={2} value={form.title} onChange={e => update('title', e.target.value)} /></div><div><label className="field-label">Approved guideline clause <span className="required">*</span></label><textarea className="form-textarea" required rows={3} minLength={8} value={form.rule_clause} onChange={e => update('rule_clause', e.target.value)} placeholder="Describe the approved brand requirement clearly..." /></div><div className="form-grid two"><div><label className="field-label">Severity</label><select className="form-input" value={form.severity} onChange={e => update('severity', e.target.value)}>{['critical', 'warning', 'info'].map(s => <option key={s}>{s}</option>)}</select></div><div><label className="field-label">Source document</label><input className="form-input" value={form.source_document} onChange={e => update('source_document', e.target.value)} /></div></div><div><label className="field-label">Deterministic regex <span className="optional">OPTIONAL</span></label><input className="form-input regex-input" value={form.pattern} onChange={e => update('pattern', e.target.value)} placeholder={'e.g. \\b(?:free|guaranteed)\\b'} /><small className="field-hint">Case-insensitive Python regular expression. Leave blank for rules requiring contextual or visual review.</small></div><div><label className="field-label">Suggested fix</label><textarea className="form-textarea" rows={2} value={form.suggested_fix} onChange={e => update('suggested_fix', e.target.value)} placeholder="Give reviewers a clear resolution path..." /></div><label className="checkbox-line"><input type="checkbox" checked={form.is_active} onChange={e => update('is_active', e.target.checked)} /><span><strong>Rule is active</strong><small>Active rules are applied to new scans and rescan jobs.</small></span></label><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? <RefreshCw size={14} className="spin" /> : <Check size={15} />}{rule ? 'Save changes' : 'Create rule'}</button></div></form></Modal>
}

function TeamModal({ onClose, onSaved, onError }: { onClose: () => void; onSaved: (message: string) => void; onError: (message: string) => void }) {
  const [form, setForm] = useState({ email: '', role: 'Creator' })
  const [saving, setSaving] = useState(false)
  const [inviteLink, setInviteLink] = useState('')
  const [sent, setSent] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault(); setSaving(true)
    try {
      const result = await api.createInvitation(form.email, form.role)
      setInviteLink(result.debug_link || ''); setSent(true)
      if (!result.debug_link) onSaved(`Invitation sent to ${form.email} as ${form.role}.`)
    } catch (e) { onError(e instanceof Error ? e.message : 'Could not create the invitation.') }
    finally { setSaving(false) }
  }
  return <Modal title={sent ? 'Invitation created' : 'Invite workspace member'} eyebrow="BRAND ADMIN / ACCESS CONTROL" onClose={onClose}>
    {sent ? <div className="form-stack"><div className="permission-preview"><CheckCircle2 size={18}/><span><strong>One-time invitation prepared</strong><small>{form.email} will join this workspace as {form.role}. They set their own password after opening the link.</small></span></div>{inviteLink ? <><label className="field-label">Development invitation link<input className="form-input" readOnly value={inviteLink}/></label><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Close</button><button type="button" className="btn btn-primary" onClick={() => { void navigator.clipboard.writeText(inviteLink); onSaved(`Invitation link copied for ${form.email}.`) }}><Copy size={14}/> Copy invitation link</button></div></> : <div className="modal-actions"><button type="button" className="btn btn-primary" onClick={() => onSaved(`Invitation sent to ${form.email} as ${form.role}.`)}>Done</button></div>}</div> : <form className="form-stack" onSubmit={submit}><div><label className="field-label">Work email <span className="required">*</span></label><input className="form-input" type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} placeholder="alex@company.com" /></div><div><label className="field-label">Workspace role <span className="required">*</span></label><select className="form-input" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>{['Creator', 'Manager', 'SME / Legal'].map(role => <option key={role}>{role}</option>)}</select></div><div className="permission-preview"><ShieldCheck size={16} /><span><strong>One-time invitation</strong><small>The invitee chooses their own password. Role permissions are applied when they accept.</small></span></div><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? <RefreshCw size={14} className="spin" /> : <Plus size={15} />}Create invitation</button></div></form>}
  </Modal>
}

export default App
