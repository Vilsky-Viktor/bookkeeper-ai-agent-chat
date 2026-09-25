/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_RECEIPTS_BUCKET: string;
  readonly VITE_FIREBASE_API_KEY?: string;
  readonly VITE_FIREBASE_PROJECT_ID?: string;
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
