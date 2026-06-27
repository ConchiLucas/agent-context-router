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
