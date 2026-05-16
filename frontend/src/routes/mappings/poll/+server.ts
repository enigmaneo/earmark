import { json, redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const BACKEND = 'http://localhost:8000';

export const GET: RequestHandler = async ({ cookies }) => {
	const token = cookies.get('earmark_session');
	if (!token) redirect(302, '/login');

	const res = await fetch(`${BACKEND}/web/mappings`, {
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
	});

	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		return json({ error: body.detail ?? 'Failed to load mappings' }, { status: res.status });
	}

	const mappings = await res.json();
	return json(mappings);
};
