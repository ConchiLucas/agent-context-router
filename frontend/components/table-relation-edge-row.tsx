import { TableRelationBadge } from "@/components/table-relation-badge";
import { dimensionsAgree, relationVerdicts } from "@/lib/table-relations";
import type { TableRelationView } from "@/lib/types";

/**
 * One relation. The identity comes first because it is what the row is about and
 * what the evidence panel is keyed on; the two verdicts follow in a fixed order so
 * they line up into columns and can be compared down the list.
 *
 * The data verdict is the headline and the code verdict the annotation: what the
 * rows contain is a fact, what the code permits is an upper bound. When the two
 * disagree the row says so rather than leaving the reader to notice.
 *
 * The whole row opens, rather than a link at one end of it. A row states two
 * verdicts and nothing about how either was reached, so wanting to know why is
 * the expected next move, not an advanced one.
 */
export function TableRelationEdgeRow({
  relation,
  busy,
  onOpen,
}: {
  relation: TableRelationView;
  busy?: boolean;
  onOpen: (relation: TableRelationView) => void;
}) {
  const [code, database] = relationVerdicts(relation);
  const agree = dimensionsAgree(relation);

  return (
    <li className="table-relation-row" data-diverging={agree ? undefined : "true"}>
      <button
        type="button"
        className="table-relation-row-open"
        aria-label={`查看 ${relation.relation_id} 的依据`}
        data-busy={busy ? "true" : undefined}
        onClick={() => onOpen(relation)}
      >
        <span className="table-relation-row-identity">
          <code className="table-relation-row-id">{relation.relation_id}</code>
          <span className="table-relation-row-arrow" aria-label="引用">
            →
          </span>
          <code className="table-relation-row-target">{relation.references}</code>
        </span>
        <span className="table-relation-row-verdicts">
          <TableRelationBadge verdict={code} muted />
          <TableRelationBadge verdict={database} />
        </span>
      </button>
    </li>
  );
}
