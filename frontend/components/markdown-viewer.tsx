import type { ReactNode } from "react";

import { parseMarkdown } from "@/lib/markdown";

interface MarkdownViewerProps {
  content: string;
}

const INLINE_PATTERN = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;

function inlineContent(text: string): ReactNode[] {
  return text.split(INLINE_PATTERN).map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }

    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link;
      if (/^https?:\/\//.test(href)) {
        return (
          <a key={index} href={href} target="_blank" rel="noreferrer">
            {label}
          </a>
        );
      }
      return (
        <span key={index} className="markdown-relative-link" title={href}>
          {label}
        </span>
      );
    }
    return part;
  });
}

export function MarkdownViewer({ content }: MarkdownViewerProps) {
  const blocks = parseMarkdown(content);

  if (blocks.length === 0) {
    return <p className="empty-message">这个文档没有可展示的内容。</p>;
  }

  return (
    <article className="markdown-body">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          const children = inlineContent(block.text);
          if (block.level === 1) return <h1 key={index}>{children}</h1>;
          if (block.level === 2) return <h2 key={index}>{children}</h2>;
          if (block.level === 3) return <h3 key={index}>{children}</h3>;
          return <h4 key={index}>{children}</h4>;
        }
        if (block.type === "paragraph") {
          return <p key={index}>{inlineContent(block.text)}</p>;
        }
        if (block.type === "code") {
          return (
            <pre key={index} data-language={block.language || undefined}>
              <code>{block.content}</code>
            </pre>
          );
        }
        if (block.type === "table") {
          return (
            <div className="markdown-table-wrap" key={index}>
              <table>
                <thead>
                  <tr>
                    {block.headers.map((header, cellIndex) => (
                      <th key={cellIndex}>{inlineContent(header)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>{inlineContent(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === "unordered-list") {
          return (
            <ul key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{inlineContent(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "ordered-list") {
          return (
            <ol key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{inlineContent(item)}</li>
              ))}
            </ol>
          );
        }
        if (block.type === "blockquote") {
          return <blockquote key={index}>{inlineContent(block.text)}</blockquote>;
        }
        return <hr key={index} />;
      })}
    </article>
  );
}

