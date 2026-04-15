import { create } from "zustand";
import type { ActivityEvent } from "@/lib/types";

interface ActivityState {
  events: ActivityEvent[];
  addEvent: (event: ActivityEvent) => void;
  todayCount: number;
  incrementTodayCount: () => void;
}

export const useActivityStore = create<ActivityState>((set) => ({
  events: [],
  addEvent: (event) =>
    set((state) => ({
      events: [event, ...state.events].slice(0, 100), // Keep last 100 events
    })),
  todayCount: 0,
  incrementTodayCount: () =>
    set((state) => ({ todayCount: state.todayCount + 1 })),
}));
