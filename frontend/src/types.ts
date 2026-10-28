export type Role = 'Creator' | 'Manager' | 'SME / Legal' | 'Brand Admin'
export type Severity = 'critical' | 'warning' | 'info'
export type FindingStatus = 'open' | 'accepted' | 'dismissed' | 'edited'
export interface User { id: string; name: string; email: string; role: Role }
export interface Finding {
  id: string; content_id: string; rule_id: string | null; rule_code: string | null; rule_title: string | null
  severity: Severity; finding_type: string; flagged_text: string; page_number: number
  location_bbox: { bbox?: number[]; coordinate_system?: string } | null; reasoning: string; suggested_fix: string
  applied_text: string | null; status: FindingStatus; dismissal_reason: string | null; created_at: string; updated_at: string
}
export interface DocumentRecord {
  id: string; filename: string; content_type: string; page_count: number; status: string; compliance_score: number
  size_bytes: number; created_by: string; creator_name?: string; created_at: string; updated_at: string
  findings_count: number; critical_count: number
}
export interface Rule {
  id: string; code: string; title: string; category: string; rule_clause: string; source_document: string
  pattern: string | null; severity: Severity; suggested_fix: string; is_active: boolean; created_at: string; updated_at: string
}
export interface Activity { id: string; actor_name: string; action: string; entity_type: string; entity_id: string; detail: Record<string, unknown>; created_at: string }
export interface Dashboard {
  integrity_score: number; total_documents: number; in_review: number; publish_ready: number; open_findings: number
  critical_findings: number; warning_findings: number; rule_count: number; recent_documents: DocumentRecord[]
  recent_activity: Activity[]; severity_counts: Record<string, number>; weekly_activity: { day: string; date: string; count: number }[]
}
export interface DocumentDetail {
  document: DocumentRecord; content_text: string; pages: { page: number; text: string; note?: string }[]
  findings: Finding[]; publish_ready: boolean; ai_configured: boolean
}
export interface InsightData {
  rule_clarity_index: number; total_findings: number; dismissed_findings: number
  rules: { id: string; code: string; title: string; category: string; triggered: number; dismissed: number; gci: number; status: string }[]
  findings_by_category: Record<string, number>
}
