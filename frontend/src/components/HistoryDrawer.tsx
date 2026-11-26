import { CheckCircle2, Clock, RefreshCw, RotateCcw, ShieldAlert, X, XCircle } from "lucide-react";
import { useEffect } from "react";
import type { HistoryEntry } from "../api/client";

interface HistoryDrawerProps {
  open: boolean;
  onClose: () => void;
  items: HistoryEntry[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onReplay: (question: string) => void;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function HistoryDrawer({
  open,
  onClose,
  items,
  loading,
  error,
  onRefresh,
  onReplay,
}: HistoryDrawerProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleEscape = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-xs"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-label="Query history"
        className="relative z-10 flex h-full w-full max-w-md flex-col border-l border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-zinc-950"
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            <div>
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Audit & Query History
              </h2>
              <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
                Latest {items.length} entries from PostgreSQL query_logs
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              title="Refresh history"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 text-zinc-600 transition hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close history drawer"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 text-zinc-600 transition hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {loading && items.length === 0 ? (
            <div className="space-y-3">
              {[1, 2, 3, 4].map((item) => (
                <div
                  key={item}
                  className="animate-pulse rounded-xl border border-zinc-200 p-3.5 dark:border-zinc-800"
                >
                  <div className="h-3 w-24 rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="mt-2 h-4 w-4/5 rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="mt-2 h-10 w-full rounded bg-zinc-100 dark:bg-zinc-900" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 p-4 text-xs text-rose-700 dark:text-rose-300">
              <p className="font-medium">Could not load history</p>
              <p className="mt-1 opacity-90">{error}</p>
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-200 p-8 text-center text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              No queries logged yet. Run a question in the workbench to create your first audit entry.
            </div>
          ) : (
            <div className="space-y-3">
              {items.map((entry) => {
                const statusLower = entry.status.toLowerCase();
                const isSuccess = statusLower === "success" || statusLower === "ok";
                const isBlocked = statusLower.includes("block") || statusLower.includes("guard");

                return (
                  <article
                    key={entry.id}
                    className="rounded-xl border border-zinc-200 bg-zinc-50/70 p-3.5 transition hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900/50 dark:hover:border-zinc-700"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                            isSuccess
                              ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                              : isBlocked
                                ? "bg-rose-500/15 text-rose-700 dark:text-rose-300"
                                : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                          }`}
                        >
                          {isSuccess ? (
                            <CheckCircle2 className="h-3 w-3" />
                          ) : isBlocked ? (
                            <ShieldAlert className="h-3 w-3" />
                          ) : (
                            <XCircle className="h-3 w-3" />
                          )}
                          {entry.status}
                        </span>
                        <span className="font-mono text-[10px] text-zinc-500 dark:text-zinc-400">
                          {entry.latency_ms.toFixed(1)} ms
                        </span>
                      </div>

                      <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                        {formatTimestamp(entry.created_at)}
                      </span>
                    </div>

                    <p className="mt-2 text-xs font-medium text-zinc-900 dark:text-zinc-100">
                      {entry.question}
                    </p>

                    {entry.generated_sql && (
                      <pre className="mt-2 overflow-x-auto rounded-lg border border-zinc-200/80 bg-white p-2 font-mono text-[11px] text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
                        <code>{entry.generated_sql}</code>
                      </pre>
                    )}

                    {entry.error_message && (
                      <p className="mt-2 rounded-md bg-rose-500/10 px-2.5 py-1.5 text-[11px] text-rose-700 dark:text-rose-300">
                        {entry.error_message}
                      </p>
                    )}

                    <div className="mt-2.5 flex justify-end">
                      <button
                        type="button"
                        onClick={() => onReplay(entry.question)}
                        className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-[11px] font-medium text-zinc-700 transition hover:border-emerald-500/50 hover:text-emerald-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:text-emerald-300"
                      >
                        <RotateCcw className="h-3 w-3" />
                        Replay
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
