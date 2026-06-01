import { config } from './config';

export interface SettingRead {
	key: string;
	label: string;
	description: string;
	value_type: string;
	is_secret: boolean;
	has_db_value: boolean;
	display_value: string;
}

const CACHE_TTL_MS = 30_000;

let cachedSettings: SettingRead[] | null = null;
let cacheExpiresAt = 0;

export async function getSettings(token: string): Promise<SettingRead[]> {
	const now = Date.now();
	if (cachedSettings && now < cacheExpiresAt) {
		return cachedSettings;
	}
	const res = await fetch(`${config.backendUrl}/web/settings`, {
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
	});
	if (!res.ok) return [];
	const data = (await res.json()) as SettingRead[];
	cachedSettings = data;
	cacheExpiresAt = now + CACHE_TTL_MS;
	return data;
}

export function getSetting(settings: SettingRead[], key: string): SettingRead | undefined {
	return settings.find((s) => s.key === key);
}
