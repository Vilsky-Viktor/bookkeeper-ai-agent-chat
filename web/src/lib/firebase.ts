import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  connectAuthEmulator,
  getAuth,
  signInWithPopup,
  signOut as firebaseSignOut,
} from "firebase/auth";
import { connectFirestoreEmulator, getFirestore } from "firebase/firestore";

const app = initializeApp({
  apiKey: "demo-key",
  projectId: "demo-bookkeeping",
  authDomain: "localhost",
});

export const auth = getAuth(app);
export const db = getFirestore(app);

if (import.meta.env.DEV) {
  connectAuthEmulator(auth, "http://localhost:9099", { disableWarnings: true });
  connectFirestoreEmulator(db, "localhost", 8081);
}

export const signIn = () => signInWithPopup(auth, new GoogleAuthProvider());
export const signOut = () => firebaseSignOut(auth);

export const CLIENT_ID = crypto.randomUUID();
