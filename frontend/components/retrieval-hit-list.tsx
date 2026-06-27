import type { ReactNode } from "react";

import type { RetrievalHit } from "@/lib/types";

type RetrievalHitListProps = Readonly<{
  hits: RetrievalHit[];
  children?: (hit: RetrievalHit) => ReactNode;
}>;

export function RetrievalHitList({ hits, children }: RetrievalHitListProps) {
  if (hits.length === 0) {
    return <p className="page-subtitle">No retrieval hits recorded yet.</p>;
  }

  return (
    <div className="grid">
      {hits.map((hit) => (
        <article className="panel" key={hit.id}>
          <div className="split-row">
            <span className="badge">rank {hit.rank}</span>
            <span className="badge">score {hit.score.toFixed(2)}</span>
            {hit.feedback ? <span className="badge">{hit.feedback}</span> : null}
          </div>
          <h3>{hit.document_title}</h3>
          <p className="page-subtitle">{hit.document_id}</p>
          <p className="page-subtitle">{hit.reason}</p>
          {children ? children(hit) : null}
        </article>
      ))}
    </div>
  );
}
