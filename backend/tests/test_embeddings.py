from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from context_router.db.models import Base, Project
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document
from context_router.services.embeddings import NoopEmbeddingProvider
from context_router.services.retrieval import retrieve_documents


def test_noop_embedding_provider_keeps_retrieval_local_and_deterministic() -> None:
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
                id="payments-runbook",
                title="Payments runbook",
                source_path="docs/payments.md",
                doc_type="runbook",
                area="payments",
                tags=["payments"],
                content_markdown="# Payments\nFix payment retry issues.",
            ),
        )
        session.commit()

        results = retrieve_documents(
            session,
            project=project,
            task="payments retry",
            max_documents=1,
            embedding_provider=NoopEmbeddingProvider(),
        )

    assert results[0].document_id == "payments-runbook"
    assert NoopEmbeddingProvider().embed(["hello", "world"]) == [None, None]
