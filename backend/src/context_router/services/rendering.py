from context_router.schemas.context import ContextDocument


def render_context_markdown(
    *,
    project: str,
    area: str | None,
    entrypoint_path: str | None,
    entrypoint_rule: str | None,
    route_hint: str | None,
    results: list[ContextDocument],
) -> str:
    lines = [
        f"project: {project}",
    ]
    if area:
        lines.append(f"area: {area}")
    if entrypoint_path:
        lines.append(f"entrypoint_path: {entrypoint_path}")
    if entrypoint_rule:
        lines.append(f"entrypoint_rule: {entrypoint_rule}")
    if route_hint:
        lines.append(f"route_hint: {route_hint}")
    lines.extend(["", "## Required Context"])

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
                f"   ctx read {result.document_id}",
            ]
        )

    return "\n".join(lines)
