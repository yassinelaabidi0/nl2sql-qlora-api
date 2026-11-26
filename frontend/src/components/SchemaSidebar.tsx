import {
  ChevronDown,
  ChevronRight,
  Columns3,
  Lock,
  RefreshCw,
  Search,
  Table2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { TableSchema } from "../api/client";

interface SchemaSidebarProps {
  tables: TableSchema[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onInsertReference: (snippet: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function SchemaSidebar({
  tables,
  loading,
  error,
  onRefresh,
  onInsertReference,
  mobileOpen,
  onCloseMobile,
}: SchemaSidebarProps) {
  const [filter, setFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const filteredTables = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) {
      return tables;
    }
    return tables
      .map((table) => {
        const tableMatches = table.name.toLowerCase().includes(query);
        const matchingColumns = table.columns.filter(
          (col) =>
            col.name.toLowerCase().includes(query) || col.data_type.toLowerCase().includes(query),
        );
        if (tableMatches) {
          return table;
        }
        if (matchingColumns.length > 0) {
          return { ...table, columns: matchingColumns };
        }
        return null;
      })
      .filter((t): t is TableSchema => t !== null);
  }, [tables, filter]);

  const toggleTable = (name: string) => {
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const sidebarContent = (
    <div className="flex h-full flex-col bg-white dark:bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            Schema Explorer
          </h2>
          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-500">
            public · {tables.length} {tables.length === 1 ? "table" : "tables"}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh schema"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button
            type="button"
            onClick={onCloseMobile}
            aria-label="Close schema sidebar"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100 lg:hidden"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="border-b border-zinc-200 p-3 dark:border-zinc-800">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-400" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter tables or columns..."
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 py-1.5 pl-8 pr-7 text-xs text-zinc-900 placeholder:text-zinc-400 focus:border-emerald-500 focus:bg-white focus:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus:bg-zinc-900"
          />
          {filter && (
            <button
              type="button"
              onClick={() => setFilter("")}
              aria-label="Clear schema filter"
              className="absolute right-2 top-2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading && tables.length === 0 ? (
          <div className="space-y-3">
            {[1, 2, 3].map((item) => (
              <div
                key={item}
                className="animate-pulse rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
              >
                <div className="h-3.5 w-28 rounded bg-zinc-200 dark:bg-zinc-800" />
                <div className="mt-2.5 space-y-1.5">
                  <div className="h-2.5 w-full rounded bg-zinc-100 dark:bg-zinc-900" />
                  <div className="h-2.5 w-4/5 rounded bg-zinc-100 dark:bg-zinc-900" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="rounded-lg border border-rose-500/25 bg-rose-500/10 p-3 text-xs text-rose-700 dark:text-rose-300">
            <p className="font-medium">Failed to load schema</p>
            <p className="mt-1 opacity-90">{error}</p>
            <button
              type="button"
              onClick={onRefresh}
              className="mt-2 inline-flex items-center gap-1 rounded border border-rose-500/30 px-2 py-1 text-[11px] font-medium hover:bg-rose-500/10"
            >
              <RefreshCw className="h-3 w-3" />
              Retry
            </button>
          </div>
        ) : filteredTables.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-200 p-4 text-center text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            {tables.length === 0
              ? "No readable tables found in public schema."
              : "No tables or columns match your filter."}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredTables.map((table) => {
              const isCollapsed = collapsed[table.name] ?? false;
              return (
                <div
                  key={table.name}
                  className="overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50/60 dark:border-zinc-800/90 dark:bg-zinc-900/40"
                >
                  <div className="flex items-center justify-between px-2.5 py-2">
                    <button
                      type="button"
                      onClick={() => toggleTable(table.name)}
                      className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs font-semibold text-zinc-800 hover:text-emerald-600 dark:text-zinc-200 dark:hover:text-emerald-400"
                    >
                      {isCollapsed ? (
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                      )}
                      <Table2 className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                      <span className="truncate font-mono">{table.name}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onInsertReference(table.name)}
                      title={`Insert "${table.name}" into question`}
                      className="ml-2 shrink-0 rounded bg-zinc-200/70 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 transition hover:bg-emerald-500/15 hover:text-emerald-700 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:text-emerald-300"
                    >
                      {table.columns.length} cols
                    </button>
                  </div>

                  {!isCollapsed && (
                    <ul className="border-t border-zinc-200/80 bg-white py-1 dark:border-zinc-800/80 dark:bg-zinc-950/60">
                      {table.columns.map((col) => (
                        <li key={col.name}>
                          <button
                            type="button"
                            onClick={() => onInsertReference(`${table.name}.${col.name}`)}
                            title={`Click to insert ${table.name}.${col.name}`}
                            className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs transition hover:bg-zinc-100 dark:hover:bg-zinc-900"
                          >
                            <span className="flex min-w-0 items-center gap-1.5 text-zinc-700 dark:text-zinc-300">
                              <Columns3 className="h-3 w-3 shrink-0 text-zinc-400" />
                              <span className="truncate font-mono">{col.name}</span>
                            </span>
                            <span className="flex shrink-0 items-center gap-1.5">
                              <span className="font-mono text-[10px] text-zinc-500 dark:text-zinc-400">
                                {col.data_type}
                              </span>
                              {col.is_nullable && (
                                <span
                                  title="Nullable column"
                                  className="rounded border border-zinc-200 px-1 text-[9px] uppercase text-zinc-400 dark:border-zinc-800 dark:text-zinc-500"
                                >
                                  null
                                </span>
                              )}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="border-t border-zinc-200 px-4 py-2.5 text-[11px] text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        <div className="flex items-center gap-1.5">
          <Lock className="h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400" />
          <span>Role: nl2sql_ro · 3000ms timeout</span>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <aside className="hidden w-72 shrink-0 border-r border-zinc-200 dark:border-zinc-800 lg:block">
        {sidebarContent}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <aside className="relative z-10 h-full w-72 max-w-[85vw] border-r border-zinc-200 shadow-2xl dark:border-zinc-800">
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
