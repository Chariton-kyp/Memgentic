/** Memgentic API client — typed fetch wrapper for the REST API. */

import type {
  CaptureProfile,
  CaptureProfileSetting,
  Collection,
  CollectionListResponse,
  CreateSkillRequest,
  GraphData,
  GraphNeighbors,
  HealthResponse,
  IngestionJob,
  IngestionJobListResponse,
  Memory,
  MemoryListResponse,
  BriefingResponse,
  BriefingTiersResponse,
  BriefingWeights,
  BriefingWeightsResponse,
  Persona,
  PersonaBootstrapResponse,
  RecallTier,
  SearchResultResponse,
  Skill,
  SkillFile,
  SkillDistribution,
  SkillListResponse,
  SourcesListResponse,
  StatsResponse,
  UpdateSkillRequest,
  UploadResponse,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100/api/v1";

// --- API Key Management ---

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("memgentic_api_key");
}

export function setApiKey(key: string): void {
  localStorage.setItem("memgentic_api_key", key);
}

export function clearApiKey(): void {
  localStorage.removeItem("memgentic_api_key");
}

export function hasApiKey(): boolean {
  return !!getApiKey();
}

// --- Fetch wrapper ---

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }

  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

// --- Memories ---

export async function listMemories(params: {
  page?: number;
  page_size?: number;
  source?: string;
  content_type?: string;
}): Promise<MemoryListResponse> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.source) qs.set("source", params.source);
  if (params.content_type) qs.set("content_type", params.content_type);
  return fetchJson(`${API_BASE}/memories?${qs}`);
}

export async function getMemory(id: string): Promise<Memory> {
  return fetchJson(`${API_BASE}/memories/${id}`);
}

export async function createMemory(body: {
  content: string;
  content_type?: string;
  topics?: string[];
  source?: string;
  capture_profile?: CaptureProfile;
}): Promise<Memory> {
  return fetchJson(`${API_BASE}/memories`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getCaptureProfileSetting(): Promise<CaptureProfileSetting> {
  return fetchJson(`${API_BASE}/settings/capture-profile`);
}

export async function updateCaptureProfileSetting(
  profile: CaptureProfile,
): Promise<CaptureProfileSetting> {
  return fetchJson(`${API_BASE}/settings/capture-profile`, {
    method: "PUT",
    body: JSON.stringify({ profile }),
  });
}

export async function updateMemory(
  id: string,
  body: { content?: string; topics?: string[]; entities?: string[]; status?: string }
): Promise<Memory> {
  return fetchJson(`${API_BASE}/memories/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteMemory(id: string): Promise<void> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const res = await fetch(`${API_BASE}/memories/${id}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

export async function searchMemories(body: {
  query: string;
  sources?: string[];
  exclude_sources?: string[];
  content_types?: string[];
  limit?: number;
}): Promise<SearchResultResponse> {
  return fetchJson(`${API_BASE}/memories/search`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function keywordSearch(body: {
  query: string;
  limit?: number;
}): Promise<MemoryListResponse> {
  return fetchJson(`${API_BASE}/memories/keyword-search`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- Sources & Stats ---

export async function getSources(): Promise<SourcesListResponse> {
  return fetchJson(`${API_BASE}/sources`);
}

export async function getStats(): Promise<StatsResponse> {
  return fetchJson(`${API_BASE}/stats`);
}

// --- Graph ---

export async function getGraphData(
  minWeight?: number
): Promise<GraphData> {
  const qs = minWeight ? `?min_weight=${minWeight}` : "";
  return fetchJson(`${API_BASE}/graph${qs}`);
}

export async function getGraphNeighbors(
  entity: string,
  depth?: number
): Promise<GraphNeighbors> {
  const qs = depth ? `?depth=${depth}` : "";
  return fetchJson(`${API_BASE}/graph/${encodeURIComponent(entity)}${qs}`);
}

// --- Import/Export ---

export async function importJson(
  memories: { content: string; content_type?: string; topics?: string[]; source?: string }[]
): Promise<{ imported: number; errors: number; total: number }> {
  return fetchJson(`${API_BASE}/import/json`, {
    method: "POST",
    body: JSON.stringify({ memories }),
  });
}

export async function exportMemories(
  source?: string
): Promise<{ count: number; memories: unknown[] }> {
  const qs = source ? `?source=${source}` : "";
  return fetchJson(`${API_BASE}/export${qs}`);
}

// --- Health ---

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson(`${API_BASE}/health`);
}

// --- Auth ---

export async function getMe(): Promise<{
  authenticated: boolean;
  id?: string;
  email?: string;
  name?: string;
  plan?: string;
}> {
  return fetchJson(`${API_BASE}/me`);
}

// --- Collections ---

export async function listCollections(): Promise<CollectionListResponse> {
  return fetchJson(`${API_BASE}/collections`);
}

export async function createCollection(body: {
  name: string;
  description?: string;
  color?: string;
}): Promise<Collection> {
  return fetchJson(`${API_BASE}/collections`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateCollection(
  id: string,
  body: { name?: string; description?: string; color?: string }
): Promise<Collection> {
  return fetchJson(`${API_BASE}/collections/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteCollection(id: string): Promise<void> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const res = await fetch(`${API_BASE}/collections/${id}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

export async function getCollectionMemories(
  id: string,
  params?: { page?: number; page_size?: number }
): Promise<MemoryListResponse> {
  const qs = new URLSearchParams();
  if (params?.page) qs.set("page", String(params.page));
  if (params?.page_size) qs.set("page_size", String(params.page_size));
  return fetchJson(`${API_BASE}/collections/${id}/memories?${qs}`);
}

export async function addMemoryToCollection(
  collectionId: string,
  memoryId: string
): Promise<void> {
  await fetchJson(`${API_BASE}/collections/${collectionId}/memories`, {
    method: "POST",
    body: JSON.stringify({ memory_id: memoryId }),
  });
}

export async function removeMemoryFromCollection(
  collectionId: string,
  memoryId: string
): Promise<void> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const res = await fetch(
    `${API_BASE}/collections/${collectionId}/memories/${memoryId}`,
    { method: "DELETE", headers }
  );
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

// --- Pin ---

export async function pinMemory(id: string): Promise<Memory> {
  return fetchJson(`${API_BASE}/memories/${id}/pin`, {
    method: "POST",
  });
}

export async function unpinMemory(id: string): Promise<Memory> {
  return fetchJson(`${API_BASE}/memories/${id}/pin`, {
    method: "DELETE",
  });
}

export async function getPinnedMemories(): Promise<MemoryListResponse> {
  return fetchJson(`${API_BASE}/memories/pinned`);
}

// --- Upload ---

export async function uploadText(body: {
  content: string;
  title?: string;
  topics?: string[];
  content_type?: string;
}): Promise<UploadResponse> {
  return fetchJson(`${API_BASE}/upload/text`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function uploadFile(
  file: File,
  metadata?: { topics?: string[]; content_type?: string }
): Promise<UploadResponse> {
  const apiKey = getApiKey();
  const formData = new FormData();
  formData.append("file", file);
  if (metadata?.topics) {
    formData.append("topics", JSON.stringify(metadata.topics));
  }
  if (metadata?.content_type) {
    formData.append("content_type", metadata.content_type);
  }
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  // Note: Do NOT set Content-Type — browser sets it with boundary for FormData
  const res = await fetch(`${API_BASE}/upload/file`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export async function uploadUrl(body: {
  url: string;
  topics?: string[];
}): Promise<UploadResponse> {
  return fetchJson(`${API_BASE}/upload/url`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- Topics ---

export async function listTopics(): Promise<{ topics: string[] }> {
  return fetchJson(`${API_BASE}/topics`);
}

// --- Related Memories ---

export async function getRelatedMemories(
  id: string
): Promise<{ results: { memory: Memory; score: number }[] }> {
  return fetchJson(`${API_BASE}/memories/${id}/related`);
}

// --- Batch Operations ---

export async function batchUpdateMemories(
  ids: string[],
  updates: { topics?: string[]; status?: string }
): Promise<{ updated: number }> {
  return fetchJson(`${API_BASE}/memories/batch-update`, {
    method: "POST",
    body: JSON.stringify({ memory_ids: ids, updates }),
  });
}

export async function batchDeleteMemories(
  ids: string[]
): Promise<{ deleted: number }> {
  return fetchJson(`${API_BASE}/memories/batch-delete`, {
    method: "POST",
    body: JSON.stringify({ memory_ids: ids }),
  });
}

// --- Skills ---

export async function listSkills(): Promise<SkillListResponse> {
  return fetchJson(`${API_BASE}/skills`);
}

export async function getSkill(id: string): Promise<Skill> {
  return fetchJson(`${API_BASE}/skills/${id}`);
}

export async function createSkill(body: CreateSkillRequest): Promise<Skill> {
  return fetchJson(`${API_BASE}/skills`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateSkill(
  id: string,
  body: UpdateSkillRequest
): Promise<Skill> {
  return fetchJson(`${API_BASE}/skills/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function deleteSkill(id: string): Promise<void> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const res = await fetch(`${API_BASE}/skills/${id}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

export async function createSkillFile(
  skillId: string,
  body: { path: string; content: string }
): Promise<SkillFile> {
  return fetchJson(`${API_BASE}/skills/${skillId}/files`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateSkillFile(
  skillId: string,
  fileId: string,
  body: { path?: string; content?: string }
): Promise<SkillFile> {
  return fetchJson(`${API_BASE}/skills/${skillId}/files/${fileId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function deleteSkillFile(
  skillId: string,
  fileId: string
): Promise<void> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const res = await fetch(`${API_BASE}/skills/${skillId}/files/${fileId}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

export async function distributeSkill(
  id: string,
  tools: string[]
): Promise<{ distributed_to: string[]; paths: string[] }> {
  return fetchJson(`${API_BASE}/skills/${id}/distribute`, {
    method: "POST",
    body: JSON.stringify({ tools }),
  });
}

export async function getSkillDistributions(
  id: string
): Promise<SkillDistribution[]> {
  return fetchJson(`${API_BASE}/skills/${id}/distributions`);
}

// Skill GitHub Import
export async function importSkillFromGitHub(github_url: string): Promise<Skill> {
  return fetchJson(`${API_BASE}/skills/import`, {
    method: "POST",
    body: JSON.stringify({ github_url }),
  });
}

// Remove skill from specific tool
export async function removeSkillFromTool(
  skillId: string,
  tool: string
): Promise<void> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) headers["X-API-Key"] = apiKey;
  const res = await fetch(
    `${API_BASE}/skills/${skillId}/distribute/${tool}`,
    {
      method: "DELETE",
      headers,
    }
  );
  if (res.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
}

// --- Ingestion Jobs ---

export async function listIngestionJobs(params?: {
  limit?: number;
  offset?: number;
}): Promise<IngestionJobListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  return fetchJson(`${API_BASE}/ingestion/jobs?${qs}`);
}

export async function getIngestionJob(id: string): Promise<IngestionJob> {
  return fetchJson(`${API_BASE}/ingestion/jobs/${id}`);
}

export async function cancelIngestionJob(id: string): Promise<void> {
  await fetchJson(`${API_BASE}/ingestion/jobs/${id}/cancel`, {
    method: "POST",
  });
}

// --- Persona (T0 Recall Tier) ---

export async function getPersona(): Promise<Persona> {
  return fetchJson<Persona>(`${API_BASE}/persona`);
}

export async function putPersona(persona: Persona): Promise<Persona> {
  return fetchJson<Persona>(`${API_BASE}/persona`, {
    method: "PUT",
    body: JSON.stringify(persona),
  });
}

export async function patchPersona(patch: Partial<Persona>): Promise<Persona> {
  return fetchJson<Persona>(`${API_BASE}/persona`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function bootstrapPersona(
  body: { source?: "recent" | "skills"; limit?: number } = {},
): Promise<PersonaBootstrapResponse> {
  return fetchJson<PersonaBootstrapResponse>(`${API_BASE}/persona/bootstrap`, {
    method: "POST",
    body: JSON.stringify({
      source: body.source ?? "recent",
      limit: body.limit ?? 100,
    }),
  });
}

export async function acceptPersonaBootstrap(
  persona: Persona,
): Promise<Persona> {
  return fetchJson<Persona>(`${API_BASE}/persona/bootstrap/accept`, {
    method: "POST",
    body: JSON.stringify({ persona }),
  });
}

// --- Chronograph (bitemporal triple store) ---

export type ChronographTriple = {
  id: string;
  subject: string;
  predicate: string;
  object: string;
  valid_from: string | null;
  valid_to: string | null;
  confidence: number;
  source_memory_id: string | null;
  status: "proposed" | "accepted" | "rejected" | "edited";
  proposer: string | null;
  accepted_by: string | null;
  accepted_at: string | null;
  workspace_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ChronographEntity = {
  id: string;
  name: string;
  type: string | null;
  aliases: string[];
  properties: Record<string, unknown>;
  workspace_id: string | null;
  created_at: string | null;
};

export type ChronographStats = {
  entities: number;
  triples: number;
  predicates: number;
  accepted: number;
  proposed: number;
  rejected: number;
  edited: number;
  triples_by_status: Record<string, number>;
};

export async function getChronographStats(): Promise<ChronographStats> {
  return fetchJson<ChronographStats>(`${API_BASE}/chronograph`);
}

export async function listProposedTriples(
  limit = 50,
): Promise<{ count: number; triples: ChronographTriple[] }> {
  return fetchJson(`${API_BASE}/chronograph/proposed?limit=${limit}`);
}

export async function listTriples(params: {
  subject?: string;
  predicate?: string;
  object?: string;
  status?: "proposed" | "accepted" | "rejected" | "edited" | "any";
  as_of?: string;
  limit?: number;
}): Promise<{ count: number; triples: ChronographTriple[] }> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return fetchJson(`${API_BASE}/chronograph/triples?${qs.toString()}`);
}

export async function getChronographTimeline(params: {
  entity?: string;
  status?: "proposed" | "accepted" | "rejected" | "edited" | "any";
  limit?: number;
}): Promise<{ count: number; triples: ChronographTriple[] }> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return fetchJson(`${API_BASE}/chronograph/timeline?${qs.toString()}`);
}

export async function acceptTriple(
  tripleId: string,
): Promise<ChronographTriple> {
  return fetchJson<ChronographTriple>(
    `${API_BASE}/chronograph/triples/${tripleId}/accept`,
    { method: "POST" },
  );
}

export async function rejectTriple(
  tripleId: string,
): Promise<ChronographTriple> {
  return fetchJson<ChronographTriple>(
    `${API_BASE}/chronograph/triples/${tripleId}/reject`,
    { method: "POST" },
  );
}

export async function editTriple(
  tripleId: string,
  patch: Partial<
    Pick<
      ChronographTriple,
      "subject" | "predicate" | "object" | "valid_from" | "valid_to" | "confidence"
    >
  >,
): Promise<ChronographTriple> {
  return fetchJson<ChronographTriple>(
    `${API_BASE}/chronograph/triples/${tripleId}`,
    {
      method: "PATCH",
      body: JSON.stringify(patch),
    },
  );
}

export async function invalidateTripleApi(
  tripleId: string,
  ended?: string,
): Promise<ChronographTriple> {
  return fetchJson<ChronographTriple>(
    `${API_BASE}/chronograph/triples/${tripleId}/invalidate`,
    {
      method: "POST",
      body: JSON.stringify({ ended: ended ?? null }),
    },
  );
}

// --- Recall Tiers (briefing) ---

export async function getBriefing(params: {
  tier?: RecallTier;
  collection?: string;
  topic?: string;
  query?: string;
  entity?: string;
  model_context?: number;
  max_tokens?: number;
} = {}): Promise<BriefingResponse> {
  const qs = new URLSearchParams();
  if (params.tier) qs.set("tier", params.tier);
  if (params.collection) qs.set("collection", params.collection);
  if (params.topic) qs.set("topic", params.topic);
  if (params.query) qs.set("query", params.query);
  if (params.entity) qs.set("entity", params.entity);
  if (params.model_context) qs.set("model_context", String(params.model_context));
  if (params.max_tokens) qs.set("max_tokens", String(params.max_tokens));
  const suffix = qs.toString() ? `?${qs}` : "";
  return fetchJson<BriefingResponse>(`${API_BASE}/briefing${suffix}`);
}

export async function listBriefingTiers(
  model_context?: number,
): Promise<BriefingTiersResponse> {
  const qs = new URLSearchParams();
  if (model_context) qs.set("model_context", String(model_context));
  const suffix = qs.toString() ? `?${qs}` : "";
  return fetchJson<BriefingTiersResponse>(`${API_BASE}/briefing/tiers${suffix}`);
}

export async function previewBriefingWeights(
  weights: Partial<BriefingWeights>,
): Promise<BriefingWeightsResponse> {
  return fetchJson<BriefingWeightsResponse>(`${API_BASE}/briefing/weights`, {
    method: "POST",
    body: JSON.stringify(weights),
  });
}

// --- Watchers ---

import type { WatcherRow, WatcherLog } from "./types";

export async function listWatchers(): Promise<{ watchers: WatcherRow[] }> {
  return fetchJson(`${API_BASE}/watchers`);
}

export async function updateWatcher(
  tool: string,
  patch: { enabled: boolean },
): Promise<WatcherRow> {
  return fetchJson<WatcherRow>(`${API_BASE}/watchers/${tool}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function installWatcher(tool: string): Promise<WatcherRow> {
  return fetchJson<WatcherRow>(`${API_BASE}/watchers/${tool}/install`, {
    method: "POST",
  });
}

export async function uninstallWatcher(tool: string): Promise<WatcherRow> {
  return fetchJson<WatcherRow>(`${API_BASE}/watchers/${tool}/uninstall`, {
    method: "POST",
  });
}

export async function getWatcherLogs(
  tool: string,
  limit = 50,
): Promise<{ logs: WatcherLog[] }> {
  return fetchJson(`${API_BASE}/watchers/${tool}/logs?limit=${limit}`);
}
