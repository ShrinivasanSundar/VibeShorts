import { create } from "zustand";

export type ConfirmRequest = {
  title: string;
  message: string;
  confirmLabel?: string;
};

type State = {
  request: (ConfirmRequest & { resolve: (ok: boolean) => void }) | null;
};

export const useConfirm = create<State>(() => ({ request: null }));

/** Ask the user to confirm a destructive action in the app's modal; resolves true on confirm. */
export function confirmAction(request: ConfirmRequest): Promise<boolean> {
  useConfirm.getState().request?.resolve(false);
  return new Promise((resolve) =>
    useConfirm.setState({
      request: {
        ...request,
        resolve: (ok) => {
          useConfirm.setState({ request: null });
          resolve(ok);
        },
      },
    }),
  );
}
