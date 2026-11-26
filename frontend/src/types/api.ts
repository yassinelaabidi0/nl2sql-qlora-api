export interface HealthResponse {
  status: string;
  inference_mode: string;
  db_connected: boolean;
}

export interface ColumnInfo {
  name: string;
  data_type: string;
  is_nullable: boolean;
}

export interface TableSchema {
  name: string;
  columns: ColumnInfo[];
}

export interface SchemaResponse {
  tables: TableSchema[];
}

export interface HistoryEntry {
  id: number;
  created_at: string;
  question: string;
  generated_sql: string;
  status: string;
  latency_ms: number;
  error_message: string | null;
}

export interface HistoryResponse {
  items: HistoryEntry[];
}

export interface QueryResponse {
  question: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  latency_ms: number;
  was_repaired: boolean;
  repair_attempts: number;
}
