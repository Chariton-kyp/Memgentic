"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getHealth,
  exportMemories,
  importJson,
  getStats,
  getMe,
  clearApiKey,
  hasApiKey,
  getCaptureProfileSetting,
  updateCaptureProfileSetting,
} from "@/lib/api";
import type {
  CaptureProfile,
  HealthResponse,
  StatsResponse,
} from "@/lib/types";
import { toast } from "sonner";
import {
  Wifi,
  WifiOff,
  Download,
  Upload,
  Settings,
  CheckCircle2,
  XCircle,
  Brain,
  Database,
  Radio,
  FileUp,
  LogOut,
  User,
  Layers,
} from "lucide-react";
import {
  ApplyCaptureProfileButton,
  CaptureProfileSelector,
} from "@/components/capture-profile-selector";

interface UserInfo {
  authenticated: boolean;
  id?: string;
  email?: string;
  name?: string;
  plan?: string;
}

export default function SettingsPage() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null);

  const [exporting, setExporting] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [captureProfile, setCaptureProfile] = useState<CaptureProfile | null>(null);
  const [pendingProfile, setPendingProfile] = useState<CaptureProfile | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);

  const apiUrl =
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100/api/v1";

  const checkHealth = useCallback(async () => {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const data = await getHealth();
      setHealth(data);
    } catch (err) {
      setHealthError((err as Error).message);
      setHealth(null);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await getStats();
      setStats(data);
    } catch {
      // Stats are non-critical, fail silently
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const fetchUser = useCallback(async () => {
    if (!hasApiKey()) return;
    try {
      const me = await getMe();
      setUserInfo(me);
    } catch {
      // Non-critical
    }
  }, []);

  const fetchCaptureProfile = useCallback(async () => {
    try {
      const setting = await getCaptureProfileSetting();
      setCaptureProfile(setting.profile);
      setPendingProfile(setting.profile);
    } catch {
      // Non-critical; UI falls back to "enriched" display
      setCaptureProfile("enriched");
      setPendingProfile("enriched");
    }
  }, []);

  async function handleApplyCaptureProfile() {
    if (!pendingProfile || pendingProfile === captureProfile) return;
    setSavingProfile(true);
    try {
      const result = await updateCaptureProfileSetting(pendingProfile);
      setCaptureProfile(result.profile);
      setPendingProfile(result.profile);
      toast.success("Capture profile updated", {
        description: `New writes will use: ${result.profile}`,
      });
    } catch (err) {
      toast.error("Failed to update capture profile", {
        description: (err as Error).message,
      });
    } finally {
      setSavingProfile(false);
    }
  }

  function handleLogout() {
    clearApiKey();
    router.push("/login");
  }

  useEffect(() => {
    checkHealth();
    fetchStats();
    fetchUser();
    fetchCaptureProfile();
  }, [checkHealth, fetchStats, fetchUser, fetchCaptureProfile]);

  async function handleExport() {
    setExporting(true);
    try {
      const data = await exportMemories();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `memgentic-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success("Export complete", {
        description: `Exported ${data.count ?? 0} memories.`,
      });
    } catch (err) {
      toast.error("Export failed", {
        description: (err as Error).message,
      });
    } finally {
      setExporting(false);
    }
  }

  async function handleImportJson(jsonText: string) {
    const parsed = JSON.parse(jsonText);
    const memories = Array.isArray(parsed) ? parsed : parsed.memories;
    if (!Array.isArray(memories)) {
      throw new Error(
        "JSON must be an array or have a 'memories' array field"
      );
    }
    return importJson(memories);
  }

  async function handleImport() {
    if (!importText.trim()) return;
    setImporting(true);
    try {
      const result = await handleImportJson(importText);
      toast.success("Import complete", {
        description: `Imported ${result.imported} memories (${result.errors} errors, ${result.total} total).`,
      });
      setImportText("");
    } catch (err) {
      toast.error("Import failed", {
        description: (err as Error).message,
      });
    } finally {
      setImporting(false);
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const result = await handleImportJson(text);
      toast.success("File import complete", {
        description: `Imported ${result.imported} memories from ${file.name}.`,
      });
    } catch (err) {
      toast.error("File import failed", {
        description: (err as Error).message,
      });
    } finally {
      setImporting(false);
      // Reset file input
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  if (healthLoading && statsLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        <Settings className="size-6" />
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Section 1: Connection Status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {health ? (
                <Wifi className="size-4 text-green-500" />
              ) : (
                <WifiOff className="size-4 text-red-500" />
              )}
              Connection Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">API URL</span>
                <code className="text-xs bg-muted px-2 py-1 rounded">
                  {apiUrl}
                </code>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Status</span>
                {healthError ? (
                  <Badge
                    variant="destructive"
                    className="flex items-center gap-1"
                  >
                    <XCircle className="size-3" />
                    Disconnected
                  </Badge>
                ) : (
                  <Badge
                    variant="default"
                    className="flex items-center gap-1 bg-green-600"
                  >
                    <CheckCircle2 className="size-3" />
                    {health?.status ?? "Connected"}
                  </Badge>
                )}
              </div>
              {health?.version && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Version</span>
                  <span className="text-sm font-mono">{health.version}</span>
                </div>
              )}
              {health?.storage_backend && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">
                    Storage Backend
                  </span>
                  <span className="text-sm">{health.storage_backend}</span>
                </div>
              )}
              {healthError && (
                <p className="text-xs text-destructive">{healthError}</p>
              )}
            </div>
            <Button variant="outline" size="sm" onClick={checkHealth}>
              Refresh
            </Button>
          </CardContent>
        </Card>

        {/* Section 2: Stats */}
        <Card>
          <CardHeader>
            <CardTitle>Statistics</CardTitle>
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <div className="grid grid-cols-2 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-20" />
                ))}
              </div>
            ) : stats ? (
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                  <Brain className="size-5 text-muted-foreground" />
                  <span className="text-2xl font-bold">
                    {stats.total_memories}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Total Memories
                  </span>
                </div>
                <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                  <Database className="size-5 text-muted-foreground" />
                  <span className="text-2xl font-bold">
                    {stats.vector_count}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Vectors
                  </span>
                </div>
                <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                  <Radio className="size-5 text-muted-foreground" />
                  <span className="text-2xl font-bold">
                    {stats.sources?.length ?? 0}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Sources
                  </span>
                </div>
                <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                  <CheckCircle2 className="size-5 text-muted-foreground" />
                  <span className="text-sm font-bold">
                    {stats.store_status}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Store Status
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">
                Unable to load statistics.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Section 3: Account */}
        {userInfo?.authenticated && (
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="size-4" />
                Account
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  {userInfo.name && (
                    <p className="text-sm font-medium">{userInfo.name}</p>
                  )}
                  {userInfo.email && (
                    <p className="text-sm text-muted-foreground">
                      {userInfo.email}
                    </p>
                  )}
                  {userInfo.plan && (
                    <Badge variant="secondary" className="mt-1">
                      {userInfo.plan}
                    </Badge>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={handleLogout}
                >
                  <LogOut className="size-4" />
                  Logout
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Section 3b: Capture Profile */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="size-4" />
              Capture Profile
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Controls how new memories are stored. Raw keeps verbatim
              content with no LLM calls; enriched (default) adds LLM-extracted
              topics and importance; dual keeps both as paired rows. Changes
              apply going forward — existing memories keep their original
              profile.
            </p>
            {pendingProfile ? (
              <CaptureProfileSelector
                value={pendingProfile}
                onChange={setPendingProfile}
                disabled={savingProfile || captureProfile === null}
              />
            ) : (
              <Skeleton className="h-28" />
            )}
            <div className="flex items-center justify-between">
              <div className="text-xs text-muted-foreground">
                {captureProfile && (
                  <>
                    Current: <span className="font-mono">{captureProfile}</span>
                  </>
                )}
              </div>
              {captureProfile && pendingProfile && (
                <ApplyCaptureProfileButton
                  current={captureProfile}
                  pending={pendingProfile}
                  saving={savingProfile}
                  onApply={handleApplyCaptureProfile}
                />
              )}
            </div>
          </CardContent>
        </Card>

        {/* Section 4: Quick Actions */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Import / Export</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Export */}
              <div className="space-y-3">
                <h3 className="text-sm font-medium">Export</h3>
                <p className="text-xs text-muted-foreground">
                  Download all memories as a JSON file.
                </p>
                <Button
                  variant="outline"
                  className="w-full justify-start gap-2"
                  onClick={handleExport}
                  disabled={exporting}
                >
                  <Download className="size-4" />
                  {exporting ? "Exporting..." : "Export All Memories"}
                </Button>
              </div>

              {/* Import */}
              <div className="space-y-3">
                <h3 className="text-sm font-medium">Import</h3>
                <p className="text-xs text-muted-foreground">
                  Upload a JSON file or paste JSON below.
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <Button
                  variant="outline"
                  className="w-full justify-start gap-2"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importing}
                >
                  <FileUp className="size-4" />
                  {importing ? "Importing..." : "Upload JSON File"}
                </Button>
                <Textarea
                  placeholder='Paste JSON here (array of memories or { "memories": [...] })'
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  rows={4}
                />
                <Button
                  variant="outline"
                  className="w-full justify-start gap-2"
                  onClick={handleImport}
                  disabled={importing || !importText.trim()}
                >
                  <Upload className="size-4" />
                  {importing ? "Importing..." : "Import from Text"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
