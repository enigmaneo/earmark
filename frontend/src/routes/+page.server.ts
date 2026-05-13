import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import type { SortBy, SortDir } from '$lib/api';

const BACKEND = 'http://localhost:8000';

export const load: PageServerLoad = async ({ cookies, url }) => {
	const token = cookies.get('earmark_session');
	if (!token) redirect(302, '/login');

	const document = url.searchParams.get('document') ?? undefined;
	const sort_by = (url.searchParams.get('sort_by') as SortBy) || 'updated_at';
	const sort_dir = (url.searchParams.get('sort_dir') as SortDir) || 'desc';
	const page = Number(url.searchParams.get('page') ?? 1);

	const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

	const [documents, progressList] = await Promise.all([
		fetch(`${BACKEND}/web/documents`, { headers }).then((r) => r.json()),
		fetch(
			`${BACKEND}/web/progress?${new URLSearchParams({
				...(document ? { document } : {}),
				sort_by,
				sort_dir,
				page: String(page),
			})}`,
			{ headers }
		).then((r) => r.json()),
	]);

	return { documents, progressList, document, sort_by, sort_dir, page };
};

export const actions: Actions = {
	deleteRecord: async ({ request, cookies }) => {
		const token = cookies.get('earmark_session');
		if (!token) return fail(401, { error: 'Not authenticated' });

		const formData = await request.formData();
		const id = Number(formData.get('id'));

		const res = await fetch(`${BACKEND}/web/records/${id}`, {
			method: 'DELETE',
			headers: { Authorization: `Bearer ${token}` },
		});

		if (!res.ok) return fail(res.status, { error: 'Delete failed' });
		return { deleted: id };
	},
};
