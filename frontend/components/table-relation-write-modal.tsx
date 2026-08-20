"use client";

import { useEffect } from "react";

import {
  missingUpdatesNote,
  missingWritesNote,
  writeKindExplanation,
  writeKindTitle,
} from "@/lib/table-relations";
import type {
  TableRelationTableIdentity,
  TableRelationPersistKind,
} from "@/lib/types";

interface PersistSite {
  kind: TableRelationPersistKind;
  file_path: string;
  method_name: string;
  snippet: string;
}

/**
 * Insert or update calls recorded against the currently selected table.
 *
 * This is not the relation evidence panel. Those cards say how a parent key is
 * assigned; these say which methods persist this table's rows. The same file and
 * method can appear in both, and that is not duplication.
 */
export function TableRelationWriteModal({
  table,
  sites,
  mode,
  onClose,
}: {
  table: TableRelationTableIdentity;
  sites: PersistSite[];
  mode: "insert" | "update";
  onClose: () => void;
}) {
  const title = mode === "insert" ? "插入入口" : "更新入口";
  const note =
    mode === "insert"
      ? "这些方法会向这张表插入行。"
      : "这些方法会更新这张表已有的行。";
  const empty = mode === "insert" ? missingWritesNote() : missingUpdatesNote();

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="relation-evidence-modal" role="presentation">
      <section
        className="relation-evidence-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${table.table_name} 的${title}`}
      >
        <header className="relation-evidence-header">
          <div className="relation-evidence-title">
            <p className="table-relation-row-identity">
              <code className="table-relation-row-id">{table.table_name}</code>
            </p>
            <p className="relation-evidence-context">
              {table.database_key}.{table.schema_name}
            </p>
          </div>
          <button
            type="button"
            className="close-button"
            aria-label={`关闭${title}`}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="relation-evidence-body">
          <section className="relation-evidence-sites" data-role={mode}>
            <h3>{title}</h3>
            {sites.length > 0 ? (
              <>
                <p className="relation-evidence-group-note">{note}</p>
                <ol>
                  {sites.map((site, index) => (
                    <PersistRow
                      key={`${site.file_path}-${site.method_name}-${index}`}
                      site={site}
                    />
                  ))}
                </ol>
              </>
            ) : (
              <p className="relation-evidence-group-note">{empty}</p>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}

function PersistRow({ site }: { site: PersistSite }) {
  return (
    <li className="relation-evidence-site">
      <div className="relation-evidence-site-head">
        <h4>{writeKindTitle(site.kind)}</h4>
      </div>
      <p className="relation-evidence-check-summary">{writeKindExplanation(site.kind)}</p>
      <p className="relation-evidence-site-location">
        <code>{site.file_path}</code>
        <span className="relation-evidence-site-method">{site.method_name}</span>
      </p>
      <pre className="relation-evidence-snippet">
        <code>{site.snippet}</code>
      </pre>
    </li>
  );
}
