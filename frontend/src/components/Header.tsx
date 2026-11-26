import { Activity, Clock, Database, Menu, Moon, RefreshCw, ShieldCheck, Sun } from "lucide-react";
import type { HealthResponse } from "../api/client";

interface HeaderProps {
  health: HealthResponse | null;
  healthLoading: boolean;
  onRefreshHealth: () => void;
  onOpenHistory: () => void;
  historyCount: number;
  onToggleSidebar: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export function Header({
  health,
  healthLoading,
  onRefreshHealth,
  onOpenHistory,
  historyCount,
  onToggleSidebar,
  theme,
  onToggleTheme,
}: HeaderProps) {
  const isHealthy = Boolean(health && health.status === "ok" && health.db_connected);
  const modeLabel = health?.inference_mode ? health.inference_mode.toUpperCase() : "OFFLINE";

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-zinc-200 bg-white/85 px-4 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/85 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onToggleSidebar}
          aria-label="Toggle schema sidebar"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 text-zinc-600 transition hover:bg-zinc-100 hover:text-zinc-900 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100 lg:hidden"
        >
          <Menu className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-600 text-white shadow-sm shadow-emerald-600/20">
            <Database className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                NL2SQL Workbench
              </h1>
              <span className="hidden items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300 sm:inline-flex">
                <ShieldCheck className="h-3 w-3" />
                AST Guarded
              </span>
            </div>
            <p className="hidden text-[11px] text-zinc-500 dark:text-zinc-400 sm:block">
              Qwen2.5-3B QLoRA · Read-Only PostgreSQL
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onRefreshHealth}
          title="Refresh backend health"
          className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
            isHealthy
              ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-300"
              : "border-amber-500/30 bg-amber-500/10 text-amber-700 hover:bg-amber-500/15 dark:text-amber-300"
          }`}
        >
          <span
            className={`h-2 w-2 rounded-full ${
              healthLoading
                ? "animate-pulse bg-amber-500"
                : isHealthy
                  ? "bg-emerald-500"
                  : "bg-rose-500"
            }`}
          />
          <span className="hidden sm:inline">
            {healthLoading ? "Checking" : isHealthy ? "Connected" : "Degraded"}
          </span>
          <span className="rounded bg-black/5 px-1.5 py-0.5 font-mono text-[10px] tracking-wide dark:bg-white/10">
            {modeLabel}
          </span>
          {healthLoading ? (
            <RefreshCw className="h-3 w-3 animate-spin" />
          ) : (
            <Activity className="hidden h-3 w-3 opacity-70 sm:inline" />
          )}
        </button>

        <button
          type="button"
          onClick={onOpenHistory}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          <Clock className="h-3.5 w-3.5 text-zinc-500 dark:text-zinc-400" />
          <span>History</span>
          {historyCount > 0 && (
            <span className="rounded-full bg-zinc-100 px-1.5 py-0.2 font-mono text-[10px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
              {historyCount}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-600 transition hover:bg-zinc-100 hover:text-zinc-900 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}
