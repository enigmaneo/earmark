import { fail, redirect } from '@sveltejs/kit';
import type { Actions } from './$types';
import { config } from '$lib/server/config';

const BACKEND = config.backendUrl;

export const actions: Actions = {
	default: async ({ request, cookies }) => {
		const data = await request.formData();
		const email = data.get('email') as string;
		const password = data.get('password') as string;

		if (!email || !password) {
			return fail(400, { error: 'Email and password are required' });
		}

		let res: Response;
		try {
			res = await fetch(`${BACKEND}/auth/login`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email, password })
			});
		} catch {
			return fail(503, { error: 'Could not reach server' });
		}

		if (!res.ok) {
			return fail(401, { error: 'Invalid email or password' });
		}

		const { access_token } = await res.json();
		cookies.set('earmark_session', access_token, {
			httpOnly: true,
			path: '/',
			maxAge: 60 * 60 * 24 * 7,
			sameSite: 'lax'
		});

		redirect(302, '/mappings');
	}
};
