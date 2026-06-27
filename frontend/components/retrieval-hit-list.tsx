import type { ReactNode } from "react";

import type { RetrievalHit } from "@/lib/types";

const statusClassMap: Record<string, string> = {
  useful: "badge-useful",
  stale: "badge-stale",
  unnecessary: "badge-unnecessary",
  missing: "badge-missing",
};

type RetrievalHitListProps = Readonly<{
  hits: RetrievalHit[];
  children?: (hit: RetrievalHit) => ReactNode;
}>;

export function RetrievalHitList({ hits, children }: RetrievalHitListProps) {
  if (hits.length === 0) {
    return <p className="page-subtitle" style={{ textAlign: "center", padding: "2rem" }}>No retrieval hits recorded yet.</p>;
  }

  return (
    <div className="grid">
      {hits.map((hit) => (
        <article className="panel" key={hit.id} style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <span className="badge" style={{ background: "rgba(129, 140, 248, 0.08)", color: "var(--accent)", borderColor: "rgba(129, 140, 248, 0.2)" }}>
                Rank {hit.rank}
              </span>
              <span className="badge" style={{ background: "rgba(6, 182, 212, 0.08)", color: "#06b6d4", borderColor: "rgba(6, 182, 212, 0.2)" }}>
                Score {hit.score.toFixed(2)}
              </span>
            </div>
            {hit.feedback ? (
              <span className={`badge ${statusClassMap[hit.feedback] || ""}`}>
                {hit.feedback}
              </span>
            ) : null}
          </div>
          <div>
            <h3 style={{ margin: "0 0 0.25rem", color: "#f1f5f9", fontSize: "1.05rem", fontWeight: 700 }}>
              {hit.document_title}
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              <span className="page-subtitle" style={{ fontSize: "0.75rem", fontFamily: "ui-monospace, monospace", opacity: 0.8 }}>
                ID: {hit.document_id}
              </span>
              <span className="page-subtitle" style={{ fontSize: "0.85rem", color: "#94a3b8", lineHeight: 1.4 }}>
                Reason: {hit.reason}
              </span>
            </div>
          </div>
          {children ? (
            <div style={{ borderTop: "1px solid var(--line)", paddingTop: "0.85rem", marginTop: "0.25rem" }}>
              {children(hit)}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
