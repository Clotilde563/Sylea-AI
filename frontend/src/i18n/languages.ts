export interface Language {
  code: string
  label: string        // nom natif
  labelEn: string      // nom en anglais (pour recherche)
}

// 13 langues verifiees, triees par ordre alphabetique (labelEn)
export const LANGUAGES: Language[] = [
  { code: 'ar', label: 'العربية', labelEn: 'Arabic' },
  { code: 'zh', label: '中文 (简体)', labelEn: 'Chinese (Simplified)' },
  { code: 'en', label: 'English', labelEn: 'English (British)' },
  { code: 'en-US', label: 'English (US)', labelEn: 'English (American)' },
  { code: 'fr', label: 'Français', labelEn: 'French' },
  { code: 'de', label: 'Deutsch', labelEn: 'German' },
  { code: 'hi', label: 'हिन्दी', labelEn: 'Hindi' },
  { code: 'it', label: 'Italiano', labelEn: 'Italian' },
  { code: 'ja', label: '日本語', labelEn: 'Japanese' },
  { code: 'ko', label: '한국어', labelEn: 'Korean' },
  { code: 'pt', label: 'Português', labelEn: 'Portuguese' },
  { code: 'ru', label: 'Русский', labelEn: 'Russian' },
  { code: 'es', label: 'Español', labelEn: 'Spanish' },
  { code: 'tr', label: 'Türkçe', labelEn: 'Turkish' },
]
