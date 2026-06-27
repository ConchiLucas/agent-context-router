from context_router.schemas.context import ContextDocument


def render_context_markdown(
    *,
    trace_id: str,
    project: str,
    results: list[ContextDocument],
) -> str:
    lines = [
        f"trace_id: {trace_id}",
        f"project: {project}",
        "",
        "## Required Context",
    ]

    if not results:
        lines.extend(
            [
                "",
                "No matching documents were found. Continue carefully and mention this gap.",
            ]
        )
        return "\n".join(lines)

    for result in results:
        lines.extend(
            [
                "",
                f"{result.rank}. {result.document_id}",
                f"   title: {result.title}",
                f"   score: {result.score:.2f}",
                f"   reason: {result.reason}",
                f"   excerpt: {result.excerpt}",
                "   follow_up:",
                f'   ctx read {result.document_id} --trace {trace_id} --reason "<why needed>"',
            ]
        )

    return "\n".join(lines)
