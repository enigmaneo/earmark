import { json, redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { config } from '$lib/server/config';

const BACKEND = config.backendUrl;

export const GET: RequestHandler = async ({ cookies, url }) => {
	const token = cookies.get('earmark_session');
	if (!token) redirect(302, '/login');

	const absItemId = url.searchParams.get('abs_item_id');
	if (!absItemId) {
		return json({ error: 'abs_item_id is required' }, { status: 400 });
	}

	const backendUrl = `${BACKEND}/web/calibre-ebooks?abs_item_id=${encodeURIComponent(absItemId)}`;
	const res = await fetch(backendUrl, {
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
	});

	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		return json({ error: body.detail ?? 'Calibre Web request failed' }, { status: res.status });
	}

	return json(await res.json());
};
