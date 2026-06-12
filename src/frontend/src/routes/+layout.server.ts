import { config } from '$lib/server/config';
import type { LayoutServerLoad } from './$types';

// Guard against a malformed timezone from the backend: an invalid value would
// make Intl.DateTimeFormat throw at render time.
function isValidTimeZone(tz: unknown): tz is string {
	if (typeof tz !== 'string' || !tz) return false;
	try {
		Intl.DateTimeFormat(undefined, { timeZone: tz });
		return true;
	} catch {
		return false;
	}
}

export const load: LayoutServerLoad = async ({ locals, fetch }) => {
	let timezone = 'UTC';
	try {
		const res = await fetch(`${config.backendUrl}/web/config`);
		if (res.ok) {
			const body = (await res.json()) as { timezone: string };
			if (isValidTimeZone(body.timezone)) {
				timezone = body.timezone;
			}
		}
	} catch {
		// fall back to UTC
	}
	return { user: locals.user, timezone };
};
