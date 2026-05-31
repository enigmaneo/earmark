// Theme switching. Each option maps a friendly label to a Skeleton built-in theme,
// applied via the `data-theme` attribute on <html>. The selection is persisted
// per-browser in localStorage (the same key the inline script in app.html reads
// before first paint to avoid a flash of the default theme).

export const STORAGE_KEY = 'earmark-theme';

export const THEMES = [
	{ value: 'cerberus', label: 'Dark' },
	{ value: 'wintry', label: 'Light' },
	{ value: 'crimson', label: 'Vampire' },
	{ value: 'concord', label: 'Cyberpunk' },
	{ value: 'seafoam', label: 'Nord' },
	{ value: 'modern', label: 'Material' },
	{ value: 'hamlindigo', label: 'White' },
	{ value: 'reign', label: 'Gray' },
] as const;

export type ThemeValue = (typeof THEMES)[number]['value'];

const VALUES = THEMES.map((t) => t.value) as readonly string[];

function isThemeValue(value: string | null): value is ThemeValue {
	return value !== null && VALUES.includes(value);
}

/** Default theme from the OS/browser color-scheme preference. */
export function resolveDefault(): ThemeValue {
	if (typeof window === 'undefined') return 'cerberus';
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'cerberus' : 'wintry';
}

/** The persisted theme, or the OS default when nothing is stored. */
export function getStoredTheme(): ThemeValue {
	if (typeof window === 'undefined') return 'cerberus';
	const stored = localStorage.getItem(STORAGE_KEY);
	return isThemeValue(stored) ? stored : resolveDefault();
}

/** Apply a theme to the document and persist the choice. */
export function applyTheme(value: ThemeValue): void {
	if (typeof document === 'undefined') return;
	document.documentElement.dataset.theme = value;
	localStorage.setItem(STORAGE_KEY, value);
}
