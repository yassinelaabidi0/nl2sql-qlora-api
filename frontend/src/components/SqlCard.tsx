import { Check, Code2, Copy, ShieldCheck, Timer } from "lucide-react";
import { useState, type ReactNode } from "react";

interface SqlCardProps {
  sql: string;
  latencyMs: number;
  rowCount: number;
}

const SQL_KEYWORDS = new Set([
  "SELECT",
  "FROM",
  "WHERE",
  "JOIN",
  "INNER",
  "LEFT",
  "RIGHT",
  "FULL",
  "OUTER",
  "CROSS",
  "ON",
  "GROUP",
  "BY",
  "ORDER",
  "HAVING",
  "LIMIT",
  "OFFSET",
  "AS",
  "AND",
  "OR",
  "NOT",
  "IN",
  "IS",
  "NULL",
  "TRUE",
  "FALSE",
  "DISTINCT",
  "ASC",
  "DESC",
  "CASE",
  "WHEN",
  "THEN",
  "ELSE",
  "END",
  "WITH",
  "UNION",
  "ALL",
  "OVER",
  "PARTITION",
  "BETWEEN",
  "LIKE",
  "ILIKE",
  "EXISTS",
  "CAST",
  "COUNT",
  "SUM",
  "AVG",
  "MIN",
  "MAX",
  "COALESCE",
  "ROUND",
]);

const TOKEN_PATTERN = /('(?:''|[^'])*'|"(?:""|[^"])*"|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b|[(),.*;=<>!+\-/]+|\s+|.)/g;

function highlightSql(sql: string): ReactNode[] {
  const tokens = sql.match(TOKEN_PATTERN) ?? [sql];
  return tokens.map((token, idx) => {
    if (/^\s+$/.test(token)) {
      return <span key={idx}>{token}</span>;
    }
    if (token.startsWith("'")) {
      return (
        <span key={idx} className="text-amber-700 dark:text-amber-300">
          {token}
        </span>
      );
    }
    if (token.startsWith('"')) {
      return (
        <span key={idx} className="text-cyan-700 dark:text-cyan-300">
          {token}
        </span>
      );
    }
    if (/^\d+(?:\.\d+)?$/.test(token)) {
      return (
        <span key={idx} className="text-violet-700 dark:text-violet-300">
          {token}
        </span>
      );
    }
    if (SQL_KEYWORDS.has(token.toUpperCase())) {
      return (
        <span key={idx} className="font-semibold text-emerald-700 dark:text-emerald-400">
          {token}
        </span>
      );
    }
    if (/^[(),.*;=<>!+\-/]+$/.test(token)) {
      return (
        <span key={idx} className="text-zinc-500 dark:text-zinc-400">
          {token}
        </span>
      );
    }
    return (
      <span key={idx} className="text-zinc-800 dark:text-zinc-100">
        {token}
      </span>
    );
  });
}

export function SqlCard({ sql, latencyMs, rowCount }: SqlCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-zinc-50/80 px-4 py-2.5 dark:border-zinc-800 dark:bg-zinc-900/90">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-zinc-800 dark:text-zinc-200">
            <Code2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
            Generated SQL
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
            <ShieldCheck className="h-3 w-3" />
            SELECT Verified
          </span>
        </div>

        <div className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
          <span className="rounded-md bg-zinc-200/70 px-2 py-0.5 font-mono text-[11px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
            {rowCount} {rowCount === 1 ? "row" : "rows"}
          </span>
          <span className="inline-flex items-center gap-1 rounded-md bg-zinc-200/70 px-2 py-0.5 font-mono text-[11px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
            <Timer className="h-3 w-3" />
            {latencyMs.toFixed(1)} ms
          </span>
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-[11px] font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-500" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                Copy
              </>
            )}
          </button>
        </div>
      </div>

      <pre className="overflow-x-auto bg-zinc-50/50 p-4 font-mono text-[13px] leading-relaxed dark:bg-zinc-950/70">
        <code>{highlightSql(sql)}</code>
      </pre>
    </section>
  );
}
