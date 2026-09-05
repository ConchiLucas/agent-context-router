export function scriptKindLabel(kind: string) {
  if (kind === "workspace_autostart") {
    return "开机";
  }
  if (kind === "workspace_ai") {
    return "AI";
  }
  return kind;
}

export function scriptCountText(scriptCount: number, autostartCount: number) {
  return `${scriptCount} total / ${autostartCount} autostart`;
}
