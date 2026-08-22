type RequestOrderedInterface = {
  last_requested_at: string | null;
  path: string;
  method: string;
};

export function sortInterfacesByLastRequest<T extends RequestOrderedInterface>(items: T[]): T[] {
  return [...items].sort((left, right) => {
    const leftTime = left.last_requested_at ? Date.parse(left.last_requested_at) : Number.NEGATIVE_INFINITY;
    const rightTime = right.last_requested_at ? Date.parse(right.last_requested_at) : Number.NEGATIVE_INFINITY;
    if (leftTime !== rightTime) return rightTime - leftTime;
    const pathOrder = left.path.localeCompare(right.path, "en", { sensitivity: "base" });
    return pathOrder || left.method.localeCompare(right.method, "en", { sensitivity: "base" });
  });
}
