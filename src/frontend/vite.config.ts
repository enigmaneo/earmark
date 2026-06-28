import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit(),
		SvelteKitPWA({
			registerType: 'autoUpdate',
			// Keep the service worker out of `npm run dev` to avoid caching headaches.
			devOptions: { enabled: false },
			manifest: {
				name: 'earmark',
				short_name: 'earmark',
				description: 'Sync your Audiobookshelf and KOReader reading progress.',
				start_url: '/',
				display: 'standalone',
				background_color: '#ffffff',
				theme_color: '#0f0f0f',
				icons: [
					{ src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png' },
					{ src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png' },
					{
						src: '/pwa-maskable-512x512.png',
						sizes: '512x512',
						type: 'image/png',
						purpose: 'maskable',
					},
				],
			},
			workbox: {
				// Precache the built app shell so the UI loads offline. API/sync data is
				// deliberately NOT cached here — those requests always hit the network so
				// reading progress is never stale.
				globPatterns: ['**/*.{js,css,html,png,svg,ico,woff,woff2}'],
				navigateFallback: '/',
			},
		}),
	],
	envDir: '..',
	server: {
		proxy: {
			'/api': {
				target: 'http://localhost:8000',
				rewrite: (path) => path.replace(/^\/api/, ''),
			},
		},
	},
});
