import type { RelationVerdict } from "@/lib/table-relations";

/**
 * One dimension's verdict: which dimension it is, the cardinality, and the kind
 * of evidence behind it. The three are announced together because any one of
 * them alone is misleading — "1 — 1" says nothing useful until you know whether
 * it came from reading the code or counting the rows.
 *
 * `muted` marks the verdict that is the annotation rather than the headline. The
 * distinction is carried by weight and fill, never by colour alone.
 */
export function TableRelationBadge({
  verdict,
  muted,
}: {
  verdict: RelationVerdict;
  muted?: boolean;
}) {
  return (
    <span
      className="table-relation-badge"
      data-dimension={verdict.dimension}
      data-cardinality={verdict.cardinality}
      data-muted={muted ? "true" : undefined}
      role="img"
      aria-label={`${verdict.dimensionLabel}维度 ${verdict.cardinalityLabel} ${verdict.evidenceLabel}`}
    >
      <span className="table-relation-badge-dimension" aria-hidden="true">
        {verdict.dimensionLabel}
      </span>
      <span className="table-relation-badge-glyph" aria-hidden="true">
        {verdict.glyph}
      </span>
      <span className="table-relation-badge-evidence" aria-hidden="true">
        {verdict.evidenceLabel}
      </span>
    </span>
  );
}
