import { useCallback, useEffect, useState } from 'react'
import { Activity, Archive, ArrowRight, BadgeCheck, BrainCircuit, Cloud, Fingerprint, GitBranch, LockKeyhole, RefreshCw, ShieldCheck, Workflow } from 'lucide-react'
import { api } from './api'

type Row = Record<string, any>
const dateLabel = (value?: string) => value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'
const compact = (value?: string) => value ? `${value.slice(0, 12)}…${value.slice(-8)}` : '—'

export default function TrustFoundationPage({ role }: { role: string }) {
  const [status, setStatus] = useState<Row | null>(null)
  const [graph, setGraph] = useState<{ nodes: Row[]; edges: Row[] }>({ nodes: [], edges: [] })
  const [traces, setTraces] = useState<Row[]>([])
  const [archives, setArchives] = useState<Row[]>([])
  const [anchors, setAnchors] = useState<Row[]>([])
  const [replay, setReplay] = useState<Row | null>(null)
  const [anchorVerification, setAnchorVerification] = useState<Row | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const isAdmin = role === 'Brand Admin'

  const load = useCallback(async () => {
    setBusy(true); setError('')
    const jobs = await Promise.allSettled([api.foundationStatus(), api.trustGraph(), api.decisionTraces(), api.evidenceArchives(), api.auditAnchors()])
    const setters: ((v: any) => void)[] = [setStatus, setGraph, setTraces, setArchives, setAnchors]
    const errors: string[] = []
    jobs.forEach((item, index) => { if (item.status === 'fulfilled') setters[index](item.value); else errors.push(item.reason instanceof Error ? item.reason.message : 'Foundation data could not be loaded.') })
    if (errors.length) setError(errors[0])
    setBusy(false)
  }, [])
  useEffect(() => { void load() }, [load])

  const run = async (action: () => Promise<any>, success: string) => {
    setBusy(true); setError(''); setNotice('')
    try { const result = await action(); setNotice(success); await load(); return result }
    catch (e) { setError(e instanceof Error ? e.message : 'Action failed.'); return null }
    finally { setBusy(false) }
  }

  return <div className="trustos-page">
    <div className="trustos-header page-title-row">
      <div><div className="section-eyebrow">CONTEXA / ENTERPRISE FOUNDATION</div><h1>Trust Foundation</h1><p>Identity, cryptographic provenance, immutable evidence and replayable decisions.</p></div>
      <div className="trustos-header-actions"><span className="trustos-role"><ShieldCheck size={14}/>{role}</span><button className="btn btn-secondary btn-compact" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? 'spin' : ''}/> Refresh</button></div>
    </div>
    {error && <div className="trustos-alert error">{error}</div>}
    {notice && <div className="trustos-alert success">{notice}</div>}

    <div className="trustos-module-intro foundation-intro"><div><span className="section-eyebrow">TRUST INFRASTRUCTURE STATUS</span><h2>Proof, not just promises.</h2><p>Providers are shown as configured only when their required settings exist. Local signing and local file storage remain development modes, not production-grade immutability.</p></div><div className="trustos-badge"><Fingerprint size={18}/> Workspace: {status?.current_workspace || '—'}</div></div>

    <div className="trustos-metrics foundation-metrics">
      <Metric icon={LockKeyhole} label="Identity" value={status?.identity?.provider || '—'} state={status?.identity?.configured ? 'Configured' : 'Local / not configured'} detail={status?.identity?.note || 'Provider verification status'} />
      <Metric icon={Fingerprint} label="Passport signing" value={status?.signing?.provider || '—'} state={status?.signing?.production_grade ? 'Production provider' : 'Development signer'} detail={status?.signing?.algorithm || 'Signing algorithm'} />
      <Metric icon={Archive} label="Evidence archive" value={status?.archive?.provider || '—'} state={status?.archive?.production_grade ? 'Object Lock configured' : 'Non-immutable / not configured'} detail={`${status?.archive?.retention_days || 0} retention days`} />
      <Metric icon={GitBranch} label="Trust Graph" value={graph.nodes.length.toLocaleString()} state="Workspace scoped" detail={`${graph.edges.length} stored relationships`} />
    </div>

    <div className="trustos-grid-2">
      <section className="panel trustos-panel foundation-panel">
        <div className="panel-heading"><div><span className="section-eyebrow">CLAIM / SOURCE / ASSET / INCIDENT</span><h3>Evidence Trust Graph</h3></div><GitBranch size={18}/></div>
        <p className="foundation-copy">Builds a graph from actual ContexA records: claims, monitored sources, approved assets, passports, drift events, incidents and agent runs. Edges represent stored workflow references, not an AI-inferred truth judgment.</p>
        <div className="foundation-counts"><div><b>{graph.nodes.length}</b><small>Nodes</small></div><div><b>{graph.edges.length}</b><small>Edges</small></div><div><b>{new Set(graph.nodes.map(x => x.node_type)).size}</b><small>Node types</small></div></div>
        <button className="btn btn-primary" onClick={() => void run(api.rebuildTrustGraph, 'Trust Graph rebuilt from workspace records.')} disabled={busy || role === 'Creator'}><Workflow size={14}/> Rebuild Trust Graph <ArrowRight size={14}/></button>
        <div className="foundation-node-list">{graph.nodes.slice(0, 10).map(node => <div key={node.id}><span className={`foundation-node-dot node-${node.node_type}`}/><b>{node.label}</b><small>{node.node_type.replaceAll('_', ' ')}</small></div>)}{!graph.nodes.length && <p className="trustos-muted">No graph nodes yet. Run a rebuild after adding source, evidence and content records.</p>}</div>
      </section>

      <section className="panel trustos-panel foundation-panel">
        <div className="panel-heading"><div><span className="section-eyebrow">TAMPER-EVIDENT AUDIT</span><h3>Signed Merkle Anchors</h3></div><BadgeCheck size={18}/></div>
        <p className="foundation-copy">A checkpoint groups the current workspace audit-event hashes into a Merkle root and signs that root with the configured trust signer. Create checkpoints after a review cycle or release.</p>
        <div className="foundation-anchor-list">{anchors.slice(0, 4).map(item => <div key={item.id}><b>{compact(item.root_sha256)}</b><small>{item.leaf_count} events · {item.signing_provider} · {dateLabel(item.created_at)}</small><button className="btn btn-quiet btn-compact" disabled={busy} onClick={() => api.verifyAuditAnchor(item.id).then(setAnchorVerification).catch(e => setError(e.message))}>Verify signature</button></div>)}{!anchors.length && <p className="trustos-muted">No signed checkpoints have been created.</p>}</div>
        {anchorVerification && <div className={`trustos-alert ${anchorVerification.signature_valid ? 'success' : 'error'}`}><b>{anchorVerification.signature_valid ? 'Anchor signature verified' : 'Anchor signature invalid'}</b> · {anchorVerification.id}<button className="btn btn-quiet btn-compact" onClick={() => setAnchorVerification(null)}>Close</button></div>}
        <button className="btn btn-secondary" disabled={!isAdmin || busy} onClick={() => void run(api.createAuditAnchor, 'Signed audit checkpoint created.')}><Fingerprint size={14}/> Create signed checkpoint</button>
        {!isAdmin && <small className="trustos-helper">Only a Brand Admin can anchor the workspace audit chain.</small>}
      </section>
    </div>

    <section className="panel trustos-panel foundation-panel">
      <div className="panel-heading"><div><span className="section-eyebrow">AI EXECUTION PROVENANCE</span><h3>Decision Replay</h3></div><BrainCircuit size={18}/></div>
      <p className="foundation-copy">Agent workflows record their deterministic engine version, input/output hashes, evidence references and human-review boundary. Replay checks that the stored execution record has not changed; it does not re-run an external model.</p>
      {traces.length ? <div className="foundation-table-wrap"><table className="data-table"><thead><tr><th>OPERATION</th><th>ENGINE / VERSION</th><th>INPUT HASH</th><th>OUTPUT HASH</th><th>CREATED</th><th/></tr></thead><tbody>{traces.map(item => <tr key={item.id}><td><b>{item.operation}</b><small>{item.agent_run_id || item.id}</small></td><td>{item.model_id}<small>{item.prompt_version}</small></td><td><code>{compact(item.input_sha256)}</code></td><td><code>{compact(item.output_sha256)}</code></td><td>{dateLabel(item.created_at)}</td><td><button className="btn btn-secondary btn-compact" onClick={() => api.replayDecisionTrace(item.id).then(setReplay).catch(e => setError(e.message))}>Verify replay</button></td></tr>)}</tbody></table></div> : <div className="trustos-empty"><Activity size={22}/><b>No decision traces yet</b><span>Run a governance agent workflow to create a replayable execution record.</span></div>}
      {replay && <div className={`trustos-alert ${replay.integrity_valid && replay.input_hash_valid && replay.output_hash_valid ? 'success' : 'error'}`}><b>{replay.integrity_valid && replay.input_hash_valid && replay.output_hash_valid ? 'Integrity verified' : 'Integrity mismatch'}</b> · Trace {replay.id} · Input {String(replay.input_hash_valid)} · Output {String(replay.output_hash_valid)}<button className="btn btn-quiet btn-compact" onClick={() => setReplay(null)}>Close</button></div>}
    </section>

    <section className="panel trustos-panel foundation-panel">
      <div className="panel-heading"><div><span className="section-eyebrow">EVIDENCE RETENTION</span><h3>Evidence Archive</h3></div><Cloud size={18}/></div>
      <p className="foundation-copy">Passport manifests are archived at issue time. AWS S3 Object Lock retention is only shown as immutable when the archive provider confirms that lock settings were requested and the write succeeded. Local mode is explicitly non-immutable.</p>
      {archives.length ? <div className="foundation-archive-list">{archives.map(item => <div key={item.id}><span className="foundation-archive-status">{item.object_lock_mode || 'LOCAL'}</span><b>{item.subject_type} · {item.subject_id}</b><code>{compact(item.sha256)}</code><small>{item.storage_provider} · {item.status} · {dateLabel(item.created_at)}</small></div>)}</div> : <p className="trustos-muted">No evidence archives yet. Issue a Trust Passport for a publish-ready asset.</p>}
    </section>
    <div className="trustos-footer-note"><ShieldCheck size={14}/> Supabase Auth, AWS KMS and S3 Object Lock remain optional provider integrations. A green configuration indicator does not replace live permission, IAM, RLS or retention acceptance tests.</div>
  </div>
}

function Metric({ icon: Icon, label, value, state, detail }: { icon: typeof Activity; label: string; value: string; state: string; detail: string }) {
  return <div className="trustos-metric panel"><div className="trustos-metric-top"><span>{label}</span><Icon size={16}/></div><strong className="foundation-provider-value">{value}</strong><small className="foundation-provider-state">{state}</small><small>{detail}</small></div>
}
