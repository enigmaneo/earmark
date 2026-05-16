import { fail, redirect } from '@sveltejs/kit';
import type { AbsItemSummary, EbookFileSummary, MappingRead } from '$lib/api';
import type { Actions, PageServerLoad } from './$types';
import { config } from '$lib/server/config';

const BACKEND = config.backendUrl;

export const load: PageServerLoad = async ({ cookies }): Promise<{
	absItems: AbsItemSummary[];
	ebookFiles: EbookFileSummary[];
	mappings: MappingRead[];
	loadError: string | null;
}> => {
	const token = cookies.get('earmark_session');
	if (!token) redirect(302, '/login');

	const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

	try {
		const [absItemsRes, ebookFilesRes, mappingsRes] = await Promise.all([
			fetch(`${BACKEND}/web/abs-items`, { headers }),
			fetch(`${BACKEND}/web/ebook-files`, { headers }),
			fetch(`${BACKEND}/web/mappings`, { headers }),
		]);

		if (!absItemsRes.ok) {
			const body = await absItemsRes.json().catch(() => ({}));
			return { absItems: [], ebookFiles: [], mappings: [], loadError: body.detail ?? 'Failed to load audiobooks' };
		}
		if (!ebookFilesRes.ok) {
			const body = await ebookFilesRes.json().catch(() => ({}));
			return { absItems: [], ebookFiles: [], mappings: [], loadError: body.detail ?? 'Failed to load ebook files' };
		}
		if (!mappingsRes.ok) {
			const body = await mappingsRes.json().catch(() => ({}));
			return { absItems: [], ebookFiles: [], mappings: [], loadError: body.detail ?? 'Failed to load mappings' };
		}

		const [absItems, ebookFiles, mappings] = await Promise.all([
			absItemsRes.json(),
			ebookFilesRes.json(),
			mappingsRes.json(),
		]);

		return { absItems, ebookFiles, mappings, loadError: null };
	} catch {
		return { absItems: [], ebookFiles: [], mappings: [], loadError: 'Failed to load page data' };
	}
};

export const actions: Actions = {
	createMapping: async ({ request, cookies }) => {
		const token = cookies.get('earmark_session');
		if (!token) return fail(401, { error: 'Not authenticated' });

		const formData = await request.formData();
		const abs_item_id = formData.get('abs_item_id') as string;
		const abs_title = formData.get('abs_title') as string;
		const abs_author = (formData.get('abs_author') as string) || null;
		const ebook_path = formData.get('ebook_path') as string;

		if (!abs_item_id || !abs_title || !ebook_path) {
			return fail(400, { error: 'All fields are required' });
		}

		const res = await fetch(`${BACKEND}/web/mappings`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
			body: JSON.stringify({ abs_item_id, abs_title, abs_author, ebook_path }),
		});

		if (res.status === 409) return fail(409, { error: 'This mapping already exists' });
		if (!res.ok) return fail(res.status, { error: 'Failed to create mapping' });

		const mapping = await res.json();
		return { created: mapping };
	},

	deleteMapping: async ({ request, cookies }) => {
		const token = cookies.get('earmark_session');
		if (!token) return fail(401, { error: 'Not authenticated' });

		const formData = await request.formData();
		const id = Number(formData.get('id'));

		const res = await fetch(`${BACKEND}/web/mappings/${id}`, {
			method: 'DELETE',
			headers: { Authorization: `Bearer ${token}` },
		});

		if (!res.ok) return fail(res.status, { error: 'Delete failed' });
		return { deleted: id };
	},

	syncMapping: async ({ request, cookies }) => {
		const token = cookies.get('earmark_session');
		if (!token) return fail(401, { error: 'Not authenticated' });

		const formData = await request.formData();
		const id = Number(formData.get('id'));

		const res = await fetch(`${BACKEND}/web/mappings/${id}/sync`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${token}` },
		});

		if (res.status === 409) return fail(409, { error: 'Another sync is already running' });
		if (!res.ok) return fail(res.status, { error: 'Sync failed to start' });

		const mapping = (await res.json()) as MappingRead;
		return { synced: mapping };
	},
};
