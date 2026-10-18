import { create } from "zustand";

// Counts user-visible operations in flight; background polling is deliberately not tracked.
export const useLoading = create<{ pending: number }>(() => ({ pending: 0 }));

export async function track<T>(work: () => Promise<T>): Promise<T> {
  useLoading.setState((s) => ({ pending: s.pending + 1 }));
  try {
    return await work();
  } finally {
    useLoading.setState((s) => ({ pending: s.pending - 1 }));
  }
}
