<script lang="ts">
	import '../app.css';
	import { enhance } from '$app/forms';
	import { AppBar, Toast } from '@skeletonlabs/skeleton-svelte';
	import { toaster } from '$lib/toaster';
	import type { LayoutData } from './$types';

	let { children, data }: { children: import('svelte').Snippet; data: LayoutData } = $props();
</script>

<Toast.Group {toaster}>
	{#snippet children(t)}
		<Toast
			toast={t}
			class="rounded-xl border border-white/20 p-4 shadow-xl min-w-64 {t.type === 'error' ? 'preset-filled-error-500' : t.type === 'success' ? 'preset-filled-success-500' : 'bg-surface-100-900'}"
		>
			<Toast.Title>{t.title}</Toast.Title>
		</Toast>
	{/snippet}
</Toast.Group>
<div class="flex h-full flex-col">
	<AppBar>
		<div class="flex w-full items-center justify-between">
			<a href="/" class="flex items-center gap-2">
				<img src="/logo-mark.png" alt="" class="h-8 w-8" />
				<strong class="text-xl">earmark</strong>
			</a>
			{#if data.user}
				<div class="flex items-center gap-3">
					<span class="text-surface-600-400 text-sm">{data.user.email}</span>
					<form method="POST" action="/logout" use:enhance>
						<button type="submit" class="btn btn-sm preset-tonal">Sign out</button>
					</form>
				</div>
			{/if}
		</div>
		{#if data.user}
			<div class="flex gap-2">
				<a href="/mappings" class="btn btn-sm preset-tonal">Mappings</a>
				<a href="/progress" class="btn btn-sm preset-tonal">Progress</a>
				<a href="/logs" class="btn btn-sm preset-tonal">Logs</a>
				<a href="/settings" class="btn btn-sm preset-tonal">Settings</a>
			</div>
		{/if}
	</AppBar>
	<main class="flex-1">
		{@render children()}
	</main>
</div>
