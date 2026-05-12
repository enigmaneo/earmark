// @ts-nocheck
import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load = async ({ cookies }: Parameters<PageServerLoad>[0]) => {
	cookies.delete('earmark_session', { path: '/' });
	redirect(302, '/login');
};
