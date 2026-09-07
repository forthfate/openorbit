type LanguageSet = {
  id: string;
  intlLocale: string;
  default?: boolean;
  messages: Record<string, unknown>;
};

const languageModules = import.meta.glob("./languages/*.json", { eager: true, import: "default" }) as Record<string, LanguageSet>;
export const languageSets = Object.values(languageModules).sort((left, right) => left.id.localeCompare(right.id));
export const defaultLocale = languageSets.find((language) => language.default)?.id ?? languageSets[0]?.id ?? "";

const interpolate = (template: string, value: number) => template.replace(/\{(?:size|count)\}/g, String(value));
// Locale files are extensible resources. Components narrow feature sections at their use sites.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const hydrateMessages = (messages: Record<string, any>) => ({
  ...messages,
  ui: { ...messages.ui, itemsPerPageValue: (size: number) => interpolate(messages.ui.itemsPerPageValue, size) },
  runUi: {
    ...messages.runUi,
    selected: (count: number) => interpolate(messages.runUi.selected, count),
    deleteSelectedDescription: (count: number) => interpolate(messages.runUi.deleteSelectedDescription, count),
  },
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const locales = Object.fromEntries(languageSets.map((language) => [language.id, hydrateMessages(language.messages)])) as Record<string, any>;
export type Locale = keyof typeof locales;
export const resolveLocale = (value: string | null | undefined): Locale => (value && value in locales ? value : defaultLocale) as Locale;
export const localeOptions = languageSets.map((language) => ({
  id: language.id,
  label: new Intl.DisplayNames([language.id], { type: "language" }).of(language.id) ?? language.id,
}));
export const intlLocales: Record<string, string> = Object.fromEntries(languageSets.map((language) => [language.id, language.intlLocale]));
export const localeMessages = <T>(locale: Locale, section: string): T => {
  const language = languageSets.find((item) => item.id === locale) ?? languageSets.find((item) => item.id === defaultLocale);
  return language?.messages[section] as T;
};
export const localeMessageMap = <T>(section: string): Record<Locale, T> => Object.fromEntries(languageSets.map((language) => [language.id, language.messages[section] as T])) as Record<Locale, T>;
