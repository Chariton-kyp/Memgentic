"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useActivityStore } from "@/stores/activity-store";
import type { ActivityEventType } from "@/lib/types";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

interface WebSocketMessage {
  type: string;
  data?: Record<string, unknown>;
}

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8100/api/v1/ws";
const MAX_BACKOFF = 30_000;

export function useWebSocket() {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1000);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus("connecting");

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setStatus("connected");
        backoffRef.current = 1000;
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const msg: WebSocketMessage = JSON.parse(event.data);
          const activityStore = useActivityStore.getState();

          if (
            msg.type === "memory_created" ||
            msg.type === "memory:created"
          ) {
            queryClient.invalidateQueries({ queryKey: ["memories"] });
            queryClient.invalidateQueries({ queryKey: ["stats"] });
            queryClient.invalidateQueries({ queryKey: ["sources"] });
            queryClient.invalidateQueries({ queryKey: ["graph"] });
            queryClient.invalidateQueries({ queryKey: ["collections"] });
            activityStore.addEvent({
              type: "memory:created",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
            activityStore.incrementTodayCount();
            toast.success("New memory captured", {
              description:
                typeof msg.data?.content === "string"
                  ? msg.data.content.slice(0, 80)
                  : "A new memory has been added.",
            });
          } else if (
            msg.type === "memory_updated" ||
            msg.type === "memory:updated"
          ) {
            queryClient.invalidateQueries({ queryKey: ["memories"] });
            queryClient.invalidateQueries({ queryKey: ["memory"] });
            queryClient.invalidateQueries({ queryKey: ["collections"] });
            activityStore.addEvent({
              type: "memory:updated",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "memory_pinned" ||
            msg.type === "memory:pinned"
          ) {
            queryClient.invalidateQueries({ queryKey: ["memories"] });
            queryClient.invalidateQueries({ queryKey: ["memories", "pinned"] });
            queryClient.invalidateQueries({ queryKey: ["memory"] });
            activityStore.addEvent({
              type: "memory:pinned" as ActivityEventType,
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "skill_created" ||
            msg.type === "skill:created"
          ) {
            queryClient.invalidateQueries({ queryKey: ["skills"] });
            const skillName =
              typeof msg.data?.name === "string"
                ? msg.data.name
                : "New skill";
            toast.success("Skill created", {
              description: skillName,
            });
            activityStore.addEvent({
              type: "skill:created",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "skill_updated" ||
            msg.type === "skill:updated"
          ) {
            queryClient.invalidateQueries({ queryKey: ["skills"] });
            if (typeof msg.data?.id === "string") {
              queryClient.invalidateQueries({
                queryKey: ["skill", msg.data.id],
              });
            }
            activityStore.addEvent({
              type: "skill:updated",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "skill_deleted" ||
            msg.type === "skill:deleted"
          ) {
            queryClient.invalidateQueries({ queryKey: ["skills"] });
            activityStore.addEvent({
              type: "skill:deleted",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "ingestion_started" ||
            msg.type === "ingestion:started"
          ) {
            queryClient.invalidateQueries({ queryKey: ["ingestion-jobs"] });
            activityStore.addEvent({
              type: "ingestion:started",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
            const sourceType =
              typeof msg.data?.source_type === "string"
                ? msg.data.source_type
                : "source";
            toast.info("Ingestion started", {
              description: `Importing from ${sourceType}`,
            });
          } else if (
            msg.type === "ingestion_progress" ||
            msg.type === "ingestion:progress"
          ) {
            queryClient.invalidateQueries({ queryKey: ["ingestion-jobs"] });
            if (typeof msg.data?.job_id === "string") {
              queryClient.invalidateQueries({
                queryKey: ["ingestion-job", msg.data.job_id],
              });
            }
            activityStore.addEvent({
              type: "ingestion:progress",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "ingestion_completed" ||
            msg.type === "ingestion:completed"
          ) {
            queryClient.invalidateQueries({ queryKey: ["ingestion-jobs"] });
            queryClient.invalidateQueries({ queryKey: ["memories"] });
            queryClient.invalidateQueries({ queryKey: ["stats"] });
            queryClient.invalidateQueries({ queryKey: ["sources"] });
            if (typeof msg.data?.job_id === "string") {
              queryClient.invalidateQueries({
                queryKey: ["ingestion-job", msg.data.job_id],
              });
            }
            activityStore.addEvent({
              type: "ingestion:completed",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
            const processed =
              typeof msg.data?.processed_items === "number"
                ? msg.data.processed_items
                : null;
            toast.success("Ingestion completed", {
              description:
                processed !== null
                  ? `Imported ${processed} item${processed === 1 ? "" : "s"}`
                  : "Import finished successfully.",
            });
          } else if (
            msg.type === "collection_created" ||
            msg.type === "collection:created"
          ) {
            queryClient.invalidateQueries({ queryKey: ["collections"] });
            activityStore.addEvent({
              type: "collection:created",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
            const collectionName =
              typeof msg.data?.name === "string"
                ? msg.data.name
                : "New collection";
            toast.success("Collection created", {
              description: collectionName,
            });
          } else if (
            msg.type === "collection_updated" ||
            msg.type === "collection:updated"
          ) {
            queryClient.invalidateQueries({ queryKey: ["collections"] });
            if (typeof msg.data?.id === "string") {
              queryClient.invalidateQueries({
                queryKey: ["collection", msg.data.id],
              });
            }
            activityStore.addEvent({
              type: "collection:updated",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          } else if (
            msg.type === "collection_deleted" ||
            msg.type === "collection:deleted"
          ) {
            queryClient.invalidateQueries({ queryKey: ["collections"] });
            activityStore.addEvent({
              type: "collection:deleted",
              timestamp: new Date().toISOString(),
              data: msg.data ?? {},
            });
          }
        } catch {
          // Ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setStatus("disconnected");
        wsRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        if (!mountedRef.current) return;
        ws.close();
      };
    } catch {
      setStatus("disconnected");
      scheduleReconnect();
    }
  }, [queryClient]);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);

    reconnectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        connect();
      }
    }, backoffRef.current);

    backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF);
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { status };
}
