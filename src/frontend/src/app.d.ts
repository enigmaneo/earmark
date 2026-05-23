declare global {
	namespace App {
		interface Locals {
			user: { id: number; email: string } | null;
		}
	}
}

export {};
