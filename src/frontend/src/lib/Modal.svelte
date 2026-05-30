<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		open = false,
		onclose,
		labelledby,
		children
	}: {
		open?: boolean;
		onclose: () => void;
		labelledby?: string;
		children: Snippet;
	} = $props();

	let dialogEl = $state<HTMLDivElement | null>(null);
	let previouslyFocused: HTMLElement | null = null;

	function focusable(): HTMLElement[] {
		if (!dialogEl) return [];
		return Array.from(
			dialogEl.querySelectorAll<HTMLElement>(
				'a[href], button:not([disabled]), textarea, input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
			)
		);
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
			return;
		}
		if (e.key !== 'Tab') return;
		const items = focusable();
		if (items.length === 0) {
			e.preventDefault();
			return;
		}
		const first = items[0];
		const last = items[items.length - 1];
		if (e.shiftKey && document.activeElement === first) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && document.activeElement === last) {
			e.preventDefault();
			first.focus();
		}
	}

	$effect(() => {
		if (!open) return;
		previouslyFocused = document.activeElement as HTMLElement | null;
		// Move focus into the dialog once it has rendered.
		queueMicrotask(() => (focusable()[0] ?? dialogEl)?.focus());
		return () => previouslyFocused?.focus?.();
	});
</script>

{#if open}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/50">
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			bind:this={dialogEl}
			class="card bg-surface-100-900 w-full max-w-md space-y-4 p-6 shadow-xl"
			role="dialog"
			aria-modal="true"
			aria-labelledby={labelledby}
			tabindex="-1"
			onkeydown={onKeydown}
		>
			{@render children()}
		</div>
	</div>
{/if}
