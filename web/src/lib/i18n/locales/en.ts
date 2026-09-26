// English defines every key; each other locale is typed as Locale, so a missing or
// misspelled key is a compile error there.
const en = {
  ui: {
    signInSubtitle: "Sign in to manage your transactions.",
    signInButton: "Sign in with Google",
    chatPlaceholder: "Add a 12 EUR coffee today…",
    uploadReceipt: "Upload receipt",
    recordVoice: "Hold to record",
    stopRecording: "Stop recording",
    transcribing: "Transcribing…",
    micError: "Couldn't access your microphone. Please check your browser's permissions.",
    confirmAndSave: "Confirm & save",
    cancel: "Cancel",
    thinking: "thinking…",
    loadEarlierMessages: "Load earlier messages",
    loadingEarlier: "Loading…",
    receiptFoundHeading: "Here's what I found — check it out",
    noTransactions: "No transactions found. Start by chatting.",
    colDate: "Date",
    colAmount: "Amount",
    colCurrency: "Currency",
    colCategory: "Category",
    colDescription: "Description",
    viewReceipt: "View receipt",
    referenceInChat: "Reference in chat",
    deleteTransaction: "Delete transaction",
    confirmDeleteTransaction: "Delete this transaction? This can't be undone.",
    delete: "Delete",
    lightMode: "Light mode",
    darkMode: "Dark mode",
    signOut: "Sign out",
    language: "Language",
    cantPreview: "This attachment can't be previewed here.",
    openInNewTab: "Open in a new tab",
    savedTransactions: "Saved {n} transaction(s) from the receipt.",
    saveFailed: "Couldn't save: {error}",
    viewAttachment: "View attachment",
  },
  // Display labels for the built-in category keys, which are also the stored values:
  // must match CATEGORIES in services/transactions/app/categorize.py (that service's
  // tests/test_contracts.py fails if they drift).
  categories: {
    groceries: "Groceries",
    dining: "Dining",
    transport: "Transport",
    housing: "Housing",
    utilities: "Utilities",
    entertainment: "Entertainment",
    health: "Health",
    shopping: "Shopping",
    travel: "Travel",
    income: "Income",
    fees: "Fees",
    other: "Other",
  },
};

export type Locale = {
  ui: Record<keyof typeof en.ui, string>;
  categories: Record<keyof typeof en.categories, string>;
};

export default en;
