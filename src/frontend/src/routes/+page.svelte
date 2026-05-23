<script lang="ts">
	import { goto } from '$app/navigation';
	import { enhance } from '$app/forms';
	import { page } from '$app/stores';
	import type { PageData } from './$types';
	import type { SortBy, SortDir, ProgressItem } from '$lib/api';

	let { data }: { data: PageData } = $props();

	let items = $state<ProgressItem[]>([]);
	let total = $state<number>(0);

	let selectedDocument = $state<string>('');
	let sortBy = $state<SortBy>('updated_at');
	let sortDir = $state<SortDir>('desc');

	let pendingDelete = $state<ProgressItem | null>(null);
	let deleteError = $state<string | null>(null);

	const columns: { key: SortBy | null; label: string }[] = [
		{ key: 'title', label: 'Title' },
		{ key: 'percentage', label: 'Percentage' },
		{ key: 'progress', label: 'Progress' },
		{ key: 'device', label: 'Device' },
		{ key: 'is_latest', label: 'Latest' },
		{ key: 'updated_at', label: 'Updated' },
		{ key: null, label: 'Actions' },
	];

	function navigate(overrides: Record<string, string>) {
		const params = new URLSearchParams($page.url.searchParams);
		for (const [k, v] of Object.entries(overrides)) {
			if (v) params.set(k, v);
			else params.delete(k);
		}
		goto(`?${params}`, { invalidateAll: true });
	}

	function handleDocumentChange(e: Event) {
		const val = (e.target as HTMLSelectElement).value;
		selectedDocument = val;
		navigate({ document: val, page: '1' });
	}

	function handleSort(key: SortBy | null) {
		if (!key) return;
		const newDir: SortDir = sortBy === key && sortDir === 'desc' ? 'asc' : 'desc';
		sortBy = key;
		sortDir = newDir;
		navigate({ sort_by: key, sort_dir: newDir, page: '1' });
	}

	function formatPercent(p: number) {
		return `${(p * 100).toFixed(1)}%`;
	}

	function formatDate(ts: number) {
		return new Date(ts * 1000).toLocaleString();
	}


	$effect(() => {
		items = data.progressList.data;
		total = data.progressList.total;
		selectedDocument = data.document ?? '';
		sortBy = data.sort_by as SortBy;
		sortDir = data.sort_dir as SortDir;
	});
</script>

<div class="container mx-auto p-6 space-y-4">
	{#if data.loadError}
		<aside class="alert variant-filled-error"><p>{data.loadError}</p></aside>
	{/if}
	<div class="flex items-center gap-4">
		<label for="doc-select" class="text-sm font-medium">Filter by title</label>
		<select
			id="doc-select"
			class="select w-72"
			value={selectedDocument}
			onchange={handleDocumentChange}
		>
			<option value="">All documents</option>
			{#each data.documents as doc}
				<option value={doc.document}>{doc.title ?? doc.document}</option>
			{/each}
		</select>
		<span class="text-surface-500 text-sm">{total} entries</span>
	</div>

	<div class="table-wrap">
		<table class="table table-hover">
			<thead>
				<tr>
					{#each columns as col}
						<th
							class={col.key ? 'cursor-pointer select-none' : ''}
							onclick={() => handleSort(col.key)}
						>
							<span class="inline-flex items-center gap-1">
								{col.label}
								{#if col.key && sortBy === col.key}
									<span>{sortDir === 'asc' ? '▲' : '▼'}</span>
								{/if}
							</span>
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each items as item (item.id)}
					<tr>
						<td class="max-w-xs truncate">{item.title ?? item.document}</td>
						<td>{formatPercent(item.percentage)}</td>
						<td class="max-w-xs truncate font-mono text-xs">{item.progress}</td>
						<td>{item.device}</td>
						<td>{item.is_latest ? '✓' : ''}</td>
						<td>{formatDate(item.timestamp)}</td>
						<td>
							<button
								class="btn btn-sm variant-ghost-error"
								onclick={() => { pendingDelete = item; deleteError = null; }}
							>
								Delete
							</button>
						</td>
					</tr>
				{:else}
					<tr>
						<td colspan="7" class="text-center text-surface-500">No progress entries.</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>

{#if pendingDelete}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		role="dialog"
		aria-modal="true"
	>
		<div class="card bg-surface-100-800 w-full max-w-md space-y-4 p-6 shadow-xl">
			<h3 class="h3">Delete entry?</h3>
			<p class="text-surface-600-400">
				This will permanently remove this progress entry. It cannot be undone.
			</p>
			{#if deleteError}
				<p class="text-error-500 text-sm">{deleteError}</p>
			{/if}
			<div class="flex justify-end gap-3">
				<button
					type="button"
					class="btn variant-soft"
					onclick={() => { pendingDelete = null; deleteError = null; }}
				>
					Cancel
				</button>
				<form
					method="POST"
					action="?/deleteRecord"
					use:enhance={() => {
						return async ({ result, update }) => {
							if (result.type === 'success' && result.data?.deleted) {
								const deletedId = result.data.deleted as number;
								items = items.filter((i) => i.id !== deletedId);
								total -= 1;
								pendingDelete = null;
								deleteError = null;
							} else {
								deleteError = 'Failed to delete. Please try again.';
								await update();
							}
						};
					}}
				>
					<input type="hidden" name="id" value={pendingDelete?.id} />
					<button type="submit" class="btn variant-filled-error">Delete</button>
				</form>
			</div>
		</div>
	</div>
{/if}
