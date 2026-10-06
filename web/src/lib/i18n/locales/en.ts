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
    send: "Send",
    close: "Close",
    systemTheme: "System",
    theme: "Theme",
    // Fixed replies: the backend sends one of these keys (a "notice", see
    // services/agent/app/models/notices.py) and the chat shows it in this language.
    receiptProposed: "Extracted your receipt from {date} — you can edit or confirm it below.",
    notAReceipt: "That doesn't look like a receipt. Please upload a photo or PDF of an actual receipt.",
    receiptUnreadable:
      "I couldn't read that file. Please upload the receipt as a photo (JPEG, PNG, WEBP, GIF) or a PDF.",
    alreadySent: "That message was already sent — no need to resend it.",
    requestFailed: "Sorry, I couldn't do that — please try again.",
    turnFailed: "Sorry, I ran into a problem and couldn't finish that. Please try again.",
    turnLimitReached: "You've reached today's chat limit. Try again tomorrow.",
    receiptLimitReached: "You've reached today's receipt limit. Try again tomorrow.",
    noResponse: "(no response)",
  },
  // Display labels for the built-in category keys, which are also the stored values:
  // must match CATEGORIES in services/agent/app/constants/categories.py (that service's
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
    subscriptions: "Subscriptions",
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
