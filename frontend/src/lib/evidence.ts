import { Source } from "@/lib/api";

/* ============================================================
   Evidence quality — credibility expressed through real evidence,
   never pseudo-precise "AI Confidence 98%" (acceptance §3).
   ============================================================ */

export type QualityLevel = "strong" | "moderate" | "review";

export type EvidenceQuality = {
  level: QualityLevel;
  label: string;
  supportingChunks: number;
  supportingDocuments: number;
  citationCoverage: number; // 0..1 of sources that carry a citation index
  topScore: number | null;
  reranked: boolean;
  webOnly: boolean;
  noEvidence: boolean;
};

export type SourceConflict = {
  metric: string;
  values: string[];
  documents: string[];
};

function scoreOf(source: Source): number | null {
  return source.relevance_score ?? null;
}

export function evidenceQuality(sources: Source[], conflicts: SourceConflict[]): EvidenceQuality {
  const documents = new Set(sources.map((source) => source.file_name).filter(Boolean));
  const cited = sources.filter((source) => source.citation_index != null).length;
  const scores = sources.map(scoreOf).filter((value): value is number => value != null);
  const rerankScores = sources.filter((source) => (source as { rerank_score?: number | null }).rerank_score != null);
  const webOnly = sources.length > 0 && sources.every((source) => source.source_type === "web");
  const topScore = scores.length ? Math.max(...scores) : null;

  let level: QualityLevel = "moderate";
  if (!sources.length || conflicts.length || webOnly) level = "review";
  else if (documents.size >= 2 && (topScore ?? 0) >= 0.55) level = "strong";

  const label = level === "strong" ? "STRONG EVIDENCE" : level === "review" ? "REVIEW REQUIRED" : "LIMITED EVIDENCE";
  return {
    level,
    label,
    supportingChunks: sources.length,
    supportingDocuments: documents.size,
    citationCoverage: sources.length ? cited / sources.length : 0,
    topScore,
    reranked: rerankScores.length > 0,
    webOnly,
    noEvidence: sources.length === 0,
  };
}

/* Heuristic source-consistency check: same unit-of-measure carrying different
   values across cited sources ⇒ SOURCE CONFLICT / REVIEW REQUIRED. */
const UNITS = ["天", "小时", "个月", "元", "%", "个工作日", "周", "年", "折"] as const;

export function findConflicts(sources: Source[]): SourceConflict[] {
  const buckets = new Map<string, Map<string, Set<string>>>();
  for (const source of sources) {
    if (source.source_type === "web" || !source.content_preview) continue;
    for (const unit of UNITS) {
      const pattern = new RegExp(`(\\d+(?:\\.\\d+)?)\\s*${unit}`, "g");
      for (const match of source.content_preview.matchAll(pattern)) {
        const value = `${match[1]} ${unit}`;
        const metric = `${unit}标准`;
        if (!buckets.has(metric)) buckets.set(metric, new Map());
        const values = buckets.get(metric)!;
        if (!values.has(value)) values.set(value, new Set());
        values.get(value)!.add(source.file_name || source.title || "source");
      }
    }
  }
  const conflicts: SourceConflict[] = [];
  for (const [metric, values] of buckets) {
    if (values.size < 2) continue;
    const distinct = [...values.keys()];
    // identical numbers split across docs are not contradictions of the same rule
    const docs = new Set([...values.values()].flatMap((set) => [...set]));
    if (distinct.length >= 2 && docs.size >= 2) {
      conflicts.push({ metric, values: distinct, documents: [...docs] });
    }
  }
  return conflicts.slice(0, 3);
}

export function answerCitationCount(answer: string): number {
  return (answer.match(/\[\d{1,2}\]/g) || []).length;
}
