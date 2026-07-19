import type { ReactNode } from "react";

type MarkdownContentProps = Readonly<{
  content: string;
}>;

type MarkdownBlock =
  | { kind: "blockquote"; lines: string[] }
  | { kind: "code"; code: string; language: string }
  | { kind: "heading"; depth: number; text: string }
  | { kind: "hr" }
  | { kind: "list"; items: string[]; ordered: boolean }
  | { kind: "paragraph"; text: string }
  | { kind: "table"; headers: string[]; rows: string[][] };

export function MarkdownContent({ content }: MarkdownContentProps) {
  const blocks = parseMarkdown(content);

  return (
    <div className="markdown-content">
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
}

function parseMarkdown(content: string) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (trimmed === "") {
      index += 1;
      continue;
    }

    const fence = trimmed.match(/^```([a-zA-Z0-9_-]+)?\s*$/);
    if (fence) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({
        kind: "code",
        code: codeLines.join("\n"),
        language: fence[1] ?? "",
      });
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      blocks.push({
        kind: "heading",
        depth: heading[1].length,
        text: heading[2],
      });
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push({ kind: "hr" });
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const headers = splitTableRow(lines[index]);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push({ kind: "table", headers, rows });
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      const orderedList = ordered !== null;
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(
          orderedList ? /^\d+\.\s+(.+)$/ : /^[-*+]\s+(.+)$/
        );
        if (!item) {
          break;
        }
        items.push(item[1]);
        index += 1;
      }
      blocks.push({ kind: "list", items, ordered: orderedList });
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ kind: "blockquote", lines: quoteLines });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length && !startsNewBlock(lines, index)) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") });
  }

  return blocks;
}

function startsNewBlock(lines: string[], index: number) {
  const trimmed = lines[index].trim();
  return (
    trimmed === "" ||
    /^```/.test(trimmed) ||
    /^(#{1,6})\s+/.test(trimmed) ||
    /^(-{3,}|\*{3,}|_{3,})$/.test(trimmed) ||
    /^[-*+]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed) ||
    trimmed.startsWith(">") ||
    isTableStart(lines, index)
  );
}

function isTableStart(lines: string[], index: number) {
  return (
    index + 1 < lines.length &&
    isTableRow(lines[index]) &&
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])
  );
}

function isTableRow(line: string) {
  return line.includes("|") && line.trim() !== "";
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderBlock(block: MarkdownBlock, index: number) {
  if (block.kind === "heading") {
    const Heading = `h${block.depth}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
    return <Heading key={index}>{renderInline(block.text, `h-${index}`)}</Heading>;
  }

  if (block.kind === "paragraph") {
    return <p key={index}>{renderInline(block.text, `p-${index}`)}</p>;
  }

  if (block.kind === "code") {
    return (
      <pre className="markdown-code-block" key={index}>
        {block.language ? <span className="markdown-code-language">{block.language}</span> : null}
        <code>{block.code}</code>
      </pre>
    );
  }

  if (block.kind === "list") {
    const List = block.ordered ? "ol" : "ul";
    return (
      <List key={index}>
        {block.items.map((item, itemIndex) => (
          <li key={`${index}-${itemIndex}`}>{renderInline(item, `li-${index}-${itemIndex}`)}</li>
        ))}
      </List>
    );
  }

  if (block.kind === "blockquote") {
    return (
      <blockquote key={index}>
        {block.lines.map((line, lineIndex) => (
          <p key={`${index}-${lineIndex}`}>{renderInline(line, `quote-${index}-${lineIndex}`)}</p>
        ))}
      </blockquote>
    );
  }

  if (block.kind === "table") {
    return (
      <div className="markdown-table-wrap" key={index}>
        <table>
          <thead>
            <tr>
              {block.headers.map((header, headerIndex) => (
                <th key={`${index}-header-${headerIndex}`}>
                  {renderInline(header, `th-${index}-${headerIndex}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${index}-row-${rowIndex}`}>
                {block.headers.map((_, cellIndex) => (
                  <td key={`${index}-cell-${rowIndex}-${cellIndex}`}>
                    {renderInline(row[cellIndex] ?? "", `td-${index}-${rowIndex}-${cellIndex}`)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <hr key={index} />;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const codePattern = /`([^`]+)`/g;
  let lastIndex = 0;
  let codeMatch: RegExpExecArray | null;

  while ((codeMatch = codePattern.exec(text)) !== null) {
    if (codeMatch.index > lastIndex) {
      nodes.push(...renderInlineWithoutCode(text.slice(lastIndex, codeMatch.index), `${keyPrefix}-t-${lastIndex}`));
    }
    nodes.push(<code key={`${keyPrefix}-code-${codeMatch.index}`}>{codeMatch[1]}</code>);
    lastIndex = codeMatch.index + codeMatch[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(...renderInlineWithoutCode(text.slice(lastIndex), `${keyPrefix}-t-${lastIndex}`));
  }

  return nodes;
}

function renderInlineWithoutCode(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    if (match[2] && match[3]) {
      nodes.push(
        <a href={match[3]} key={`${keyPrefix}-link-${match.index}`}>
          {match[2]}
        </a>
      );
    } else if (match[4]) {
      nodes.push(<strong key={`${keyPrefix}-strong-${match.index}`}>{match[4]}</strong>);
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}
