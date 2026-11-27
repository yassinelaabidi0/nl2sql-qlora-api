import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchHealth,
  fetchHistory,
  fetchSchema,
  runQuery,
  type HealthResponse,
  type HistoryEntry,
  type QueryResponse,
  type TableSchema,
} from "./api/client";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { Header } from "./components/Header";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { SchemaSidebar } from "./components/SchemaSidebar";

type Theme = "light" | "dark";

function readInitialTheme(): Theme {
  if (typeof window === "undefined") {
    return "dark";
  }
  const saved = window.localStorage.getItem("nl2sql-theme");
  if (saved === "light" || saved === "dark") {
    return saved;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  const [tables, setTables] = useState<TableSchema[]>([]);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [schemaDdl, setSchemaDdl] = useState("");
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [queryError, setQueryError] = useState<ApiError | null>(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    window.localStorage.setItem("nl2sql-theme", theme);
  }, [theme]);

  const loadHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = await fetchHealth();
      setHealth(data);
    } catch {
      setHealth(null);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const loadSchema = useCallback(async () => {
    setSchemaLoading(true);
    setSchemaError(null);
    try {
      const data = await fetchSchema();
      setTables(data.tables);
    } catch (err) {
      setSchemaError(err instanceof Error ? err.message : "Failed to load schema");
    } finally {
      setSchemaLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const data = await fetchHistory(25);
      setHistory(data.items);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
    void loadSchema();
    void loadHistory();
  }, [loadHealth, loadSchema, loadHistory]);

  const handleOpenHistory = () => {
    setHistoryOpen(true);
    void loadHistory();
  };

  const handleInsertReference = (snippet: string) => {
    setQuestion((prev) => {
      if (!prev.trim()) {
        return snippet;
      }
      return prev.endsWith(" ") ? `${prev}${snippet}` : `${prev} ${snippet}`;
    });
    setSidebarOpen(false);
  };

  const executeQuestion = async (overrideQuestion?: string) => {
    const prompt = (overrideQuestion ?? question).trim();
    if (!prompt || queryLoading) {
      return;
    }

    setLastQuestion(prompt);
    setQueryLoading(true);
    setQueryError(null);

    try {
      const response = await runQuery(prompt, schemaDdl.trim() || undefined);
      setResult(response);
    } catch (err) {
      setResult(null);
      if (err instanceof ApiError) {
        setQueryError(err);
      } else {
        setQueryError(
          new ApiError(
            500,
            "unexpected_error",
            err instanceof Error ? err.message : "Unexpected error running query",
          ),
        );
      }
    } finally {
      setQueryLoading(false);
      void loadHistory();
    }
  };

  const handleReplay = (historicQuestion: string) => {
    setQuestion(historicQuestion);
    setHistoryOpen(false);
    void executeQuestion(historicQuestion);
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <Header
        health={health}
        healthLoading={healthLoading}
        onRefreshHealth={() => void loadHealth()}
        onOpenHistory={handleOpenHistory}
        historyCount={history.length}
        onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
        theme={theme}
        onToggleTheme={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
      />

      <div className="flex min-h-0 flex-1">
        <SchemaSidebar
          tables={tables}
          loading={schemaLoading}
          error={schemaError}
          onRefresh={() => void loadSchema()}
          onInsertReference={handleInsertReference}
          mobileOpen={sidebarOpen}
          onCloseMobile={() => setSidebarOpen(false)}
        />

        <ChatWorkspace
          tables={tables}
          question={question}
          onQuestionChange={setQuestion}
          schemaDdl={schemaDdl}
          onSchemaDdlChange={setSchemaDdl}
          onSubmit={(q) => void executeQuestion(q)}
          isLoading={queryLoading}
          result={result}
          error={queryError}
          lastQuestion={lastQuestion}
          onClearError={() => setQueryError(null)}
        />
      </div>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={history}
        loading={historyLoading}
        error={historyError}
        onRefresh={() => void loadHistory()}
        onReplay={handleReplay}
      />
    </div>
  );
}