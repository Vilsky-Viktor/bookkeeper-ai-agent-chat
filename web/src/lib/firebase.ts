import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  connectAuthEmulator,
  getAuth,
  signInWithPopup,
  signOut as firebaseSignOut,
} from "firebase/auth";

// VITE_FIREBASE_* are only set in a real production build (see
// .github/workflows/web.yml) — local dev's .env never sets them, so this falls back
// to the same fake local-emulator config it always used, unchanged.
const app = initializeApp({
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || "demo-key",
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "demo-bookkeeping",
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "localhost",
});

export const auth = getAuth(app);

if (import.meta.env.DEV) {
  connectAuthEmulator(auth, "http://localhost:9099", { disableWarnings: true });
}

export const signIn = () => signInWithPopup(auth, new GoogleAuthProvider());
export const signOut = () => firebaseSignOut(auth);
