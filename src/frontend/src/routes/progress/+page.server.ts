import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import type { SortBy, SortDir, MappingRead } from '$lib/api';
import { config } from '$lib/server/config';

const BACKEND = config.backendUrl;

export const load: PageServerLoad = async ({ cookies, url }) => {
	const token = cookies.get('earmark_session');
	if (!token) redirect(302, '/login');

	const document = url.searchParams.get('document') ?? undefined;
	const sort_by = (url.searchParams.get('sort_by') as SortBy) || 'updated_at';
	const sort_dir = (url.searchParams.get('sort_dir') as SortDir) || 'desc';
	const page = Number(url.searchParams.get('page') ?? 1);

	const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

	try {
		const [documentsRes, progressRes, mappingsRes] = await Promise.all([
			fetch(`${BACKEND}/web/documents`, { headers }),
			fetch(
				`${BACKEND}/web/progress?${new URLSearchParams({
					...(document ? { document } : {}),
					sort_by,
					sort_dir,
					page: String(page),
				})}`,
				{ headers }
			),
			fetch(`${BACKEND}/web/mappings`, { headers }),
		]);

		if (!documentsRes.ok || !progressRes.ok) {
			const failed = !documentsRes.ok ? 'documents' : 'progress';
			return {
				documents: [],
				progressList: { data: [], total: 0 },
				document,
				sort_by,
				sort_dir,
				page,
				mappedAbsItemId: null,
				loadError: `Failed to load ${failed} data`,
			};
		}

		const [documents, progressList] = await Promise.all([
			documentsRes.json(),
			progressRes.json(),
		]);

		let mappedAbsItemId: string | null = null;
		if (document && mappingsRes.ok) {
			const mappings = (await mappingsRes.json()) as MappingRead[];
			mappedAbsItemId = mappings.find((m) => m.kosync_document === document)?.abs_item_id ?? null;
		}

		return {
			documents,
			progressList,
			document,
			sort_by,
			sort_dir,
			page,
			mappedAbsItemId,
			loadError: null,
		};
	} catch {
		return {
			documents: [],
			progressList: { data: [], total: 0 },
			document,
			sort_by,
			sort_dir,
			page,
			mappedAbsItemId: null,
			loadError: 'Failed to load data',
		};
	}
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
