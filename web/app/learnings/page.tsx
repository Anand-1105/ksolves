"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Minimal markdown renderer — no external deps, handles headers/bold/lists/code
// ---------------------------------------------------------------------------

function renderMarkdown(md: string): React.ReactNode[] {
  const lines = md.split("\n");
  const nodes: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // H1
    if (line.startsWith("# ")) {
      nodes.push(
        <h1 key={i} className="text-xl font-semibold text-text-primary mt-6 mb-3 first:mt-0">
          {line.slice(2)}
        </h1>
      );
      i++;
      continue;
    }

    // H2
    if (line.startsWith("## ")) {
      nodes.push(
        <h2 key={i} className="text-sm font-semibold text-text-primary mt-6 mb-2 border-b border-border pb-1">
          {line.slice(3)}
        </h2>
      );
      i++;
      continue;
    }

    // H3
    if (line.startsWith("### ")) {
      nodes.push(
        <h3 key={i} className="text-xs font-semibold text-text-secondary mt-4 mb-1.5 uppercase tracking-wider">
          {line.slice(4)}
        </h3>
      );
      i++;
      continue;
    }

    // Horizontal rule
    if (line.trim() === "---") {
      nodes.push(<hr key={i} className="border-border my-4" />);
      i++;
      continue;
    }

    // Table — collect all table lines
    if (line.startsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      nodes.push(<MarkdownTable key={`table-${i}`} lines={tableLines} />);
      continue;
    }

    // Bullet list item
    if (line.startsWith("- ") || line.startsWith("* ")) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("* "))) {
        items.push(lines[i].slice(2));
        i++;
      }
      nodes.push(
        <ul key={`ul-${i}`} className="space-y-1 my-2 ml-4">
          {items.map((item, j) => (
            <li key={j} className="text-xs text-text-secondary flex gap-2">
              <span className="text-accent mt-0.5 shrink-0">•</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Numbered list
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s/, ""));
        i++;
      }
      nodes.push(
        <ol key={`ol-${i}`} className="space-y-1 my-2 ml-4 list-decimal list-inside">
          {items.map((item, j) => (
            <li key={j} className="text-xs text-text-secondary">
              {renderInline(item)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Code block
    if (line.startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      nodes.push(
        <pre key={`code-${i}`} className="bg-bg-elevated border border-border rounded-container p-3 my-3 overflow-auto text-[11px] text-text-secondary font-mono">
          {codeLines.join("\n")}
        </pre>
      );
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      nodes.push(<div key={i} className="h-2" />);
      i++;
      continue;
    }

    // Italic line (starts with *)
    if (line.startsWith("*") && line.endsWith("*") && !line.startsWith("**")) {
      nodes.push(
        <p key={i} className="text-xs text-text-dim italic my-1">
          {line.slice(1, -1)}
        </p>
      );
      i++;
      continue;
    }

    // Regular paragraph
    nodes.push(
      <p key={i} className="text-xs text-text-secondary leading-relaxed my-1">
        {renderInline(line)}
      </p>
    );
    i++;
  }

  return nodes;
}

function renderInline(text: string): React.ReactNode {
  // Bold: **text**
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="text-text-primary font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={i} className="font-mono text-accent bg-bg-elevated px-1 py-0.5 rounded text-[11px]">{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

function MarkdownTable({ lines }: { lines: string[] }) {
  const rows = lines
    .filter((l) => !l.replace(/[\s|:-]/g, "").length === false)
    .filter((l) => !/^\|[-:\s|]+\|$/.test(l.trim()));

  if (rows.length === 0) return null;

  const parseRow = (line: string) =>
    line
      .split("|")
      .slice(1, -1)
      .map((cell) => cell.trim());

  const [header, ...body] = rows;
  const headers = parseRow(header);

  return (
    <div className="my-3 overflow-auto">
      <table className="w-full border border-border rounded-container overflow-hidden text-xs">
        <thead className="bg-bg-surface border-b border-border">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="px-3 py-2 text-left text-[11px] font-medium text-text-muted uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? "bg-bg-base" : "bg-bg-surface"}>
              {parseRow(row).map((cell, ci) => (
                <td key={ci} className="px-3 py-2 text-text-secondary">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function LearningsPage() {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [exists, setExists] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .learnings()
      .then((data) => {
        setContent(data.content);
        setExists(data.exists);
      })
      .finally(() => setLoading(false));
  }, []);

  function handleRefresh() {
    setLoading(true);
    setError(null);
    api
      .learnings()
      .then((data) => {
        setContent(data.content);
        setExists(data.exists);
      })
      .finally(() => setLoading(false));
  }

  function handleGenerate() {
    setGenerating(true);
    setError(null);
    api
      .generateLearnings()
      .then((data) => {
        setContent(data.content);
        setExists(data.exists ?? true);
      })
      .catch((err) => {
        setError(err.message ?? "Failed to generate learnings");
      })
      .finally(() => setGenerating(false));
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">Agent Learnings</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Self-improvement analysis generated after each run
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRefresh}
            disabled={loading || generating}
            className="text-xs text-text-muted hover:text-text-secondary border border-border rounded-input px-3 py-1.5 transition-colors disabled:opacity-50"
          >
            Refresh
          </button>
          <button
            onClick={handleGenerate}
            disabled={loading || generating}
            className="text-xs font-medium bg-accent hover:bg-accent-hover text-white px-3 py-1.5 rounded-input transition-colors disabled:opacity-50"
          >
            {generating ? "Generating…" : "Generate Report"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 border border-resolution-deny-border bg-resolution-deny-bg rounded-container text-xs text-resolution-deny">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24 text-text-muted text-sm">
          <span className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse"
                style={{ animationDelay: `${i * 150}ms` }}
              />
            ))}
          </span>
        </div>
      ) : !exists || !content ? (
        <div className="flex flex-col items-center justify-center py-24 border border-border rounded-container text-center">
          <div className="w-10 h-10 rounded-container border border-border flex items-center justify-center mb-4 text-text-dim text-lg">
            🧠
          </div>
          <p className="text-sm text-text-muted">No learnings report yet</p>
          <p className="text-xs text-text-dim mt-1 max-w-xs">
            Run all 20 tickets first, then generate the self-improvement analysis
          </p>
          <div className="flex gap-2 mt-4">
            <a
              href="/run"
              className="text-xs font-medium border border-border text-text-secondary px-4 py-2 rounded-input transition-colors hover:bg-bg-elevated"
            >
              Run All Tickets
            </a>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="text-xs font-medium bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-input transition-colors disabled:opacity-50"
            >
              {generating ? "Generating…" : "Generate Report →"}
            </button>
          </div>
        </div>
      ) : (
        <div className="border border-border rounded-container p-6 bg-bg-surface">
          {renderMarkdown(content)}
        </div>
      )}
    </div>
  );
}
