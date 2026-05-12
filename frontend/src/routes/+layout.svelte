<script lang="ts">
	import '../app.css';
	import { AppBar } from '@skeletonlabs/skeleton-svelte';
	import type { LayoutData } from './$types';

	let { children, data }: { children: import('svelte').Snippet; data: LayoutData } = $props();
</script>

<div class="flex h-full flex-col">
	<AppBar>
		<AppBar.Lead>
			<strong class="text-xl">earmark</strong>
		</AppBar.Lead>
		{#if data.user}
			<AppBar.Trail>
				<span class="text-surface-600-400 text-sm">{data.user.email}</span>
				<a href="/logout" class="btn btn-sm variant-soft">Sign out</a>
			</AppBar.Trail>
		{/if}
	</AppBar>
	<main class="flex-1">
		{@render children()}
	</main>
</div>
