import { env } from '$env/dynamic/private';

export const config = {
	backendUrl: env.BACKEND_URL ?? 'http://localhost:8000',
	secretKey: env.SECRET_KEY ?? 'change-me-in-production',
};
