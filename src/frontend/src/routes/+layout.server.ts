import { config } from '$lib/server/config';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals, fetch }) => {
	let timezone = 'UTC';
	try {
		const res = await fetch(`${config.backendUrl}/web/config`);
		if (res.ok) {
			const body = (await res.json()) as { timezone: string };
			timezone = body.timezone;
		}
	} catch {
		// fall back to UTC
	}
	return { user: locals.user, timezone };
};
