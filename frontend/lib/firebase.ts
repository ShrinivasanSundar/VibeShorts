import { getApps, initializeApp } from "firebase/app";
import { browserPopupRedirectResolver, connectAuthEmulator, getAuth, inMemoryPersistence, initializeAuth } from "firebase/auth";

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
    persistence: inMemoryPersistence,
    popupRedirectResolver: browserPopupRedirectResolver,
  }) : getAuth(app);
  if (first) {
    if (emulator) connectAuthEmulator(auth, process.env.NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL || "http://127.0.0.1:9099", { disableWarnings: true });
  }
  return auth;
}
