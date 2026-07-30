import type { EnvironmentJsonObject } from "@/lib/types";

export const ENVIRONMENT_JSON_TOTAL_MAX_BYTES = 256 * 1024;

export type EnvironmentJsonParseResult =
  | { ok: true; value: EnvironmentJsonObject }
  | { ok: false; error: string };

export function environmentJsonByteLength(sources: readonly string[]): number {
  const encoder = new TextEncoder();
  return sources.reduce(
    (total, source) => total + encoder.encode(source).byteLength,
    0,
  );
}

export function parseEnvironmentJson(
  source: string,
): EnvironmentJsonParseResult {
  if (!source.trim()) {
    return { ok: false, error: "JSON 不能为空" };
  }
  try {
    let hasUnsafeNumber = false;
    const value = JSON.parse(source, (_key, item: unknown) => {
      if (
        typeof item === "number" &&
        (!Number.isFinite(item) ||
          (Number.isInteger(item) && !Number.isSafeInteger(item)))
      ) {
        hasUnsafeNumber = true;
      }
      return item;
    }) as unknown;
    if (hasUnsafeNumber) {
      return {
        ok: false,
        error: "JSON 含超出 JavaScript 安全整数范围的数字，请改用字符串",
      };
    }
    if (value === null || Array.isArray(value) || typeof value !== "object") {
      return {
        ok: false,
        error: "环境 JSON 顶层必须是对象",
      };
    }
    return { ok: true, value: value as EnvironmentJsonObject };
  } catch {
    return {
      ok: false,
      error: "JSON 语法不正确，请检查括号、引号和逗号",
    };
  }
}

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
