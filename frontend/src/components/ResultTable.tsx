import { ArrowDown, ArrowUp, ArrowUpDown, Download, FileJson, Search, X } from "lucide-react";
import { useMemo, useState } from "react";

interface ResultTableProps {
  columns: string[];
  rows: unknown[][];
}

type SortDirection = "asc" | "desc" | null;

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "NULL";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function compareValues(a: unknown, b: unknown, dir: "asc" | "desc"): number {
  const factor = dir === "asc" ? 1 : -1;
  if (a === null || a === undefined) {
    return b === null || b === undefined ? 0 : 1;
  }
  if (b === null || b === undefined) {
    return -1;
  }
  const numA = typeof a === "number" ? a : Number(a);
  const numB = typeof b === "number" ? b : Number(b);
  if (
    a !== "" &&
    b !== "" &&
    typeof a !== "boolean" &&
    typeof b !== "boolean" &&
    !Number.isNaN(numA) &&
    !Number.isNaN(numB)
  ) {
    return (numA - numB) * factor;
  }
  return formatCell(a).localeCompare(formatCell(b), undefined, { numeric: true }) * factor;
}

function escapeCsvField(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  const str = typeof value === "object" ? JSON.stringify(value) : String(value);
  if (/[",\r\n]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function ResultTable({ columns, rows }: ResultTableProps) {
  const [filterText, setFilterText] = useState("");
  const [sortColIndex, setSortColIndex] = useState<number | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>(null);

  const filteredAndSortedRows = useMemo(() => {
    const query = filterText.trim().toLowerCase();
    const filtered = query
      ? rows.filter((row) =>
          row.some((cell) => formatCell(cell).toLowerCase().includes(query)),
        )
      : rows;

    if (sortColIndex === null || sortDirection === null) {
      return filtered;
    }

    return [...filtered].sort((a, b) =>
      compareValues(a[sortColIndex], b[sortColIndex], sortDirection),
    );
  }, [rows, filterText, sortColIndex, sortDirection]);

  const handleSort = (colIndex: number) => {
    if (sortColIndex !== colIndex) {
      setSortColIndex(colIndex);
      setSortDirection("asc");
      return;
    }
    if (sortDirection === "asc") {
      setSortDirection("desc");
      return;
    }
    setSortColIndex(null);
    setSortDirection(null);
  };

  const exportCsv = () => {
    const headerLine = columns.map(escapeCsvField).join(",");
    const dataLines = filteredAndSortedRows.map((row) => row.map(escapeCsvField).join(","));
    downloadBlob([headerLine, ...dataLines].join("\n"), "query-results.csv", "text/csv;charset=utf-8");
  };

  const exportJson = () => {
    const records = filteredAndSortedRows.map((row) => {
      const obj: Record<string, unknown> = {};
      columns.forEach((col, idx) => {
        obj[col] = row[idx] ?? null;
      });
      return obj;
    });
    downloadBlob(
      JSON.stringify(records, null, 2),
      "query-results.json",
      "application/json;charset=utf-8",
    );
  };

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <h3 className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">
            Query Results
          </h3>
          <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
            Showing {filteredAndSortedRows.length} of {rows.length}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-zinc-400" />
            <input
              type="text"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="Filter rows..."
              className="w-44 rounded-lg border border-zinc-200 bg-zinc-50 py-1 pl-8 pr-7 text-xs text-zinc-900 placeholder:text-zinc-400 focus:border-emerald-500 focus:bg-white focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-500 sm:w-52"
            />
            {filterText && (
              <button
                type="button"
                onClick={() => setFilterText("")}
                aria-label="Clear table filter"
                className="absolute right-2 top-2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <button
            type="button"
            onClick={exportCsv}
            disabled={rows.length === 0}
            className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </button>
          <button
            type="button"
            onClick={exportJson}
            disabled={rows.length === 0}
            className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
          >
            <FileJson className="h-3.5 w-3.5" />
            JSON
          </button>
        </div>
      </div>

      {columns.length === 0 || rows.length === 0 ? (
        <div className="p-8 text-center text-xs text-zinc-500 dark:text-zinc-400">
          Query executed successfully and returned 0 rows.
        </div>
      ) : filteredAndSortedRows.length === 0 ? (
        <div className="p-8 text-center text-xs text-zinc-500 dark:text-zinc-400">
          No rows match "{filterText}".
        </div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead className="sticky top-0 z-10 bg-zinc-50 text-zinc-600 shadow-2xs dark:bg-zinc-900 dark:text-zinc-300">
              <tr className="border-b border-zinc-200 dark:border-zinc-800">
                {columns.map((col, idx) => {
                  const isSorted = sortColIndex === idx;
                  return (
                    <th key={`${col}-${idx}`} className="whitespace-nowrap px-4 py-2.5 font-semibold">
                      <button
                        type="button"
                        onClick={() => handleSort(idx)}
                        className="inline-flex items-center gap-1.5 font-mono text-[11px] hover:text-zinc-950 dark:hover:text-white"
                      >
                        <span>{col}</span>
                        {isSorted && sortDirection === "asc" ? (
                          <ArrowUp className="h-3 w-3 text-emerald-500" />
                        ) : isSorted && sortDirection === "desc" ? (
                          <ArrowDown className="h-3 w-3 text-emerald-500" />
                        ) : (
                          <ArrowUpDown className="h-3 w-3 opacity-40" />
                        )}
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
              {filteredAndSortedRows.map((row, rowIdx) => (
                <tr
                  key={rowIdx}
                  className="transition hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40"
                >
                  {columns.map((_, colIdx) => {
                    const value = row[colIdx];
                    const isNull = value === null || value === undefined;
                    const isNumber = typeof value === "number";
                    return (
                      <td
                        key={colIdx}
                        className={`whitespace-nowrap px-4 py-2 font-mono text-xs ${
                          isNull
                            ? "italic text-zinc-400 dark:text-zinc-500"
                            : isNumber
                              ? "tabular-nums text-zinc-900 dark:text-zinc-100"
                              : "text-zinc-800 dark:text-zinc-200"
                        }`}
                      >
                        {formatCell(value)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
