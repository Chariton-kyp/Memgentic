import { create } from "zustand";

interface DashboardState {
  activeCollection: string | null; // null = "All Memories"
  searchQuery: string;
  uploadModalOpen: boolean;
  setActiveCollection: (id: string | null) => void;
  setSearchQuery: (q: string) => void;
  setUploadModalOpen: (open: boolean) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  activeCollection: null,
  searchQuery: "",
  uploadModalOpen: false,
  setActiveCollection: (id) => set({ activeCollection: id }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  setUploadModalOpen: (open) => set({ uploadModalOpen: open }),
}));
