import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, Bell, Check, CheckCircle2, CornerDownRight, Download, History, MessageSquare, RefreshCw, Trash2 } from 'lucide-react'
import { api } from './api'
import type { User } from './types'

type Notice = { id: string; kind: string; title: string; body: string; entity_type: string | null; entity_id: string | null; read: boolean; created_at: string }

function ago(value: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000))
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

/* ------------------------------------------------------------------ */
/* Notification bell: real inbox backed by /api/notifications          */
/* ------------------------------------------------------------------ */
export function NotificationBell({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [items, setItems] = useState<Notice[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const box = useRef<HTMLDivElement | null>(null)

  const refreshCount = useCallback(async () => {
    try { setUnread((await api.unreadCount()).unread_count) } catch { /* the health pill already reports API outages */ }
  }, [])
  const load = useCallback(async () => {
    setBusy(true); setError('')
    try { const data = await api.notifications(); setItems(data.items); setUnread(data.unread_count) }
    catch (e) { setError(errText(e, 'Could not load notifications.')) }
    finally { setBusy(false) }
  }, [])

  useEffect(() => {
    void refreshCount()
    const timer = window.setInterval(() => void refreshCount(), 45_000)
    const onFocus = () => void refreshCount()
    window.addEventListener('focus', onFocus)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus) }
  }, [refreshCount])

  useEffect(() => {
    if (!open) return
    void load()
    const onDown = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false) }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown); document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open, load])

  const openItem = (item: Notice) => {
    if (item.entity_type === 'document' && item.entity_id) { setOpen(false); onOpenDocument(item.entity_id) }
    if (!item.read) {
      setItems(list => list.map(n => n.id === item.id ? { ...n, read: true } : n)); setUnread(v => Math.max(0, v - 1))
      api.markNotificationRead(item.id).catch(() => { void load() }) // resync if the server did not accept it
    }
  }
  const readAll = async () => {
    try { await api.markAllNotificationsRead(); setItems(list => list.map(n => ({ ...n, read: true }))); setUnread(0) }
    catch (e) { setError(errText(e, 'Could not mark notifications as read.')) }
  }

  return <div className="nb-bell" ref={box}>
    <button className="icon-button notification-button" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(v => !v)}>
      <Bell size={17} />{unread > 0 && <span className="nb-bell-count">{unread > 99 ? '99+' : unread}</span>}
    </button>
    {open && <div className="nb-popover" role="dialog" aria-label="Notifications">
      <div className="nb-popover-head"><strong>Notifications</strong><button className="nb-link" onClick={() => void readAll()} disabled={!unread}><Check size={13} /> Mark all read</button></div>
      {error && <div className="inline-error" role="alert"><AlertCircle size={14} />{error}</div>}
      <div className="nb-popover-list">
        {busy && !items.length ? <div className="nb-empty"><RefreshCw size={16} className="spin" /> Loading…</div>
          : items.length ? items.map(item => <button key={item.id} className={`nb-notice ${item.read ? '' : 'is-unread'}`} onClick={() => openItem(item)}>
            <span className="nb-notice-kind">{item.kind.replace('_', ' ')}</span>
            <strong>{item.title}</strong>
            {item.body && <span className="nb-notice-body">{item.body}</span>}
            <small>{ago(item.created_at)}</small>
          </button>)
          : <div className="nb-empty">You're all caught up. Review assignments, @mentions and approvals will appear here.</div>}
      </div>
    </div>}
  </div>
}

/* ------------------------------------------------------------------ */
/* Discussion + activity panel for a document                          */
/* ------------------------------------------------------------------ */
function Mentions({ text }: { text: string }) {
  const parts = text.split(/(@[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g)
  return <>{parts.map((part, i) => part.startsWith('@') && part.includes('.') ? <mark className="nb-mention" key={i}>{part}</mark> : <span key={i}>{part}</span>)}</>
}

export function DiscussionPanel({ documentId, user, isPublished }: { documentId: string; user: User; isPublished: boolean }) {
  const [tab, setTab] = useState<'discussion' | 'activity'>('discussion')
  const [threads, setThreads] = useState<any[]>([])
  const [events, setEvents] = useState<any[]>([])
  const [draft, setDraft] = useState('')
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const reviewer = user.role !== 'Creator'

  const load = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const [c, a] = await Promise.all([api.comments('document', documentId), api.documentActivity(documentId)])
      setThreads(c.threads); setEvents(a.events)
    } catch (e) { setError(errText(e, 'Could not load the discussion.')) }
    finally { setBusy(false) }
  }, [documentId])
  useEffect(() => { setThreads([]); setEvents([]); setReplyTo(null); void load() }, [load])

  const post = async (body: string, parent_id?: string) => {
    if (!body.trim()) return
    setPosting(true); setError('')
    try {
      await api.addComment({ entity_type: 'document', entity_id: documentId, body: body.trim(), parent_id })
      if (parent_id) { setReply(''); setReplyTo(null) } else setDraft('')
      await load()
    } catch (e) { setError(errText(e, 'Could not post your comment.')) }
    finally { setPosting(false) }
  }
  const act = async (fn: () => Promise<unknown>, fallback: string) => {
    setError('')
    try { await fn(); await load() } catch (e) { setError(errText(e, fallback)) }
  }

  const renderComment = (c: any, isReply = false) => <div className={`nb-comment ${isReply ? 'is-reply' : ''} ${c.resolved ? 'is-resolved' : ''}`} key={c.id}>
    <div className="nb-comment-head">
      <strong>{c.author_name}</strong><small>{ago(c.created_at)}{c.edited_at ? ' · edited' : ''}</small>
      {c.resolved && !isReply && <span className="nb-chip"><CheckCircle2 size={12} /> Resolved</span>}
    </div>
    <p className={c.is_deleted ? 'nb-deleted' : ''}>{c.is_deleted ? 'This comment was deleted.' : <Mentions text={c.body} />}</p>
    {!c.is_deleted && <div className="nb-comment-actions">
      {!isReply && <button className="nb-link" onClick={() => { setReplyTo(replyTo === c.id ? null : c.id); setReply('') }}><CornerDownRight size={12} /> Reply</button>}
      {!isReply && (c.author_id === user.id || reviewer) && <button className="nb-link" onClick={() => void act(() => api.updateComment(c.id, { resolved: !c.resolved }), 'Could not update the thread.')}><Check size={12} /> {c.resolved ? 'Reopen' : 'Resolve'}</button>}
      {(c.author_id === user.id || user.role === 'Brand Admin') && <button className="nb-link nb-link-danger" onClick={() => { if (window.confirm('Delete this comment?')) void act(() => api.deleteComment(c.id), 'Could not delete the comment.') }}><Trash2 size={12} /> Delete</button>}
    </div>}
    {replyTo === c.id && <div className="nb-compose nb-compose-reply">
      <textarea aria-label="Write a reply" value={reply} maxLength={4000} onChange={e => setReply(e.target.value)} placeholder="Write a reply…" />
      <button className="btn btn-primary" disabled={posting || !reply.trim()} onClick={() => void post(reply, c.id)}>{posting ? <RefreshCw size={14} className="spin" /> : null} Reply</button>
    </div>}
  </div>

  const open = threads.filter(t => !t.resolved).length
  return <section className="panel nb-discussion" aria-label="Discussion and activity">
    <div className="panel-heading">
      <div><div className="section-eyebrow small">TEAM</div><h3>{tab === 'discussion' ? 'Discussion' : 'Activity'} <span className="muted-count">{tab === 'discussion' ? threads.length : events.length}</span></h3></div>
      <div className="nb-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'discussion'} className={tab === 'discussion' ? 'is-active' : ''} onClick={() => setTab('discussion')}><MessageSquare size={13} /> Discussion{open ? ` · ${open} open` : ''}</button>
        <button role="tab" aria-selected={tab === 'activity'} className={tab === 'activity' ? 'is-active' : ''} onClick={() => setTab('activity')}><History size={13} /> Activity</button>
      </div>
    </div>
    {error && <div className="inline-error" role="alert"><AlertCircle size={14} />{error}</div>}
    {tab === 'discussion' && <>
      <div className="nb-compose">
        <textarea aria-label="Add a comment" value={draft} maxLength={4000} onChange={e => setDraft(e.target.value)}
          placeholder={isPublished ? 'Add a note to this approved document…' : 'Ask a question or leave a note. Mention a teammate with @their.email@company.com'} />
        <button className="btn btn-primary" disabled={posting || !draft.trim()} onClick={() => void post(draft)}>{posting ? <RefreshCw size={14} className="spin" /> : <MessageSquare size={14} />} Post comment</button>
      </div>
      {busy && !threads.length ? <div className="nb-empty"><RefreshCw size={16} className="spin" /> Loading discussion…</div>
        : threads.length ? <div className="nb-thread-list">{threads.map(t => <div className="nb-thread" key={t.id}>{renderComment(t)}{(t.replies || []).map((r: any) => renderComment(r, true))}</div>)}</div>
        : <div className="nb-empty">No comments yet. Start the conversation — reviewers are notified when you @mention them.</div>}
    </>}
    {tab === 'activity' && (busy && !events.length ? <div className="nb-empty"><RefreshCw size={16} className="spin" /> Loading activity…</div>
      : events.length ? <ol className="nb-timeline">{events.map(e => <li key={e.id}><span className="nb-dot" /><div><strong>{String(e.action).replaceAll('.', ' ').replaceAll('_', ' ')}</strong><small>{e.actor_name} · {ago(e.created_at)}</small></div></li>)}</ol>
      : <div className="nb-empty">No recorded activity for this document yet.</div>)}
  </section>
}

/* ------------------------------------------------------------------ */
/* Compliance trend: real daily snapshots from /api/analytics/trend    */
/* ------------------------------------------------------------------ */
export function ComplianceTrendPanel() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<{ series: any[]; summary: any } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setBusy(true); setError('')
    api.complianceTrend(days).then(result => { if (active) setData(result) }).catch(e => { if (active) setError(errText(e, 'Could not load the compliance trend.')) }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [days])

  const series = data?.series || []
  const latest = series[series.length - 1]
  const W = 600, H = 170, padL = 34, padR = 12, padT = 12, padB = 24
  const x = (i: number) => series.length < 2 ? (padL + (W - padL - padR) / 2) : padL + (i * (W - padL - padR)) / (series.length - 1)
  const y = (v: number) => padT + (1 - v / 100) * (H - padT - padB)
  const line = series.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.integrity_score).toFixed(1)}`).join(' ')
  const critMax = Math.max(1, ...series.map(p => p.critical_findings))
  const change = data?.summary?.score_change ?? 0

  const download = async () => {
    try {
      const blob = await api.complianceTrendCsv(days)
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'contexa-compliance-trend.csv'; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError(errText(e, 'Could not download the CSV.')) }
  }

  return <section className="panel nb-trend" aria-label="Compliance trend">
    <div className="panel-heading">
      <div><div className="section-eyebrow small">HISTORY</div><h3>Compliance trend</h3></div>
      <div className="nb-trend-tools">
        <div className="nb-tabs" role="tablist" aria-label="Range">{[7, 30, 90].map(d => <button key={d} role="tab" aria-selected={days === d} className={days === d ? 'is-active' : ''} onClick={() => setDays(d)}>{d}d</button>)}</div>
        <button className="btn btn-secondary" onClick={() => void download()} disabled={!series.length}><Download size={14} /> CSV</button>
      </div>
    </div>
    {error && <div className="inline-error" role="alert"><AlertCircle size={14} />{error}</div>}
    {busy && !data ? <div className="nb-empty"><RefreshCw size={16} className="spin" /> Loading trend…</div> : <>
      <div className="nb-trend-stats">
        <div><small>Integrity</small><strong>{latest ? `${latest.integrity_score}%` : '—'}</strong>{series.length > 1 && <em className={change >= 0 ? 'up' : 'down'}>{change >= 0 ? '+' : ''}{change} pts</em>}</div>
        <div><small>Open findings</small><strong>{latest?.open_findings ?? '—'}</strong></div>
        <div><small>Critical</small><strong>{latest?.critical_findings ?? '—'}</strong></div>
        <div><small>Open reviews</small><strong>{latest?.open_tasks ?? '—'}</strong></div>
      </div>
      <svg className="nb-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Integrity score over the last ${days} days`} preserveAspectRatio="xMidYMid meet">
        {[0, 50, 100].map(v => <g key={v}><line className={v === 0 ? 'nb-chart-base' : 'nb-chart-grid'} x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} strokeOpacity={v === 0 ? 1 : 0.5} strokeDasharray={v === 0 ? undefined : '4 4'} /><text className="nb-chart-text" x={padL - 6} y={y(v) + 4} textAnchor="end">{v}</text></g>)}
        {series.map((p, i) => { const bw = Math.min(26, (W - padL - padR) / Math.max(series.length, 1) - 4); const h = (p.critical_findings / critMax) * 38; return p.critical_findings ? <rect className="nb-chart-bar" key={`b${i}`} x={x(i) - bw / 2} y={H - padB - h} width={bw} height={h} /> : null })}
        {series.length > 1 && <path className="nb-chart-line" d={line} />}
        {series.map((p, i) => <circle className="nb-chart-dot" key={p.date} cx={x(i)} cy={y(p.integrity_score)} r="6"><title>{`${p.date}: ${p.integrity_score}% · ${p.critical_findings} critical`}</title></circle>)}
        {series.length > 0 && <><text className="nb-chart-text" x={x(0)} y={H - 6} textAnchor={series.length > 1 ? 'start' : 'middle'}>{series[0].date.slice(5)}</text>{series.length > 1 && <text className="nb-chart-text" x={x(series.length - 1)} y={H - 6} textAnchor="end">{series[series.length - 1].date.slice(5)}</text>}</>}
      </svg>
      <p className="nb-trend-note">{series.length > 1 ? 'Line: integrity score. Red bars: critical findings. One snapshot is stored per day after each upload, scan or review action.' : 'History starts today. A snapshot is stored once per day whenever content is uploaded, scanned or reviewed, so the line fills in as you work — nothing is back-filled.'}</p>
    </>}
  </section>
}
