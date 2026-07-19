from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from context_router.db.models import Base, Project
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document
from context_router.services.retrieval import retrieve_documents


def test_retrieval_prefers_documents_matching_task_area_tags_and_text() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="my-app", name="My App")
        session.add(project)
        session.flush()

        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="payments-webhook-timeout-history",
                title="Payments webhook timeout history",
                source_path="docs/payments-timeout.md",
                doc_type="debugging",
                area="payments",
                tags=["webhook", "timeout"],
                content_markdown=(
                    "# Payments\nWebhook timeout happened after retry headers changed."
                ),
            ),
        )
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="frontend-theme-guide",
                title="Frontend theme guide",
                source_path="docs/frontend-theme.md",
                doc_type="architecture",
                area="frontend",
                tags=["react", "theme"],
                content_markdown="# Frontend\nTheme tokens and layout notes.",
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=project,
            task="修复 payments webhook timeout",
            max_documents=2,
        )

    assert [result.document_id for result in results] == [
        "payments-webhook-timeout-history",
        "frontend-theme-guide",
    ]
    assert results[0].score > results[1].score
    assert "payments" in results[0].reason
    assert "timeout" in results[0].excerpt


def test_retrieval_can_route_by_explicit_area() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="my-app", name="My App")
        session.add(project)
        session.flush()

        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="payments-webhook-runbook",
                title="Payments webhook runbook",
                source_path="docs/payments.md",
                doc_type="runbook",
                area="payments",
                tags=["webhook"],
                content_markdown="# Payments\nWebhook retry guidance.",
            ),
        )
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="frontend-react-guide",
                title="Frontend React guide",
                source_path="docs/frontend.md",
                doc_type="architecture",
                area="frontend",
                tags=["react"],
                content_markdown="# Frontend\nReact webhook examples.",
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=project,
            task="fix react webhook",
            area="payments",
            max_documents=5,
        )

    assert [result.document_id for result in results] == ["payments-webhook-runbook"]


def test_retrieval_includes_child_project_documents_from_parent_project() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        parent = Project(slug="workspace", name="Workspace")
        session.add(parent)
        session.flush()
        child = Project(
            slug="word-select-dashboard-web-react",
            name="Word Select Dashboard Web React",
            parent_project_id=parent.id,
        )
        session.add(child)
        session.flush()

        upsert_document(
            session,
            project=child,
            document=DocumentCreate(
                id="word-select-dashboard-web-react-ai-context",
                title="上下文路由入口: word-select-dashboard-web-react",
                source_path="AI_CONTEXT_INDEX.md",
                doc_type="routing_index",
                area="agent",
                tags=["context", "routing"],
                content_markdown=(
                    "# AI_CONTEXT_INDEX\nword select dashboard web react 单词选择页面功能链路。"
                ),
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=parent,
            task="查询 word select dashboard web react 单词选择页面功能链路",
            area="frontend",
            max_documents=5,
        )

    assert [result.document_id for result in results] == [
        "word-select-dashboard-web-react-ai-context"
    ]


def test_retrieval_keeps_entry_documents_available_when_area_is_set() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="my-app", name="My App")
        session.add(project)
        session.flush()

        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="my-app-ai-context",
                title="上下文路由入口: my-app",
                source_path="AI_CONTEXT_INDEX.md",
                doc_type="routing_index",
                area="agent",
                tags=["context", "routing"],
                content_markdown="# AI_CONTEXT_INDEX\nfrontend route for my app.",
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=project,
            task="frontend route",
            area="frontend",
            max_documents=5,
        )

    assert [result.document_id for result in results] == ["my-app-ai-context"]


def test_retrieval_prefers_usage_step_over_noisy_child_entry_for_prepare_task() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        parent = Project(slug="workspace", name="Workspace")
        session.add(parent)
        session.flush()
        child = Project(
            slug="word-select-dashboard-web-react",
            name="Word Select Dashboard Web React",
            parent_project_id=parent.id,
        )
        session.add(child)
        session.flush()

        upsert_document(
            session,
            project=parent,
            document=DocumentCreate(
                id="context-router-prepare-guide",
                title="准备任务上下文",
                source_path="docs/managed/context-router-prepare-guide.md",
                doc_type="usage_step",
                area="agent",
                tags=["prepare", "context"],
                content_markdown=(
                    "# 准备任务上下文\n本文件说明 AI 什么时候使用 ctx prepare 准备任务上下文。"
                ),
            ),
        )
        upsert_document(
            session,
            project=child,
            document=DocumentCreate(
                id="word-select-dashboard-web-react-ai-context",
                title="上下文路由入口: word-select-dashboard-web-react",
                source_path="AI_CONTEXT_INDEX.md",
                doc_type="routing_index",
                area="agent",
                tags=["context", "routing"],
                content_markdown=(
                    "# AI_CONTEXT_INDEX\n"
                    "ctx prepare ctx prepare ctx prepare ctx prepare ctx prepare "
                    "web react dashboard route."
                ),
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=parent,
            task="开发新功能前 AI 如何使用 ctx prepare 准备任务上下文",
            max_documents=2,
        )

    assert results[0].document_id == "context-router-prepare-guide"


def test_retrieval_prefers_requested_area_route_for_parent_project() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        parent = Project(slug="workspace", name="Workspace")
        session.add(parent)
        session.flush()
        child = Project(
            slug="word-agent",
            name="Word Agent",
            parent_project_id=parent.id,
        )
        session.add(child)
        session.flush()

        upsert_document(
            session,
            project=parent,
            document=DocumentCreate(
                id="context-router-area-backend",
                title="后端路由",
                source_path="docs/managed/context-router-area-backend.md",
                doc_type="area_route",
                area="backend",
                tags=["backend", "api"],
                content_markdown="# 后端路由\nFastAPI ctx prepare ctx read trace CLI MCP。",
            ),
        )
        upsert_document(
            session,
            project=child,
            document=DocumentCreate(
                id="word-agent-ai-context",
                title="上下文路由入口: word-agent",
                source_path="AI_CONTEXT_INDEX.md",
                doc_type="routing_index",
                area="agent",
                tags=["context", "routing"],
                content_markdown="backend backend backend API API agent model ctx prepare.",
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=parent,
            task="修改后端 API ctx prepare trace 逻辑",
            area="backend",
            max_documents=2,
        )

    assert results[0].document_id == "context-router-area-backend"


def test_retrieval_matches_chinese_phrase_variants_with_bigrams() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        parent = Project(slug="workspace", name="Workspace")
        session.add(parent)
        session.flush()
        child = Project(
            slug="child-web",
            name="Child Web",
            parent_project_id=parent.id,
        )
        session.add(child)
        session.flush()

        upsert_document(
            session,
            project=parent,
            document=DocumentCreate(
                id="context-router-project-entry-guide",
                title="子项目入口文档说明",
                source_path="docs/managed/context-router-project-entry-guide.md",
                doc_type="project_entry_guide",
                area="agent",
                tags=["project", "entry"],
                content_markdown=(
                    "# 子项目入口文档说明\n"
                    "本文件说明 AGENTS.md 和 AI_CONTEXT_INDEX.md 如何关联到各个子项目。"
                ),
            ),
        )
        upsert_document(
            session,
            project=child,
            document=DocumentCreate(
                id="child-web-ai-context",
                title="上下文路由入口: child-web",
                source_path="AI_CONTEXT_INDEX.md",
                doc_type="routing_index",
                area="agent",
                tags=["context", "routing"],
                content_markdown="AI_CONTEXT_INDEX AGENTS.md 子项目 入口 ctx prepare。",
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=parent,
            task="子项目入口文档说明是什么，怎么关联 AGENTS 和 AI_CONTEXT_INDEX",
            max_documents=2,
        )

    assert results[0].document_id == "context-router-project-entry-guide"
