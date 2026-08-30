"use client";

import React, { useCallback, useEffect, useState } from "react";
import { fetchChainAnalyticsOverview } from "../lib/api";
import {
  ChainAnalyticsOverview,
  DocumentHealthMatrixItem,
  BrokenLinkAlertItem,
  AgentComparisonItem,
} from "../lib/types";

interface DocumentChainAnalyticsProps {
  workspaceId?: string;
}

export const DocumentChainAnalyticsPanel: React.FC<DocumentChainAnalyticsProps> = ({ workspaceId }) => {
  const [data, setData] = useState<ChainAnalyticsOverview | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [hours, setHours] = useState<number>(168);

  const loadData = useCallback(async (h: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchChainAnalyticsOverview({ workspace_id: workspaceId, hours: h });
      setData(res);
    } catch (e: any) {
      console.error("Failed to load chain analytics:", e);
      setError(e.message || "加载诊断数据失败");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    loadData(hours);
  }, [hours, loadData]);

  if (loading && !data) {
    return (
      <div className="doc-stats-loading">
        <div style={{ marginBottom: "8px", fontWeight: 500 }}>⚡ 正在计算 Agent 检索效能与链路健康度...</div>
        <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>根据任务上下文分析 Prepare &rarr; Search &rarr; Read 行为数据中</div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="doc-stats-empty" style={{ color: "#dc2626" }}>
        ⚠️ {error}
      </div>
    );
  }

  const { funnel, health_matrix = [], alerts = [], agent_comparison = [] } = data || {};

  const totalTasks = funnel?.total_tasks || 0;
  const directHitTasks = funnel?.direct_hit_tasks || 0;
  const directHitRate = Number(funnel?.direct_hit_rate || 0) * 100;
  const searchRate = Number(funnel?.search_rate || 0) * 100;
  const avgReads = Number(funnel?.avg_reads_per_task || 0);
  const avgSearches = Number(funnel?.avg_searches_per_task || 0);

  const renderHealthBadge = (category: string) => {
    switch (category) {
      case "high_freq_effective":
        return <span className="health-badge health-badge-high-eff">🔥 高频有效</span>;
      case "high_freq_ineffective":
        return <span className="health-badge health-badge-high-ineff">⚠️ 高频失效 (需优化)</span>;
      case "low_freq_effective":
        return <span className="health-badge health-badge-low-eff">✅ 低频有效</span>;
      case "low_freq_ineffective":
      default:
        return <span className="health-badge health-badge-low-ineff">💤 低频不活跃</span>;
    }
  };

  return (
    <div className="analytics-container">
      {/* 顶部标题与筛选栏 */}
      <div className="analytics-header-card">
        <div>
          <h2 className="analytics-title">
            <span>📊</span> Agent 检索效能与链路诊断
          </h2>
          <div className="analytics-subtitle">
            深入诊断上下文导引 (Prepare Task) 的命中率、二次搜索行为及文档健康度
          </div>
        </div>
        <div className="doc-stats-filters">
          <span className="doc-stats-filter-label">时间范围：</span>
          <select
            className="doc-stats-select"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            <option value={24}>近 24 小时</option>
            <option value={72}>近 3 天</option>
            <option value={168}>近 7 天</option>
            <option value={720}>近 30 天</option>
          </select>
        </div>
      </div>

      {/* 核心指标与漏斗图概览 */}
      <div className="analytics-section-card">
        <h3 className="analytics-section-title">
          <span>🎯</span> 检索链路漏斗与效率指标
        </h3>

        <div className="analytics-funnel-grid">
          <div className="analytics-metric-card">
            <span className="analytics-metric-label">分析任务总量</span>
            <span className="analytics-metric-val">{totalTasks}</span>
            <span className="analytics-metric-desc">包含上下文导引的独立任务数</span>
          </div>

          <div className="analytics-metric-card">
            <span className="analytics-metric-label">Prepare 直达命中率</span>
            <span className="analytics-metric-val" style={{ color: "#2563eb" }}>
              {directHitRate.toFixed(1)}%
            </span>
            <span className="analytics-metric-desc">无须补搜直达文档 ({directHitTasks} 任务)</span>
            <div className="analytics-bar-track">
              <div
                className="analytics-bar-fill analytics-bar-blue"
                style={{ width: `${Math.min(directHitRate, 100)}%` }}
              />
            </div>
          </div>

          <div className="analytics-metric-card">
            <span className="analytics-metric-label">二次搜索发起率</span>
            <span className="analytics-metric-val" style={{ color: "#d97706" }}>
              {searchRate.toFixed(1)}%
            </span>
            <span className="analytics-metric-desc">导引不足导致重新搜索</span>
            <div className="analytics-bar-track">
              <div
                className="analytics-bar-fill analytics-bar-amber"
                style={{ width: `${Math.min(searchRate, 100)}%` }}
              />
            </div>
          </div>

          <div className="analytics-metric-card">
            <span className="analytics-metric-label">单任务平均探索度</span>
            <span className="analytics-metric-val" style={{ color: "#059669" }}>
              {avgReads.toFixed(2)} <span style={{ fontSize: "0.85rem", fontWeight: 400 }}>篇阅读</span>
            </span>
            <span className="analytics-metric-desc">平均交互 {avgSearches.toFixed(2)} 次搜索</span>
          </div>
        </div>
      </div>

      {/* 两列布局： Agent 效能对比 & 链路异常告警 */}
      <div className="analytics-grid-2">
        {/* Agent 维度性能对比 */}
        <div className="analytics-section-card">
          <h3 className="analytics-section-title">
            <span>🤖</span> Agent 客户端效能对比
          </h3>
          {agent_comparison.length === 0 ? (
            <div className="doc-stats-empty" style={{ padding: "24px 0" }}>暂无 Agent 效能数据</div>
          ) : (
            <div className="analytics-table-wrapper">
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Agent 名称</th>
                    <th>任务数</th>
                    <th>直达率</th>
                    <th>均次搜索</th>
                    <th>均次阅读</th>
                  </tr>
                </thead>
                <tbody>
                  {agent_comparison.map((agent: AgentComparisonItem) => {
                    const hitRate = Number(agent.direct_hit_rate || 0) * 100;
                    return (
                      <tr key={agent.agent_name}>
                        <td style={{ fontWeight: 600, color: "var(--foreground)" }}>{agent.agent_name}</td>
                        <td>{agent.total_tasks}</td>
                        <td style={{ color: hitRate > 50 ? "#059669" : "#2563eb", fontWeight: 600 }}>
                          {hitRate.toFixed(1)}%
                        </td>
                        <td>{Number(agent.avg_searches || 0).toFixed(2)}</td>
                        <td>{Number(agent.avg_reads || 0).toFixed(2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 链路健康与告警 */}
        <div className="analytics-section-card">
          <h3 className="analytics-section-title">
            <span>🚨</span> 诊断告警与失效追踪 ({alerts.length})
          </h3>
          {alerts.length === 0 ? (
            <div className="doc-stats-empty" style={{ padding: "24px 0", color: "#059669" }}>
              🎉 链路表现优异，未发现高频失效或导引断层
            </div>
          ) : (
            <div className="alert-list">
              {alerts.map((alert: BrokenLinkAlertItem, idx: number) => {
                const isHighRisk = alert.alert_type === "high_search_after_read";
                return (
                  <div
                    key={idx}
                    className={`alert-item ${!isHighRisk ? "alert-item-warning" : ""}`}
                  >
                    <div className="alert-icon">{isHighRisk ? "🚨" : "⚠️"}</div>
                    <div className="alert-content">
                      <div className="alert-title">{alert.message || "链路异常警告"}</div>
                      {alert.task_prompt && <p className="alert-desc">任务 Prompt: {alert.task_prompt}</p>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* 文档健康度象限矩阵 */}
      <div className="analytics-section-card">
        <h3 className="analytics-section-title">
          <span>🩺</span> 核心文档健康度象限矩阵 (Top 15)
        </h3>
        {health_matrix.length === 0 ? (
          <div className="doc-stats-empty" style={{ padding: "24px 0" }}>暂无文档健康度象限数据</div>
        ) : (
          <div className="analytics-table-wrapper">
            <table className="analytics-table">
              <thead>
                <tr>
                  <th>文档路径</th>
                  <th>健康度象限</th>
                  <th>阅读次数</th>
                  <th>关联任务数</th>
                  <th>读后二次搜索率</th>
                </tr>
              </thead>
              <tbody>
                {health_matrix.map((doc: DocumentHealthMatrixItem) => {
                  const searchAfterRate = Number(doc.search_after_read_rate || 0) * 100;
                  return (
                    <tr key={doc.document_id}>
                      <td style={{ maxWidth: "320px", wordBreak: "break-all", fontFamily: "monospace", fontSize: "0.78rem" }}>
                        {doc.document_path || doc.document_id}
                      </td>
                      <td>{renderHealthBadge(doc.health_category)}</td>
                      <td style={{ fontWeight: 600 }}>{doc.read_count}</td>
                      <td>{doc.task_count}</td>
                      <td style={{ color: searchAfterRate > 40 ? "#dc2626" : "var(--foreground)" }}>
                        {searchAfterRate.toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
