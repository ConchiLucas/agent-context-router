"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { MarkdownViewer } from "@/components/markdown-viewer";
import { listManagedRules } from "@/lib/api";
import type { ManagedRule } from "@/lib/types";

function combinedMarkdown(rules: ManagedRule[]): string {
  return rules
    .map((rule) => {
      const body = rule.body.trim();
      if (body.startsWith("#")) {
        return body;
      }
      return `## ${rule.title}\n\n${body}`;
    })
    .join("\n\n");
}

export function ManagedRulesManager() {
  const [rules, setRules] = useState<ManagedRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await listManagedRules();
      setRules(next.rules);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取规则失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const document = useMemo(() => combinedMarkdown(rules), [rules]);

  return (
    <section className="shared-ai-page managed-rules-page" aria-label="规则管理">
      <div className="shared-ai-content">
        {error ? (
          <p className="error-banner" role="alert">
            {error}
          </p>
        ) : null}
        {loading ? <p className="empty-message">正在读取规则…</p> : null}
        {!loading && !document ? (
          <p className="empty-message">还没有控制面规则。</p>
        ) : null}
        {!loading && document ? (
          <article className="managed-rule-card">
            <MarkdownViewer content={document} />
          </article>
        ) : null}
      </div>
    </section>
  );
}
