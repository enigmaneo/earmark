<script lang="ts">
	import '../app.css';
	import { AppBar } from '@skeletonlabs/skeleton-svelte';

	let { children } = $props();
</script>

<div class="flex h-full flex-col">
	<AppBar>
		<AppBar.Lead>
			<strong class="text-xl">earmark</strong>
		</AppBar.Lead>
	</AppBar>
	<main class="flex-1">
		{@render children()}
	</main>
</div>
