import { fail, redirect } from '@sveltejs/kit';
import type { AbsItemSummary, EbookFileSummary, MappingRead } from '$lib/api';
import type { Actions, PageServerLoad } from './$types';
import { config } from '$lib/server/config';
import { getSettings, getSetting } from '$lib/server/settings';

const BACKEND = config.backendUrl;

export const load: PageServerLoad = async ({ cookies }): Promise<{
	absItems: AbsItemSummary[];
	ebookFiles: EbookFileSummary[];
	mappings: MappingRead[];
	calibreConfigured: boolean;
	loadError: string | null;
}> => {
	const token = cookies.get('earmark_session');
	if (!token) redirect(302, '/login');

	const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

	try {
		const [absItemsRes, ebookFilesRes, mappingsRes, appSettings] = await Promise.all([
			fetch(`${BACKEND}/web/abs-items`, { headers }),
			fetch(`${BACKEND}/web/ebook-files`, { headers }),
			fetch(`${BACKEND}/web/mappings`, { headers }),
			getSettings(token),
		]);

		if (!absItemsRes.ok) {
			const body = await absItemsRes.json().catch(() => ({}));
			return { absItems: [], ebookFiles: [], mappings: [], calibreConfigured: false, loadError: body.detail ?? 'Failed to load audiobooks' };
		}
		if (!ebookFilesRes.ok) {
			const body = await ebookFilesRes.json().catch(() => ({}));
			return { absItems: [], ebookFiles: [], mappings: [], calibreConfigured: false, loadError: body.detail ?? 'Failed to load ebook files' };
		}
		if (!mappingsRes.ok) {
			const body = await mappingsRes.json().catch(() => ({}));
			return { absItems: [], ebookFiles: [], mappings: [], calibreConfigured: false, loadError: body.detail ?? 'Failed to load mappings' };
		}

		const [absItems, ebookFiles, mappings] = await Promise.all([
			absItemsRes.json(),
			ebookFilesRes.json(),
			mappingsRes.json(),
		]);

		const calibreConfigured = !!(getSetting(appSettings, 'cwa_url')?.display_value);

		return { absItems, ebookFiles, mappings, calibreConfigured, loadError: null };
	} catch {
		return { absItems: [], ebookFiles: [], mappings: [], calibreConfigured: false, loadError: 'Failed to load page data' };
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
		const ebook_source = ((formData.get('ebook_source') as string) || 'local') as
			| 'local'
			| 'calibre';
		const ebook_path = (formData.get('ebook_path') as string) || null;
		const ebook_source_ref = (formData.get('ebook_source_ref') as string) || null;

		if (!abs_item_id || !abs_title) {
			return fail(400, { error: 'Audiobook is required' });
		}
		if (ebook_source === 'local' && !ebook_path) {
			return fail(400, { error: 'Pick a local ebook file' });
		}
		if (ebook_source === 'calibre' && !ebook_source_ref) {
			return fail(400, { error: 'Pick a Calibre Web ebook' });
		}

		const res = await fetch(`${BACKEND}/web/mappings`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
			body: JSON.stringify({
				abs_item_id,
				abs_title,
				abs_author,
				ebook_source,
				ebook_path,
				ebook_source_ref,
			}),
		});

		if (res.status === 409) return fail(409, { error: 'This mapping already exists' });
		if (!res.ok) return fail(res.status, { error: 'Failed to create mapping' });

		const mapping = (await res.json()) as MappingRead;

		// Automatically kick off alignment after creating the mapping
		const syncRes = await fetch(`${BACKEND}/web/mappings/${mapping.id}/sync`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${token}` },
		});
		if (syncRes.ok) {
			const synced = (await syncRes.json()) as MappingRead;
			return { created: synced };
		}

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
