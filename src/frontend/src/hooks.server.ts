import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { jwtVerify } from 'jose';
import { config } from '$lib/server/config';

const PUBLIC_ROUTES = ['/login', '/register'];
let secret: Uint8Array | null = null;

function getSecret(): Uint8Array {
	if (!secret) secret = new TextEncoder().encode(config.secretKey);
	return secret;
}

export const handle: Handle = async ({ event, resolve }) => {
	const token = event.cookies.get('earmark_session');

	if (token) {
		try {
			const { payload } = await jwtVerify(token, getSecret(), { algorithms: ['HS256'] });
			const id = Number(payload.sub);
			const email = payload.email as string;
			if (id && email) {
				event.locals.user = { id, email };
			} else {
				event.locals.user = null;
			}
		} catch (err) {
			console.error('JWT verification failed:', err);
			event.cookies.delete('earmark_session', { path: '/' });
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
