from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RetrievalFunnelMetrics(BaseModel):
    total_tasks: int
    direct_hit_tasks: int
    search_then_read_tasks: int
    deep_search_tasks: int
    direct_hit_rate: float
    search_rate: float
    avg_reads_per_task: float
    avg_searches_per_task: float


class DocumentHealthMatrixItem(BaseModel):
    document_id: str
    document_path: str | None = None
    read_count: int
    task_count: int
    search_after_read_count: int
    search_after_read_rate: float
    health_category: str  # high_freq_effective | high_freq_ineffective | low_freq_effective | low_freq_ineffective


class BrokenLinkAlertItem(BaseModel):
    alert_type: str  # search_no_results | read_error | loop_search | deep_traversal
    task_id: int
    task_prompt: str | None = None
    agent_name: str | None = None
    message: str
    created_at: datetime


class AgentComparisonItem(BaseModel):
    agent_name: str
    total_tasks: int
    avg_searches: float
    avg_reads: float
    direct_hit_rate: float


class DocumentChainAnalyticsResponse(BaseModel):
    funnel: RetrievalFunnelMetrics
    health_matrix: list[DocumentHealthMatrixItem]
    alerts: list[BrokenLinkAlertItem]
    agent_comparison: list[AgentComparisonItem]
