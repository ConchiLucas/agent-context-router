import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from context_router.db.models import UsageCard
from context_router.db.session import get_session
from context_router.schemas.usage import (
    UsageCardCreate,
    UsageCardDeleteResponse,
    UsageCardListResponse,
    UsageCardResponse,
    UsageCardUpdate,
)

router = APIRouter(prefix="/api/usage", tags=["usage"])

DEFAULT_CTX_CARD_SLUG = "ctx-session-usage"
DEFAULT_CTX_CARD_MARKDOWN = """# ctx / SESSION_ID 使用说明

## 初始化变量

不要假设 `ctx` 已经在 `PATH` 中。进入项目后，先在当前 shell 中定义：

```bash
CTX="/Users/conchi/workforce/python_workforce/agent-context-router/bin/ctx"
SESSION_ID="<当前 AI 对话固定 session id>"
```

`SESSION_ID` 由 AI 在当前对话开始时自行设置。
如果运行环境提供稳定的 thread/conversation id，优先使用该 id；
否则生成一个本轮唯一且可读的字符串，例如：

```bash
SESSION_ID="rob-english-word-workforce-codex-20260703-001"
```

同一个 AI 对话窗口内，后续所有 `ctx read` / `ctx prepare`
必须复用同一个 `SESSION_ID`，不要每次读取时重新生成。

## 读取 AGENTS.md 链路文档

读取 `AGENTS.md` 递归关联出来的 Markdown 文档时，统一使用：

```bash
"$CTX" read <doc-id> --session "$SESSION_ID"
```

如果文档继续指向下一层文档，也继续通过 ctx 读取，并保留 `from_doc -> to_doc` 的来源关系。

## 兜底检索

只有无法判断 doc-id 时，才使用 prepare 兜底：

```bash
"$CTX" prepare --project <project-slug> --session "$SESSION_ID"
```

## 同步本地 Markdown

修改本地 Markdown 后，在对应项目根目录运行：

```bash
"$CTX" doc sync --project <project-slug> --docs-dir . --prune
```
"""


@router.get("/cards", response_model=UsageCardListResponse)
def list_usage_cards(
    session: Annotated[Session, Depends(get_session)],
) -> UsageCardListResponse:
    _ensure_default_usage_card(session)
    cards = session.scalars(select(UsageCard).order_by(UsageCard.sort_order, UsageCard.title)).all()
    return UsageCardListResponse(cards=[UsageCardResponse.model_validate(card) for card in cards])


@router.post("/cards", response_model=UsageCardResponse)
def create_usage_card(
    card: UsageCardCreate,
    session: Annotated[Session, Depends(get_session)],
) -> UsageCardResponse:
    _ensure_default_usage_card(session)
    slug = _unique_slug(session, card.slug or card.title)
    saved = UsageCard(
        slug=slug,
        title=card.title.strip(),
        description=card.description.strip(),
        content_markdown=card.content_markdown,
        sort_order=card.sort_order if card.sort_order is not None else _next_sort_order(session),
        is_builtin=False,
    )
    _validate_card(saved)
    session.add(saved)
    session.commit()
    session.refresh(saved)
    return UsageCardResponse.model_validate(saved)


@router.get("/cards/{slug}", response_model=UsageCardResponse)
def get_usage_card(
    slug: str,
    session: Annotated[Session, Depends(get_session)],
) -> UsageCardResponse:
    _ensure_default_usage_card(session)
    card = _get_card_or_404(session, slug)
    return UsageCardResponse.model_validate(card)


@router.put("/cards/{slug}", response_model=UsageCardResponse)
def update_usage_card(
    slug: str,
    updates: UsageCardUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> UsageCardResponse:
    _ensure_default_usage_card(session)
    card = _get_card_or_404(session, slug)
    card.title = updates.title.strip()
    card.description = updates.description.strip()
    card.content_markdown = updates.content_markdown
    if updates.sort_order is not None:
        card.sort_order = updates.sort_order
    _validate_card(card)
    session.commit()
    session.refresh(card)
    return UsageCardResponse.model_validate(card)


@router.delete("/cards/{slug}", response_model=UsageCardDeleteResponse)
def delete_usage_card(
    slug: str,
    session: Annotated[Session, Depends(get_session)],
) -> UsageCardDeleteResponse:
    _ensure_default_usage_card(session)
    card = _get_card_or_404(session, slug)
    if card.is_builtin:
        raise HTTPException(status_code=400, detail="Builtin usage cards cannot be deleted")
    session.delete(card)
    session.commit()
    return UsageCardDeleteResponse(deleted=True)


def _ensure_default_usage_card(session: Session) -> None:
    existing = session.scalar(select(UsageCard).where(UsageCard.slug == DEFAULT_CTX_CARD_SLUG))
    if existing is not None:
        return

    session.add(
        UsageCard(
            slug=DEFAULT_CTX_CARD_SLUG,
            title="ctx / SESSION_ID 使用说明",
            description="AGENTS.md 链路文档读取、SESSION_ID 生成与复用规则。",
            content_markdown=DEFAULT_CTX_CARD_MARKDOWN,
            sort_order=10,
            is_builtin=True,
        )
    )
    session.commit()


def _get_card_or_404(session: Session, slug: str) -> UsageCard:
    card = session.scalar(select(UsageCard).where(UsageCard.slug == slug))
    if card is None:
        raise HTTPException(status_code=404, detail=f"Usage card not found: {slug}")
    return card


def _validate_card(card: UsageCard) -> None:
    if not card.title:
        raise HTTPException(status_code=422, detail="Title is required")
    if not card.content_markdown.strip():
        raise HTTPException(status_code=422, detail="Markdown content is required")


def _next_sort_order(session: Session) -> int:
    max_sort_order = session.scalar(select(func.max(UsageCard.sort_order)))
    return int(max_sort_order or 0) + 10


def _unique_slug(session: Session, value: str) -> str:
    base = _slugify(value)
    candidate = base
    suffix = 2
    while session.scalar(select(UsageCard).where(UsageCard.slug == candidate)) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "usage-card"
