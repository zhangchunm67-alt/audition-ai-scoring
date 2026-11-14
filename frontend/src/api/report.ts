/** 报告详情接口（GET /api/reports/{id}）的返回结构。后端返回的是组装好的字典，这里手写类型。 */
export type Hit = {
  evidence_id: string; item_id: string; item_name: string; kind: string; start_ms: number | null; end_ms: number | null;
  quote: string | null; label: string | null; judgment: string | number | null; reason: string | null; confidence: number;
  source: string; ref: string | null; value: number | null; segment: string | null; delta: number | null; issue: boolean;
};
export type SentenceRow = { segment: string; start_ms: number; end_ms: number; text: string; hits: Hit[]; issue: boolean; suggestion: string | null };
export type SegmentBlock = { segment: string; sentences: SentenceRow[]; segment_hits: Hit[] };
export type ItemResult = {
  item_id: string; name: string; dimension: string; type: string; status: string; score: number | null; max: number;
  low_confidence: boolean; low_confidence_reasons: string[]; missing_reasons: string[];
  contributions: { evidence_id: string; delta: number; note: string }[]; notes: string[];
  source?: "machine" | "human"; suggested_score?: number | null; human?: { score: number; by?: string | null; note?: string | null } | null;
};
export type Dimension = { id: string; name: string; status: string; raw: number | null; applicable_max: number; scaled: number | null; score: number | null; grade: number | null };
export type RoundSummary = { round_no: number; total_grade: number; grade_pass: boolean; dimension_scores: Record<string, number>; dimension_grades: Record<string, number> };
export type ReportDetail = {
  id: string; revision: number; superseded_at: string | null; created_at: string; recording_id: string; candidate_id: string; candidate_name: string;
  submitted_at: string | null; sheet_code: string; product_name: string; audience: string; props_available: boolean; mode?: string;
  label: "recommend" | "pending" | "not_recommend"; conclusion: string; critical: boolean; redline_hit: boolean; informal: boolean;
  verdict: { reason: string; rounds: RoundSummary[]; display_round: number; majority_grade_pass: boolean };
  display_round: number;
  result: { items: ItemResult[]; dimensions: Dimension[]; total_grade: number; threshold: number; audience: string; critical: boolean;
            low_confidence_items: string[]; missing_items: string[]; redlines_enabled: boolean };
  evidence: Hit[];
  sentences: SegmentBlock[];
  trace: { rubric_version: string; rubric_status: string; config_hash: string; detector_config_version: string; detector_config_status: string;
           redline_lexicon_version: string | null; model_manifest: Record<string, string> };
  media: { video_asset_id: string | null; video_deleted: boolean; segments: { segment: string; start_ms: number; end_ms: number }[];
           objection_times: { objection_id: string; at_ms: number; video_ms: number }[] };
};
export const LABEL_COLOR: Record<string, string> = { recommend: "green", pending: "gold", not_recommend: "red" };
export const LABEL_TEXT: Record<string, string> = { recommend: "推荐", pending: "待定", not_recommend: "不推荐" };
export const LABEL_TONE: Record<string, "ok" | "warn" | "bad"> = { recommend: "ok", pending: "warn", not_recommend: "bad" };
