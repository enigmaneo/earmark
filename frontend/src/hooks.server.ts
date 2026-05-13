import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';

const PUBLIC_ROUTES = ['/login', '/register'];
const BACKEND = 'http://localhost:8000';

export const handle: Handle = async ({ event, resolve }) => {
	const token = event.cookies.get('earmark_session');

	if (token) {
		try {
			const res = await fetch(`${BACKEND}/auth/me`, {
				headers: { Authorization: `Bearer ${token}` }
			});
			if (res.ok) {
				const user = await res.json();
				event.locals.user = { id: user.id, email: user.email };
			} else {
				event.cookies.delete('earmark_session', { path: '/' });
				event.locals.user = null;
			}
		} catch {
			event.locals.user = null;
		}
	} else {
		event.locals.user = null;
	}

	const isPublic = PUBLIC_ROUTES.some((r) => event.url.pathname.startsWith(r));
	if (!event.locals.user && !isPublic) {
		redirect(302, '/login');
	}

	return resolve(event);
};
