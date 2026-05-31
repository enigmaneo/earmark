import { redirect } from '@sveltejs/kit';
import type { Actions } from './$types';

export const actions: Actions = {
	default: async ({ cookies }) => {
		cookies.delete('earmark_session', { path: '/' });
		redirect(302, '/login');
	}
};
