/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_RECEIPTS_BUCKET: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
