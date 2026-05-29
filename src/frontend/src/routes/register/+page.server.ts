import { fail, redirect } from '@sveltejs/kit';
import { dev } from '$app/environment';
import type { Actions } from './$types';
import { config } from '$lib/server/config';

const BACKEND = config.backendUrl;

export const actions: Actions = {
	default: async ({ request, cookies }) => {
		const data = await request.formData();
		const email = data.get('email') as string;
		const password = data.get('password') as string;
		const confirmPassword = data.get('confirm_password') as string;

		if (!email || !password || !confirmPassword) {
			return fail(400, { error: 'All fields are required' });
		}
		if (password !== confirmPassword) {
			return fail(400, { error: 'Passwords do not match' });
		}
		if (password.length < 8) {
			return fail(400, { error: 'Password must be at least 8 characters' });
		}

		let registerRes: Response;
		try {
			registerRes = await fetch(`${BACKEND}/auth/register`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email, password })
			});
		} catch {
			return fail(503, { error: 'Could not reach server' });
		}

		if (!registerRes.ok) {
			const body = await registerRes.json().catch(() => ({}));
			return fail(registerRes.status, { error: body.detail ?? 'Registration failed' });
		}

		const loginRes = await fetch(`${BACKEND}/auth/login`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ email, password })
		});

		if (!loginRes.ok) {
			redirect(302, '/login');
		}

		const { access_token } = await loginRes.json();
		cookies.set('earmark_session', access_token, {
			httpOnly: true,
			path: '/',
			maxAge: 60 * 60 * 24 * 7,
			sameSite: 'lax',
			secure: !dev
		});

		redirect(302, '/');
	}
};
