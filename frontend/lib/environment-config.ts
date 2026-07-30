import type { EnvironmentJsonObject } from "@/lib/types";

export function formatEnvironmentJson(value: EnvironmentJsonObject): string {
  const entries = Object.entries(value).sort(([left], [right]) => {
    if (left === "middleware") return -1;
    if (right === "middleware") return 1;
    return 0;
  });
  if (entries.length === 0) return "{}";

  const body = entries
    .map(([key, item]) => {
      const formattedValue = JSON.stringify(item, null, 2) ?? "null";
      return `  ${JSON.stringify(key)}: ${formattedValue.replaceAll("\n", "\n  ")}`;
    })
    .join(",\n");
  return `{\n${body}\n}`;
}
