import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  CornerDownLeft,
  ShieldAlert,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import { useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ApiError, QueryResponse, TableSchema } from "../api/client";
import { ResultTable } from "./ResultTable";
import { SqlCard } from "./SqlCard";

interface ChatWorkspaceProps {
  tables: TableSchema[];
  question: string;
  onQuestionChange: (value: string) => void;
  schemaDdl: string;
  onSchemaDdlChange: (value: string) => void;
  onSubmit: (overrideQuestion?: string) => void;
  isLoading: boolean;
  result: QueryResponse | null;
  error: ApiError | null;
  lastQuestion: string | null;
  onClearError: () => void;
}

interface ExamplePrompt {
  title: string;
  question: string;
  tag: string;
  isSecurityTest?: boolean;
}

const FALLBACK_PROMPTS: ExamplePrompt[] = [
  {
    title: "Headcount by department",
    question: "How many employees work in each department?",
    tag: "Aggregation",
  },
  {
    title: "Revenue across regions",
    question: "What is the total sales amount by region?",
    tag: "Sales Analytics",
  },
  {
    title: "Top compensated staff",
    question: "List the top 5 highest-paid employees with their department.",
    tag: "Ranking & Join",
  },
  {
    title: "Drop the departments table",
    question: "Drop the departments table",
    tag: "Guardrail Test",
    isSecurityTest: true,
  },
];

function getColumnType(col: TableSchema["columns"][number]): string {
  const record = col as unknown as Record<string, unknown>;
  return String(record.data_type ?? record.type ?? "").toLowerCase();
}

function buildPromptsForSchema(tables: TableSchema[]): ExamplePrompt[] {
  const userTables = tables.filter((t) => t.name !== "query_logs");
  if (userTables.length === 0) {
    return FALLBACK_PROMPTS;
  }

  const isNumeric = (col: TableSchema["columns"][number]) => {
    const dtype = getColumnType(col);
    return (
      col.name !== "id" &&
      !col.name.endsWith("_id") &&
      (dtype.includes("num") ||
        dtype.includes("int") ||
        dtype.includes("dec") ||
        dtype.includes("float") ||
        dtype.includes("double"))
    );
  };

  const isDimension = (col: TableSchema["columns"][number]) => {
    const dtype = getColumnType(col);
    return col.name !== "id" && (dtype.includes("text") || dtype.includes("char") || dtype.includes("date"));
  };

  // 1. Aggregation card
  const aggTable =
    userTables.find((t) => t.columns.some(isNumeric) && t.columns.some(isDimension)) ?? userTables[0];
  const metric = aggTable.columns.find(isNumeric);
  const dim = aggTable.columns.find(isDimension);
  const aggQuestion =
    metric && dim
      ? `What is the total ${metric.name.replace(/_/g, " ")} by ${dim.name.replace(/_/g, " ")} in ${aggTable.name}?`
      : `How many rows are in ${aggTable.name}?`;

  // 2. Relational join card (detects *_id foreign keys across tables)
  const tableNames = new Set(userTables.map((t) => t.name));
  let joinQuestion = `List all records from ${userTables[Math.min(1, userTables.length - 1)].name}`;
  for (const tbl of userTables) {
    const fkCol = tbl.columns.find((c) => c.name.endsWith("_id"));
    if (fkCol) {
      const stem = fkCol.name.slice(0, -3);
      const target =
        userTables.find((t) => t.name === `${stem}s` || t.name === `${stem}es` || t.name === stem) ??
        (stem.endsWith("y") && tableNames.has(`${stem.slice(0, -1)}ies`)
          ? userTables.find((t) => t.name === `${stem.slice(0, -1)}ies`)
          : undefined);
      if (target && target.name !== tbl.name) {
        joinQuestion = `Show ${tbl.name} with their ${target.name} details`;
        break;
      }
    }
  }

  // 3. Ranking card
  const rankTable = userTables.find((t) => t.columns.some(isNumeric)) ?? userTables[0];
  const rankCol = rankTable.columns.find(isNumeric) ?? rankTable.columns[0];
  const rankQuestion = `List the top 5 ${rankTable.name} ordered by ${rankCol.name.replace(/_/g, " ")}`;

  // 4. Guardrail test card
  const guardTable = userTables[0].name;

  return [
    { title: "Aggregation", question: aggQuestion, tag: "Aggregation" },
    { title: "Relational Join", question: joinQuestion, tag: "Relational Join" },
    { title: "Ranking", question: rankQuestion, tag: "Ranking" },
    {
      title: `Drop ${guardTable}`,
      question: `Drop the ${guardTable} table`,
      tag: "Guardrail Test",
      isSecurityTest: true,
    },
  ];
}

export function ChatWorkspace({
  tables,
  question,
  onQuestionChange,
  schemaDdl,
  onSchemaDdlChange,
  onSubmit,
  isLoading,
  result,
  error,
  lastQuestion,
  onClearError,
}: ChatWorkspaceProps) {
  const [showCustomDdl, setShowCustomDdl] = useState(false);
  const examplePrompts = useMemo(() => buildPromptsForSchema(tables), [tables]);

  const handleFormSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim() || isLoading) {
      return;
    }
    onSubmit();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (question.trim() && !isLoading) {
        onSubmit();
      }
    }
  };

  const handleExampleClick = (promptText: string) => {
    onQuestionChange(promptText);
    onSubmit(promptText);
  };

  const isSecurityRejection =
    error !== null &&
    (error.status === 400 ||
      error.status === 403 ||
      error.errorCode === "sql_guard_rejected");

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-6 lg:p-8">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Ask PostgreSQL in Natural Language
            </h2>
            <button
              type="button"
              onClick={() => setShowCustomDdl((prev) => !prev)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-200"
            >
              <Terminal className="h-3.5 w-3.5" />
              Custom DDL
              {showCustomDdl ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </button>
          </div>

          <form
            onSubmit={handleFormSubmit}
            className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs transition focus-within:border-emerald-500 focus-within:ring-2 focus-within:ring-emerald-500/15 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <textarea
              rows={3}
              value={question}
              onChange={(e) => onQuestionChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your PostgreSQL tables... (Enter to run, Shift+Enter for newline)"
              className="w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-100 dark:placeholder:text-zinc-500"
            />

            {showCustomDdl && (
              <div className="border-t border-zinc-200 bg-zinc-50/70 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950/60">
                <div className="mb-1.5 flex items-center justify-between">
                  <label
                    htmlFor="custom-schema-ddl"
                    className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400"
                  >
                    Optional Schema DDL Override (leave blank to introspect live PostgreSQL)
                  </label>
                  {schemaDdl && (
                    <button
                      type="button"
                      onClick={() => onSchemaDdlChange("")}
                      className="text-[11px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                    >
                      Reset
                    </button>
                  )}
                </div>
                <textarea
                  id="custom-schema-ddl"
                  rows={3}
                  value={schemaDdl}
                  onChange={(e) => onSchemaDdlChange(e.target.value)}
                  placeholder="CREATE TABLE departments (id INT PRIMARY KEY, name TEXT, budget NUMERIC);"
                  className="w-full rounded-lg border border-zinc-200 bg-white p-2.5 font-mono text-xs text-zinc-800 placeholder:text-zinc-400 focus:border-emerald-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
                />
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-100 bg-zinc-50/50 px-4 py-2.5 dark:border-zinc-800/80 dark:bg-zinc-900/60">
              <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
                Validated by <span className="font-mono">sqlglot</span> AST guard · Read-only execution
              </p>
              <button
                type="submit"
                disabled={isLoading || !question.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" />
                <span>{isLoading ? "Running..." : "Run Query"}</span>
                {!isLoading && <CornerDownLeft className="h-3 w-3 opacity-80" />}
              </button>
            </div>
          </form>
        </section>

        <section className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {examplePrompts.map((item) => (
            <button
              key={item.title}
              type="button"
              disabled={isLoading}
              onClick={() => handleExampleClick(item.question)}
              className={`group flex flex-col justify-between rounded-xl border p-3 text-left transition disabled:opacity-50 ${item.isSecurityTest
                ? "border-rose-500/25 bg-rose-500/5 hover:border-rose-500/50 hover:bg-rose-500/10"
                : "border-zinc-200 bg-white hover:border-emerald-500/50 hover:bg-emerald-500/5 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-emerald-500/40"
                }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${item.isSecurityTest
                    ? "bg-rose-500/15 text-rose-700 dark:text-rose-300"
                    : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
                    }`}
                >
                  {item.isSecurityTest && <ShieldAlert className="h-3 w-3" />}
                  {item.tag}
                </span>
              </div>
              <p className="mt-2 text-xs font-medium text-zinc-800 group-hover:text-zinc-950 dark:text-zinc-200 dark:group-hover:text-white">
                {item.question}
              </p>
            </button>
          ))}
        </section>

        {isLoading && (
          <section className="space-y-4">
            <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="flex items-center gap-2 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                <span className="h-2 w-2 animate-ping rounded-full bg-emerald-500" />
                Generating SQL and validating read-only AST...
              </div>
              <div className="mt-4 animate-pulse space-y-2">
                <div className="h-3 w-3/4 rounded bg-zinc-200 dark:bg-zinc-800" />
                <div className="h-3 w-1/2 rounded bg-zinc-200 dark:bg-zinc-800" />
              </div>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="animate-pulse space-y-2.5">
                <div className="h-4 w-36 rounded bg-zinc-200 dark:bg-zinc-800" />
                {[1, 2, 3, 4].map((row) => (
                  <div key={row} className="h-7 w-full rounded bg-zinc-100 dark:bg-zinc-800/60" />
                ))}
              </div>
            </div>
          </section>
        )}

        {!isLoading && error && (
          <section
            role="alert"
            className={`rounded-xl border p-4 shadow-xs ${isSecurityRejection
              ? "border-rose-500/35 bg-rose-500/10 text-rose-900 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-100"
              : "border-amber-500/35 bg-amber-500/10 text-amber-950 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-100"
              }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div
                  className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${isSecurityRejection
                    ? "bg-rose-500/20 text-rose-600 dark:text-rose-300"
                    : "bg-amber-500/20 text-amber-600 dark:text-amber-300"
                    }`}
                >
                  {isSecurityRejection ? (
                    <ShieldAlert className="h-4 w-4" />
                  ) : (
                    <AlertTriangle className="h-4 w-4" />
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold">
                      {isSecurityRejection ? "Blocked by SQL Security Guard" : "Query Execution Error"}
                    </h3>
                    <span className="rounded bg-black/10 px-1.5 py-0.5 font-mono text-[11px] dark:bg-white/10">
                      {error.status > 0 ? `HTTP ${error.status}` : "NETWORK"} · {error.errorCode}
                    </span>
                  </div>
                  {lastQuestion && (
                    <p className="text-xs opacity-80">Prompt: "{lastQuestion}"</p>
                  )}
                  <p className="text-xs leading-relaxed font-medium">{error.reason}</p>
                  {error.generatedSql && (
                    <details
                      open
                      className="mt-2 overflow-hidden rounded-lg border border-black/10 bg-black/5 dark:border-white/10 dark:bg-black/25"
                    >
                      <summary className="cursor-pointer select-none px-2.5 py-1.5 font-mono text-[11px] font-medium opacity-85 hover:opacity-100">
                        Failed SQL attempted
                      </summary>
                      <pre className="max-h-44 overflow-auto border-t border-black/10 p-2.5 font-mono text-xs dark:border-white/10">
                        <code>{error.generatedSql}</code>
                      </pre>
                    </details>
                  )}
                </div>
              </div>

              <button
                type="button"
                onClick={onClearError}
                aria-label="Dismiss error"
                className="rounded-md p-1 opacity-70 transition hover:bg-black/10 hover:opacity-100 dark:hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </section>
        )}

        {!isLoading && !error && result && (
          <section className="space-y-4">
            <div className="flex items-center justify-between gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-2.5 text-xs dark:border-zinc-800 dark:bg-zinc-900">
              <div className="min-w-0">
                <span className="font-medium text-zinc-500 dark:text-zinc-400">Question: </span>
                <span className="font-medium text-zinc-900 dark:text-zinc-100">
                  {result.question}
                </span>
              </div>
            </div>

            <SqlCard
              sql={result.sql}
              latencyMs={result.latency_ms}
              rowCount={result.row_count}
              wasRepaired={result.was_repaired}
              repairAttempts={result.repair_attempts}
            />
            <ResultTable columns={result.columns} rows={result.rows} />
          </section>
        )}
      </div>
    </main>
  );
}