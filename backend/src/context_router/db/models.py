from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    root_path: Mapped[str | None] = mapped_column(String(1024))
    docs_path: Mapped[str | None] = mapped_column(String(1024), unique=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(
        String(40),
        default="never",
        nullable=False,
    )
    last_sync_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, default="")
    parent_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        index=True,
    )

    parent: Mapped[Project | None] = relationship(
        "Project",
        back_populates="children",
        remote_side="Project.id",
    )
    children: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="parent",
    )

    documents: Mapped[list[Document]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    traces: Mapped[list[Trace]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    area: Mapped[str | None] = mapped_column(String(120), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    is_reachable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    graph_depth: Mapped[int | None] = mapped_column(Integer, index=True)

    project: Mapped[Project] = relationship(back_populates="documents")
    retrieval_hits: Mapped[list[RetrievalHit]] = relationship(back_populates="document")
    outgoing_links: Mapped[list[DocumentLink]] = relationship(
        "DocumentLink",
        back_populates="source_document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentLink.source_document_id",
    )
    incoming_links: Mapped[list[DocumentLink]] = relationship(
        "DocumentLink",
        back_populates="target_document",
        foreign_keys="DocumentLink.target_document_id",
    )


class DocumentLink(TimestampMixin, Base):
    __tablename__ = "document_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    target_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(80), default="markdown_link", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    source_document: Mapped[Document] = relationship(
        "Document",
        back_populates="outgoing_links",
        foreign_keys=[source_document_id],
    )
    target_document: Mapped[Document | None] = relationship(
        "Document",
        back_populates="incoming_links",
        foreign_keys=[target_document_id],
    )


class UsageCard(TimestampMixin, Base):
    __tablename__ = "usage_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    cwd: Mapped[str | None] = mapped_column(String(1024))
    area: Mapped[str | None] = mapped_column(String(120), index=True)
    entrypoint_path: Mapped[str | None] = mapped_column(String(1024))
    entrypoint_rule: Mapped[str | None] = mapped_column(Text)
    route_hint: Mapped[str | None] = mapped_column(String(240))
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped[Project] = relationship(back_populates="traces")
    events: Mapped[list[TraceEvent]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="TraceEvent.created_at",
    )
    retrieval_hits: Mapped[list[RetrievalHit]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="RetrievalHit.rank",
    )


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    trace: Mapped[Trace] = relationship(back_populates="events")


class RetrievalHit(Base):
    __tablename__ = "retrieval_hits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    was_returned: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    feedback: Mapped[str | None] = mapped_column(String(40), index=True)

    trace: Mapped[Trace] = relationship(back_populates="retrieval_hits")
    document: Mapped[Document] = relationship(back_populates="retrieval_hits")
