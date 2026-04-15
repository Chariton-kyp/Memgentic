/** TypeScript types matching the Memgentic REST API schemas. */

export interface SourceMetadata {
  platform: string;
  platform_version: string | null;
  session_id: string | null;
  session_title: string | null;
  capture_method: string;
  original_timestamp: string | null;
  file_path: string | null;
}

export interface Memory {
  id: string;
  content: string;
  content_type: string;
  platform: string;
  topics: string[];
  entities: string[];
  confidence: number;
  status: string;
  is_pinned: boolean;
  pinned_at: string | null;
  created_at: string;
  last_accessed: string | null;
  access_count: number;
  source: SourceMetadata;
}

export interface MemoryListResponse {
  memories: Memory[];
  total: number;
  page: number;
  page_size: number;
}

export interface SearchResult {
  memory: Memory;
  score: number;
}

export interface SearchResultResponse {
  results: SearchResult[];
  query: string;
  total: number;
}

export interface SourceStats {
  platform: string;
  count: number;
  percentage: number;
}

export interface SourcesListResponse {
  sources: SourceStats[];
  total: number;
}

export interface StatsResponse {
  total_memories: number;
  vector_count: number;
  store_status: string;
  sources: SourceStats[];
}

export interface GraphNode {
  id: string;
  type: string;
  count: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphNeighbors {
  entity: string;
  neighbors: { name: string; type: string; count: number; depth: number }[];
  not_found?: boolean;
}

export interface HealthResponse {
  status: string;
  version: string;
  storage_backend: string;
}

// Collections
export interface Collection {
  id: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  position: number;
  memory_count: number;
  created_at: string;
  updated_at: string;
}

export interface CollectionListResponse {
  collections: Collection[];
  total: number;
}

// Uploads
export interface UploadResponse {
  id: string;
  filename: string;
  status: string;
  memory_id: string | null;
  error_message: string | null;
  created_at: string;
}

// --- Skills ---

export interface SkillFile {
  id: string;
  path: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface SkillDistribution {
  tool: string;
  target_path: string;
  distributed_at: string;
  status: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  config: Record<string, unknown>;
  source: string;
  source_url: string | null;
  version: string;
  tags: string[];
  distribute_to: string[];
  auto_distribute: boolean;
  auto_extracted: boolean;
  extraction_confidence: number;
  files: SkillFile[];
  distributions: SkillDistribution[];
  created_at: string;
  updated_at: string;
}

export interface SkillListResponse {
  skills: Skill[];
  total: number;
}

export interface CreateSkillRequest {
  name: string;
  description?: string;
  content?: string;
  tags?: string[];
  distribute_to?: string[];
  files?: { path: string; content: string }[];
}

export interface UpdateSkillRequest {
  name?: string;
  description?: string;
  content?: string;
  tags?: string[];
  distribute_to?: string[];
}

// Ingestion Jobs
export interface IngestionJob {
  id: string;
  source_type: string;
  source_path: string | null;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  total_items: number;
  processed_items: number;
  failed_items: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface IngestionJobListResponse {
  jobs: IngestionJob[];
  total: number;
}

// Activity
export type ActivityEventType =
  | "memory:created"
  | "memory:updated"
  | "memory:deleted"
  | "memory:pinned"
  | "skill:created"
  | "skill:updated"
  | "skill:deleted"
  | "ingestion:started"
  | "ingestion:progress"
  | "ingestion:completed"
  | "collection:created"
  | "collection:updated"
  | "collection:deleted";

export interface ActivityEvent {
  type: ActivityEventType;
  timestamp: string;
  data: Record<string, unknown>;
}
