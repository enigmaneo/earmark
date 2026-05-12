<script lang="ts">
	import { enhance } from '$app/forms';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<div class="flex min-h-full items-center justify-center p-8">
	<div class="card bg-surface-100-900 w-full max-w-sm space-y-6 p-8">
		<div>
			<h1 class="h2">Sign in</h1>
			<p class="text-surface-600-400 mt-1 text-sm">to your earmark account</p>
		</div>

		{#if form?.error}
			<aside class="alert variant-filled-error">
				<p>{form.error}</p>
			</aside>
		{/if}

		<form method="POST" use:enhance class="space-y-4">
			<label class="label">
				<span>Email</span>
				<input
					class="input"
					type="email"
					name="email"
					placeholder="you@example.com"
					autocomplete="email"
					required
				/>
			</label>

			<label class="label">
				<span>Password</span>
				<input
					class="input"
					type="password"
					name="password"
					placeholder="••••••••"
					autocomplete="current-password"
					required
				/>
			</label>

			<button type="submit" class="btn variant-filled-primary w-full">Sign in</button>
		</form>

		<p class="text-surface-600-400 text-center text-sm">
			Don't have an account?
			<a href="/register" class="anchor">Register</a>
		</p>
	</div>
</div>
