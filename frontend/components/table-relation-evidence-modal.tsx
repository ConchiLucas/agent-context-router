"use client";

import { useEffect, useState } from "react";

import { TableRelationBadge } from "@/components/table-relation-badge";
import {
  cardinalityBadge,
  codeEvidenceExplanation,
  dbEvidenceExplanation,
  groupRelationSites,
  missingSitesNote,
  relationCheckCopy,
  relationVerdicts,
  siteKindExplanation,
  siteKindTitle,
} from "@/lib/table-relations";
import type {
  TableRelationCheck,
  TableRelationCodeSite,
  TableRelationDetail,
} from "@/lib/types";

/**
 * Why one relation reads the way it does.
 *
 * The list can say what the verdict is; only this can say why, and the whole
 * point of saying why is that the reader can then disagree. So every claim here
 * carries something to check it against: each number is published next to the
 * query that produced it, and the query is the one that was actually run, down to
 * the soft-delete filter and how an unset key is spelled.
 *
 * The two dimensions sit side by side because the model is that they can
 * disagree. Reading them one after the other would turn a comparison into an act
 * of memory.
 */
export function TableRelationEvidenceModal({
  detail,
  onClose,
}: {
  detail: TableRelationDetail;
  onClose: () => void;
}) {
  const { relation, measurement, checks } = detail;
  const [code, database] = relationVerdicts(relation);
  const siteGroups = groupRelationSites(detail.code_sites);

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
        aria-label={`关系 ${relation.relation_id} 的依据`}
      >
        <header className="relation-evidence-header">
          <div className="relation-evidence-title">
            <p className="table-relation-row-identity">
              <code className="table-relation-row-id">{relation.relation_id}</code>
              <span className="table-relation-row-arrow" aria-label="引用">
                →
              </span>
              <code className="table-relation-row-target">{relation.references}</code>
            </p>
            {/* Which end this reading is from. The cardinalities depend on it, so
                leaving it implicit would make two correct readings look like a
                contradiction. */}
            <p className="relation-evidence-context">
              从 {detail.table.table_name} 这一侧看
            </p>
          </div>
          <span className="table-relation-row-verdicts">
            <TableRelationBadge verdict={code} muted />
            <TableRelationBadge verdict={database} />
          </span>
          <button
            type="button"
            className="close-button"
            aria-label="关闭关系依据"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="relation-evidence-body">
          <div className="relation-evidence-dimensions">
            <section className="relation-evidence-dimension" data-dimension="code">
              <h3>代码维度</h3>
              <p className="relation-evidence-verdict">
                <span className="relation-evidence-glyph">{code.glyph}</span>
                <span className="relation-evidence-evidence">{code.evidenceLabel}</span>
              </p>
              <p className="relation-evidence-explanation">
                {codeEvidenceExplanation(relation.code_evidence)}
              </p>
              <p className="relation-evidence-caveat">
                这个结论来自读写入路径，不是编译器算出来的。
              </p>
              <Timestamp label="读代码" value={relation.code_checked_at} />
            </section>

            <section className="relation-evidence-dimension" data-dimension="db">
              <h3>数据库维度</h3>
              <p className="relation-evidence-verdict">
                <span className="relation-evidence-glyph">{database.glyph}</span>
                <span className="relation-evidence-evidence">{database.evidenceLabel}</span>
              </p>
              <p className="relation-evidence-explanation">
                {dbEvidenceExplanation(relation.db_evidence)}
              </p>
              <Timestamp label="测数据" value={relation.db_measured_at} />
            </section>
          </div>

          {siteGroups.length > 0 ? (
            siteGroups.map((group) => (
              <section
                key={group.role}
                className="relation-evidence-sites"
                data-role={group.role}
              >
                <h3>{group.title}</h3>
                <p className="relation-evidence-group-note">{group.note}</p>
                <ol>
                  {group.sites.map((site, index) => (
                    <SiteRow key={`${site.file_path}-${site.kind}-${index}`} site={site} />
                  ))}
                </ol>
              </section>
            ))
          ) : (
            <MissingSites relation={relation} />
          )}

          <section className="relation-evidence-checks">
            <h3>体检项</h3>
            <ol>
              {checks.map((check) => (
                <CheckRow key={check.key} check={check} measurement={measurement} />
              ))}
            </ol>
          </section>
        </div>
      </section>
    </div>
  );
}

/**
 * One place in the source, with enough to find it and nothing that can go stale.
 *
 * No line number is shown because none is stored: the file, the method and the
 * snippet are what a reader searches for, and all three survive an edit that
 * merely moves the code. A line number would keep looking exact after it stopped
 * being right.
 */
function SiteRow({ site }: { site: TableRelationCodeSite }) {
  const badge = cardinalityBadge(site.implies);

  return (
    <li className="relation-evidence-site">
      <div className="relation-evidence-site-head">
        <h4>{siteKindTitle(site.kind)}</h4>
        <span className="relation-evidence-site-implies" title={`支持${badge.label}`}>
          {badge.glyph}
        </span>
      </div>
      <p className="relation-evidence-check-summary">{siteKindExplanation(site.kind)}</p>
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

/**
 * Said out loud rather than left as an empty area.
 *
 * A blank space where evidence should be reads as "there is none", which is a
 * different and much stronger claim than "nobody has written it down".
 */
function MissingSites({ relation }: { relation: TableRelationDetail["relation"] }) {
  const note = missingSitesNote(relation);
  if (note === null) return null;
  return (
    <section className="relation-evidence-sites" data-role="missing">
      <h3>写入入口</h3>
      <p className="relation-evidence-group-note">{note}</p>
    </section>
  );
}

function CheckRow({
  check,
  measurement,
}: {
  check: TableRelationCheck;
  measurement: TableRelationDetail["measurement"];
}) {
  const copy = relationCheckCopy(check, measurement);

  return (
    <li className="relation-evidence-check" data-outcome={check.outcome}>
      <div className="relation-evidence-check-head">
        <h4>{copy.title}</h4>
        <span className="relation-evidence-outcome">{copy.outcomeLabel}</span>
      </div>
      <p className="relation-evidence-check-summary">{copy.summary}</p>
      <CopyableSql sql={check.sql} label={copy.title} />
    </li>
  );
}

/**
 * The query, offered to be taken away and run.
 *
 * Displaying it is what makes the number above it a claim rather than an
 * assertion, and copying is how that offer is actually taken up — nobody
 * retypes a nine-line join.
 */
function CopyableSql({ sql, label }: { sql: string; label: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="relation-evidence-sql">
      <div className="relation-evidence-sql-head">
        <span>复算 SQL</span>
        <button
          type="button"
          className="secondary-button"
          aria-label={`复制${label}的 SQL`}
          onClick={() => void copy()}
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre>
        <code>{sql}</code>
      </pre>
    </div>
  );
}

/**
 * When this side was last looked at.
 *
 * The two sides are refreshed on their own schedules, so a disagreement between
 * them is only a finding once you know both readings are current.
 */
function Timestamp({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <p className="relation-evidence-timestamp">
      {label}：
      <time dateTime={value}>
        {new Intl.DateTimeFormat("zh-CN", {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(value))}
      </time>
    </p>
  );
}
