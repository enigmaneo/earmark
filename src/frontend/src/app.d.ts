/// <reference types="vite-plugin-pwa/info" />
/// <reference types="vite-plugin-pwa/client" />

declare global {
	namespace App {
		interface Locals {
			user: { id: number; email: string } | null;
		}
	}
}

export {};
