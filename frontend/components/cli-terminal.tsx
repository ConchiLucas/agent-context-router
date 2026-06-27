"use client";

import { useState } from "react";

type CliTerminalProps = {
  command: string;
};

export function CliTerminal({ command }: CliTerminalProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text: ", err);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
      <div className="terminal-header">
        <div className="terminal-dot red" />
        <div className="terminal-dot yellow" />
        <div className="terminal-dot green" />
        <span className="terminal-title">terminal</span>
      </div>
      <div style={{ position: "relative" }}>
        <pre className="code-block" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0 }}>
          <code>{command}</code>
        </pre>
        <button
          className="button"
          onClick={handleCopy}
          style={{
            position: "absolute",
            top: "0.75rem",
            right: "0.75rem",
            padding: "0.3rem 0.6rem",
            fontSize: "0.75rem",
            borderRadius: "var(--radius-sm)",
            background: "rgba(255, 255, 255, 0.05)",
            borderColor: "rgba(255, 255, 255, 0.1)",
          }}
          type="button"
        >
          {copied ? (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--useful-color)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span style={{ color: "var(--useful-color)" }}>Copied!</span>
            </>
          ) : (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
