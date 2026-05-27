<script lang="ts">
	import '../app.css';
	import { AppBar, Toast } from '@skeletonlabs/skeleton-svelte';
	import { toaster } from '$lib/toaster';
	import type { LayoutData } from './$types';

	let { children, data }: { children: import('svelte').Snippet; data: LayoutData } = $props();
</script>

<Toast.Group {toaster}>
	{#snippet children(t)}
		<Toast toast={t}>
			<Toast.Title />
		</Toast>
	{/snippet}
</Toast.Group>
<div class="flex h-full flex-col">
	<AppBar>
		<div class="flex w-full items-center justify-between">
			<strong class="text-xl">earmark</strong>
			{#if data.user}
				<div class="flex items-center gap-3">
					<span class="text-surface-600-400 text-sm">{data.user.email}</span>
					<a href="/logout" class="btn btn-sm variant-soft">Sign out</a>
				</div>
			{/if}
		</div>
		{#if data.user}
			<div class="flex gap-2">
				<a href="/mappings" class="btn btn-sm variant-ghost">Mappings</a>
				<a href="/progress" class="btn btn-sm variant-ghost">Progress</a>
			</div>
		{/if}
	</AppBar>
	<main class="flex-1">
		{@render children()}
	</main>
</div>
