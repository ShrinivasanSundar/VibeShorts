import { getApps, initializeApp } from "firebase/app";
import { browserLocalPersistence, browserPopupRedirectResolver, connectAuthEmulator, getAuth, GoogleAuthProvider, indexedDBLocalPersistence, initializeAuth, setPersistence, signInWithPopup } from "firebase/auth";

export function firebaseAuth() {
  const emulator = process.env.NEXT_PUBLIC_MODE !== "production";
  const config = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || (emulator ? "demo-key" : ""),
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || (emulator ? "demo-vibeshorts.firebaseapp.com" : ""),
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || (emulator ? "demo-vibeshorts" : ""),
  };
  if (!config.apiKey || !config.authDomain || !config.projectId) throw new Error("Firebase sign-in is not configured.");
  const first = getApps().length === 0;
  const app = first ? initializeApp(config) : getApps()[0];
  const auth = first ? initializeAuth(app, {
    persistence: [indexedDBLocalPersistence, browserLocalPersistence],
    popupRedirectResolver: browserPopupRedirectResolver,
  }) : getAuth(app);
  if (first) {
    if (emulator) connectAuthEmulator(auth, process.env.NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL || "http://127.0.0.1:9099", { disableWarnings: true });
  }
  return auth;
}

export async function signInWithGoogle() {
  const auth = firebaseAuth();
  // Fast Refresh can reuse an Auth instance initialized with memory-only storage.
  // Migrate it before sign-in instead of relying on the first initialization.
  await auth.authStateReady();
  try {
    await setPersistence(auth, indexedDBLocalPersistence);
  } catch {
    await setPersistence(auth, browserLocalPersistence);
  }
  return signInWithPopup(auth, new GoogleAuthProvider());
}
