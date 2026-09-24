import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getPreferences, updatePreferences } from "./api";

export const SUPPORTED_LANGUAGES: { code: string; label: string; dir: "ltr" | "rtl" }[] = [
  { code: "en", label: "English", dir: "ltr" },
  { code: "es", label: "Español", dir: "ltr" },
  { code: "id", label: "Bahasa Indonesia", dir: "ltr" },
  { code: "fr", label: "Français", dir: "ltr" },
  { code: "de", label: "Deutsch", dir: "ltr" },
  { code: "pt", label: "Português", dir: "ltr" },
  { code: "he", label: "עברית", dir: "rtl" },
  { code: "ru", label: "Русский", dir: "ltr" },
  { code: "uk", label: "Українська", dir: "ltr" },
  { code: "ar", label: "العربية", dir: "rtl" },
];

const DIR_BY_LANGUAGE: Record<string, "ltr" | "rtl"> = Object.fromEntries(
  SUPPORTED_LANGUAGES.map((l) => [l.code, l.dir]),
);

const translations = {
  en: {
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
    lightMode: "Light mode",
    darkMode: "Dark mode",
    signOut: "Sign out",
    language: "Language",
    cantPreview: "This attachment can't be previewed here.",
    openInNewTab: "Open in a new tab",
    extractReceiptCaption: "Please extract this receipt.",
    savedTransactions: "Saved {n} transaction(s) from the receipt.",
    viewAttachment: "View attachment",
  },
  es: {
    signInSubtitle: "Inicia sesión para gestionar tus transacciones.",
    signInButton: "Iniciar sesión con Google",
    chatPlaceholder: "Añade un café de 12 EUR hoy…",
    uploadReceipt: "Subir recibo",
    recordVoice: "Mantén pulsado para grabar",
    stopRecording: "Detener grabación",
    transcribing: "Transcribiendo…",
    micError: "No se pudo acceder al micrófono. Comprueba los permisos de tu navegador.",
    confirmAndSave: "Confirmar y guardar",
    cancel: "Cancelar",
    thinking: "pensando…",
    loadEarlierMessages: "Cargar mensajes anteriores",
    loadingEarlier: "Cargando…",
    receiptFoundHeading: "Esto es lo que encontré — échale un vistazo",
    noTransactions: "No se encontraron transacciones. Empieza chateando.",
    colDate: "Fecha",
    colAmount: "Importe",
    colCurrency: "Moneda",
    colCategory: "Categoría",
    colDescription: "Descripción",
    viewReceipt: "Ver recibo",
    referenceInChat: "Referenciar en el chat",
    lightMode: "Modo claro",
    darkMode: "Modo oscuro",
    signOut: "Cerrar sesión",
    language: "Idioma",
    cantPreview: "Este archivo adjunto no se puede previsualizar aquí.",
    openInNewTab: "Abrir en una pestaña nueva",
    extractReceiptCaption: "Por favor, extrae este recibo.",
    savedTransactions: "Se guardaron {n} transacción(es) del recibo.",
    viewAttachment: "Ver archivo adjunto",
  },
  id: {
    signInSubtitle: "Masuk untuk mengelola transaksi Anda.",
    signInButton: "Masuk dengan Google",
    chatPlaceholder: "Tambahkan kopi 12 EUR hari ini…",
    uploadReceipt: "Unggah struk",
    recordVoice: "Tahan untuk merekam",
    stopRecording: "Hentikan rekaman",
    transcribing: "Mentranskripsi…",
    micError: "Tidak dapat mengakses mikrofon. Periksa izin browser Anda.",
    confirmAndSave: "Konfirmasi & simpan",
    cancel: "Batal",
    thinking: "sedang berpikir…",
    loadEarlierMessages: "Muat pesan sebelumnya",
    loadingEarlier: "Memuat…",
    receiptFoundHeading: "Ini yang saya temukan — coba lihat",
    noTransactions: "Tidak ada transaksi. Mulai dengan chat.",
    colDate: "Tanggal",
    colAmount: "Jumlah",
    colCurrency: "Mata Uang",
    colCategory: "Kategori",
    colDescription: "Deskripsi",
    viewReceipt: "Lihat struk",
    referenceInChat: "Rujuk di chat",
    lightMode: "Mode terang",
    darkMode: "Mode gelap",
    signOut: "Keluar",
    language: "Bahasa",
    cantPreview: "Lampiran ini tidak dapat dipratinjau di sini.",
    openInNewTab: "Buka di tab baru",
    extractReceiptCaption: "Tolong ekstrak struk ini.",
    savedTransactions: "{n} transaksi dari struk berhasil disimpan.",
    viewAttachment: "Lihat lampiran",
  },
  fr: {
    signInSubtitle: "Connectez-vous pour gérer vos transactions.",
    signInButton: "Se connecter avec Google",
    chatPlaceholder: "Ajoutez un café à 12 EUR aujourd'hui…",
    uploadReceipt: "Téléverser un reçu",
    recordVoice: "Maintenir pour enregistrer",
    stopRecording: "Arrêter l'enregistrement",
    transcribing: "Transcription en cours…",
    micError: "Impossible d'accéder au microphone. Vérifiez les autorisations de votre navigateur.",
    confirmAndSave: "Confirmer et enregistrer",
    cancel: "Annuler",
    thinking: "réflexion…",
    loadEarlierMessages: "Charger les messages précédents",
    loadingEarlier: "Chargement…",
    receiptFoundHeading: "Voici ce que j'ai trouvé — jetez-y un œil",
    noTransactions: "Aucune transaction trouvée. Commencez par discuter.",
    colDate: "Date",
    colAmount: "Montant",
    colCurrency: "Devise",
    colCategory: "Catégorie",
    colDescription: "Description",
    viewReceipt: "Voir le reçu",
    referenceInChat: "Référencer dans le chat",
    lightMode: "Mode clair",
    darkMode: "Mode sombre",
    signOut: "Se déconnecter",
    language: "Langue",
    cantPreview: "Cette pièce jointe ne peut pas être prévisualisée ici.",
    openInNewTab: "Ouvrir dans un nouvel onglet",
    extractReceiptCaption: "Merci d'extraire ce reçu.",
    savedTransactions: "{n} transaction(s) du reçu enregistrée(s).",
    viewAttachment: "Voir la pièce jointe",
  },
  de: {
    signInSubtitle: "Melde dich an, um deine Transaktionen zu verwalten.",
    signInButton: "Mit Google anmelden",
    chatPlaceholder: "Füge heute einen Kaffee für 12 EUR hinzu…",
    uploadReceipt: "Beleg hochladen",
    recordVoice: "Zum Aufnehmen halten",
    stopRecording: "Aufnahme stoppen",
    transcribing: "Wird transkribiert…",
    micError: "Zugriff auf das Mikrofon nicht möglich. Bitte überprüfe die Berechtigungen deines Browsers.",
    confirmAndSave: "Bestätigen & speichern",
    cancel: "Abbrechen",
    thinking: "denke nach…",
    loadEarlierMessages: "Frühere Nachrichten laden",
    loadingEarlier: "Lade…",
    receiptFoundHeading: "Das habe ich gefunden — sieh es dir an",
    noTransactions: "Keine Transaktionen gefunden. Starte mit dem Chat.",
    colDate: "Datum",
    colAmount: "Betrag",
    colCurrency: "Währung",
    colCategory: "Kategorie",
    colDescription: "Beschreibung",
    viewReceipt: "Beleg ansehen",
    referenceInChat: "Im Chat referenzieren",
    lightMode: "Heller Modus",
    darkMode: "Dunkler Modus",
    signOut: "Abmelden",
    language: "Sprache",
    cantPreview: "Dieser Anhang kann hier nicht angezeigt werden.",
    openInNewTab: "In neuem Tab öffnen",
    extractReceiptCaption: "Bitte extrahiere diesen Beleg.",
    savedTransactions: "{n} Transaktion(en) aus dem Beleg gespeichert.",
    viewAttachment: "Anhang ansehen",
  },
  pt: {
    signInSubtitle: "Entre para gerenciar suas transações.",
    signInButton: "Entrar com o Google",
    chatPlaceholder: "Adicione um café de 12 EUR hoje…",
    uploadReceipt: "Enviar recibo",
    recordVoice: "Segure para gravar",
    stopRecording: "Parar gravação",
    transcribing: "Transcrevendo…",
    micError: "Não foi possível acessar o microfone. Verifique as permissões do seu navegador.",
    confirmAndSave: "Confirmar e salvar",
    cancel: "Cancelar",
    thinking: "pensando…",
    loadEarlierMessages: "Carregar mensagens anteriores",
    loadingEarlier: "Carregando…",
    receiptFoundHeading: "Aqui está o que encontrei — dê uma olhada",
    noTransactions: "Nenhuma transação encontrada. Comece conversando.",
    colDate: "Data",
    colAmount: "Valor",
    colCurrency: "Moeda",
    colCategory: "Categoria",
    colDescription: "Descrição",
    viewReceipt: "Ver recibo",
    referenceInChat: "Referenciar no chat",
    lightMode: "Modo claro",
    darkMode: "Modo escuro",
    signOut: "Sair",
    language: "Idioma",
    cantPreview: "Este anexo não pode ser visualizado aqui.",
    openInNewTab: "Abrir em uma nova aba",
    extractReceiptCaption: "Por favor, extraia este recibo.",
    savedTransactions: "{n} transação(ões) do recibo salva(s).",
    viewAttachment: "Ver anexo",
  },
  he: {
    signInSubtitle: "התחבר כדי לנהל את העסקאות שלך.",
    signInButton: "התחברות עם Google",
    chatPlaceholder: "הוסף קפה ב-12 יורו היום…",
    uploadReceipt: "העלאת קבלה",
    recordVoice: "החזק כדי להקליט",
    stopRecording: "עצור הקלטה",
    transcribing: "מתמלל…",
    micError: "לא ניתן לגשת למיקרופון. בדוק את הרשאות הדפדפן שלך.",
    confirmAndSave: "אשר ושמור",
    cancel: "ביטול",
    thinking: "חושב…",
    loadEarlierMessages: "טען הודעות קודמות",
    loadingEarlier: "טוען…",
    receiptFoundHeading: "הנה מה שמצאתי — בדוק את זה",
    noTransactions: "לא נמצאו עסקאות. התחל בשיחה.",
    colDate: "תאריך",
    colAmount: "סכום",
    colCurrency: "מטבע",
    colCategory: "קטגוריה",
    colDescription: "תיאור",
    viewReceipt: "צפה בקבלה",
    referenceInChat: "התייחס בצ'אט",
    lightMode: "מצב בהיר",
    darkMode: "מצב כהה",
    signOut: "התנתקות",
    language: "שפה",
    cantPreview: "לא ניתן להציג תצוגה מקדימה של הקובץ המצורף הזה כאן.",
    openInNewTab: "פתח בכרטיסייה חדשה",
    extractReceiptCaption: "אנא חלץ את הקבלה הזו.",
    savedTransactions: "נשמרו {n} עסקאות מהקבלה.",
    viewAttachment: "צפה בקובץ המצורף",
  },
  ru: {
    signInSubtitle: "Войдите, чтобы управлять своими транзакциями.",
    signInButton: "Войти через Google",
    chatPlaceholder: "Добавьте кофе за 12 EUR сегодня…",
    uploadReceipt: "Загрузить чек",
    recordVoice: "Удерживайте для записи",
    stopRecording: "Остановить запись",
    transcribing: "Расшифровка…",
    micError: "Не удалось получить доступ к микрофону. Проверьте разрешения браузера.",
    confirmAndSave: "Подтвердить и сохранить",
    cancel: "Отмена",
    thinking: "думаю…",
    loadEarlierMessages: "Загрузить более ранние сообщения",
    loadingEarlier: "Загрузка…",
    receiptFoundHeading: "Вот что я нашёл — проверьте",
    noTransactions: "Транзакции не найдены. Начните с чата.",
    colDate: "Дата",
    colAmount: "Сумма",
    colCurrency: "Валюта",
    colCategory: "Категория",
    colDescription: "Описание",
    viewReceipt: "Посмотреть чек",
    referenceInChat: "Сослаться в чате",
    lightMode: "Светлая тема",
    darkMode: "Тёмная тема",
    signOut: "Выйти",
    language: "Язык",
    cantPreview: "Этот файл нельзя предварительно просмотреть здесь.",
    openInNewTab: "Открыть в новой вкладке",
    extractReceiptCaption: "Пожалуйста, извлеките данные из этого чека.",
    savedTransactions: "Сохранено {n} транзакций из чека.",
    viewAttachment: "Просмотреть вложение",
  },
  uk: {
    signInSubtitle: "Увійдіть, щоб керувати своїми транзакціями.",
    signInButton: "Увійти через Google",
    chatPlaceholder: "Додайте каву за 12 EUR сьогодні…",
    uploadReceipt: "Завантажити чек",
    recordVoice: "Утримуйте для запису",
    stopRecording: "Зупинити запис",
    transcribing: "Розшифровка…",
    micError: "Не вдалося отримати доступ до мікрофона. Перевірте дозволи браузера.",
    confirmAndSave: "Підтвердити і зберегти",
    cancel: "Скасувати",
    thinking: "думаю…",
    loadEarlierMessages: "Завантажити попередні повідомлення",
    loadingEarlier: "Завантаження…",
    receiptFoundHeading: "Ось що я знайшов — перевірте",
    noTransactions: "Транзакцій не знайдено. Почніть із чату.",
    colDate: "Дата",
    colAmount: "Сума",
    colCurrency: "Валюта",
    colCategory: "Категорія",
    colDescription: "Опис",
    viewReceipt: "Переглянути чек",
    referenceInChat: "Послатися в чаті",
    lightMode: "Світла тема",
    darkMode: "Темна тема",
    signOut: "Вийти",
    language: "Мова",
    cantPreview: "Цей файл не можна попередньо переглянути тут.",
    openInNewTab: "Відкрити в новій вкладці",
    extractReceiptCaption: "Будь ласка, витягніть дані з цього чека.",
    savedTransactions: "Збережено {n} транзакцій із чека.",
    viewAttachment: "Переглянути вкладення",
  },
  ar: {
    signInSubtitle: "سجّل الدخول لإدارة معاملاتك.",
    signInButton: "تسجيل الدخول عبر Google",
    chatPlaceholder: "أضف قهوة بـ 12 يورو اليوم…",
    uploadReceipt: "رفع الإيصال",
    recordVoice: "اضغط مطولاً للتسجيل",
    stopRecording: "إيقاف التسجيل",
    transcribing: "جارٍ تحويل الصوت إلى نص…",
    micError: "تعذر الوصول إلى الميكروفون. يرجى التحقق من أذونات المتصفح.",
    confirmAndSave: "تأكيد وحفظ",
    cancel: "إلغاء",
    thinking: "أفكر…",
    loadEarlierMessages: "تحميل الرسائل السابقة",
    loadingEarlier: "جارٍ التحميل…",
    receiptFoundHeading: "هذا ما وجدته — تحقق منه",
    noTransactions: "لم يتم العثور على معاملات. ابدأ بالمحادثة.",
    colDate: "التاريخ",
    colAmount: "المبلغ",
    colCurrency: "العملة",
    colCategory: "الفئة",
    colDescription: "الوصف",
    viewReceipt: "عرض الإيصال",
    referenceInChat: "الإشارة في المحادثة",
    lightMode: "الوضع الفاتح",
    darkMode: "الوضع الداكن",
    signOut: "تسجيل الخروج",
    language: "اللغة",
    cantPreview: "لا يمكن معاينة هذا المرفق هنا.",
    openInNewTab: "فتح في علامة تبويب جديدة",
    extractReceiptCaption: "يرجى استخراج بيانات هذا الإيصال.",
    savedTransactions: "تم حفظ {n} معاملة من الإيصال.",
    viewAttachment: "عرض المرفق",
  },
} as const;

type Language = keyof typeof translations;
type Key = keyof (typeof translations)["en"];

function isLanguage(l: string): l is Language {
  return l in translations;
}

// Display-only labels for the built-in category keys (see CATEGORIES in
// services/transactions/app/categorize.py — keep this list in sync with that one).
// The stored/matched value is always the English key underneath; a category the user
// typed via a correction (not in this list) just displays as-is in every language,
// since there's nothing to translate it from.
const CATEGORY_LABELS: Record<Language, Record<string, string>> = {
  en: {
    groceries: "Groceries", dining: "Dining", transport: "Transport", housing: "Housing",
    utilities: "Utilities", entertainment: "Entertainment", health: "Health",
    shopping: "Shopping", travel: "Travel", income: "Income", fees: "Fees", other: "Other",
  },
  es: {
    groceries: "Comestibles", dining: "Restaurantes", transport: "Transporte", housing: "Vivienda",
    utilities: "Servicios", entertainment: "Entretenimiento", health: "Salud",
    shopping: "Compras", travel: "Viajes", income: "Ingresos", fees: "Comisiones", other: "Otro",
  },
  id: {
    groceries: "Bahan Makanan", dining: "Makan di Luar", transport: "Transportasi", housing: "Perumahan",
    utilities: "Utilitas", entertainment: "Hiburan", health: "Kesehatan",
    shopping: "Belanja", travel: "Perjalanan", income: "Pendapatan", fees: "Biaya", other: "Lainnya",
  },
  fr: {
    groceries: "Épicerie", dining: "Restauration", transport: "Transport", housing: "Logement",
    utilities: "Charges", entertainment: "Divertissement", health: "Santé",
    shopping: "Achats", travel: "Voyage", income: "Revenus", fees: "Frais", other: "Autre",
  },
  de: {
    groceries: "Lebensmittel", dining: "Restaurant", transport: "Transport", housing: "Wohnen",
    utilities: "Nebenkosten", entertainment: "Unterhaltung", health: "Gesundheit",
    shopping: "Einkaufen", travel: "Reisen", income: "Einkommen", fees: "Gebühren", other: "Sonstiges",
  },
  pt: {
    groceries: "Mercado", dining: "Restaurante", transport: "Transporte", housing: "Moradia",
    utilities: "Utilidades", entertainment: "Entretenimento", health: "Saúde",
    shopping: "Compras", travel: "Viagem", income: "Receita", fees: "Taxas", other: "Outro",
  },
  he: {
    groceries: "מכולת", dining: "מסעדות", transport: "תחבורה", housing: "דיור",
    utilities: "שירותים", entertainment: "בידור", health: "בריאות",
    shopping: "קניות", travel: "נסיעות", income: "הכנסה", fees: "עמלות", other: "אחר",
  },
  ru: {
    groceries: "Продукты", dining: "Рестораны", transport: "Транспорт", housing: "Жильё",
    utilities: "Коммунальные услуги", entertainment: "Развлечения", health: "Здоровье",
    shopping: "Покупки", travel: "Путешествия", income: "Доход", fees: "Комиссии", other: "Другое",
  },
  uk: {
    groceries: "Продукти", dining: "Ресторани", transport: "Транспорт", housing: "Житло",
    utilities: "Комунальні послуги", entertainment: "Розваги", health: "Здоров'я",
    shopping: "Покупки", travel: "Подорожі", income: "Дохід", fees: "Комісії", other: "Інше",
  },
  ar: {
    groceries: "بقالة", dining: "مطاعم", transport: "مواصلات", housing: "سكن",
    utilities: "مرافق", entertainment: "ترفيه", health: "صحة",
    shopping: "تسوق", travel: "سفر", income: "دخل", fees: "رسوم", other: "أخرى",
  },
};

interface Ctx {
  language: Language;
  setLanguage: (l: string) => void;
  t: (key: Key) => string;
  tCategory: (category: string) => string;
}

const LanguageContext = createContext<Ctx | null>(null);

function readCachedLanguage(): Language {
  try {
    const stored = localStorage.getItem("language");
    if (stored && isLanguage(stored)) return stored;
  } catch {
    // ignore — localStorage can throw in private/blocked-storage contexts
  }
  return "en";
}

export function LanguageProvider({ userId, children }: { userId: string | null; children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readCachedLanguage);

  useEffect(() => {
    document.documentElement.dir = DIR_BY_LANGUAGE[language] ?? "ltr";
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    // The authoritative value lives server-side per account (see /api/chat/preferences);
    // the localStorage read above is just so returning users don't flash back to
    // English for the instant before this fetch resolves.
    if (!userId) return;
    getPreferences()
      .then((p) => {
        if (isLanguage(p.language)) {
          setLanguageState(p.language);
          try {
            localStorage.setItem("language", p.language);
          } catch {
            // ignore
          }
        }
      })
      .catch(() => {
        // best effort — stay on the cached/default language
      });
  }, [userId]);

  function setLanguage(l: string) {
    if (!isLanguage(l)) return;
    setLanguageState(l);
    try {
      localStorage.setItem("language", l);
    } catch {
      // ignore
    }
    updatePreferences({ language: l }).catch(() => {
      // best effort — the UI already switched; a failed save just means it reverts
      // to the old language next reload
    });
  }

  function t(key: Key): string {
    return translations[language][key];
  }

  function tCategory(category: string): string {
    return CATEGORY_LABELS[language][category.toLowerCase()] ?? category;
  }

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t, tCategory }}>{children}</LanguageContext.Provider>
  );
}

export function useTranslation(): Ctx {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useTranslation must be used within a LanguageProvider");
  return ctx;
}
