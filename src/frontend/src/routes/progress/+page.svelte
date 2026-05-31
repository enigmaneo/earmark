<script lang="ts">
	import { goto } from '$app/navigation';
	import { enhance } from '$app/forms';
	import { page } from '$app/stores';
	import Modal from '$lib/Modal.svelte';
	import type { PageData } from './$types';
	import type { SortBy, SortDir, ProgressItem } from '$lib/api';

	let { data }: { data: PageData } = $props();

	let items = $state<ProgressItem[]>([]);
	let total = $state<number>(0);
	let perPage = $state<number>(50);
	let currentPage = $state<number>(1);

	let totalPages = $derived(Math.max(1, Math.ceil(total / perPage)));

	let selectedDocument = $state<string>('');
	let sortBy = $state<SortBy>('updated_at');
	let sortDir = $state<SortDir>('desc');

	let pendingDelete = $state<ProgressItem | null>(null);
	let deleteError = $state<string | null>(null);

	const columns: { key: SortBy | null; label: string }[] = [
		{ key: 'title', label: 'Title' },
		{ key: null, label: 'Document' },
		{ key: 'percentage', label: 'Percentage' },
		{ key: 'progress', label: 'Progress' },
		{ key: 'device', label: 'Device' },
		{ key: 'is_latest', label: 'Latest' },
		{ key: 'updated_at', label: 'Updated' },
		{ key: null, label: 'ABS Sync' },
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
		return new Intl.DateTimeFormat(undefined, {
			timeZone: data.timezone,
			dateStyle: 'medium',
			timeStyle: 'short',
		}).format(new Date(ts * 1000));
	}


	$effect(() => {
		items = data.progressList.data;
		total = data.progressList.total;
		perPage = data.progressList.per_page ?? 50;
		currentPage = data.page ?? 1;
		selectedDocument = data.document ?? '';
		sortBy = data.sort_by as SortBy;
		sortDir = data.sort_dir as SortDir;
	});
</script>

<div class="container mx-auto p-6 space-y-4">
	{#if data.loadError}
		<aside class="alert preset-filled-error-500"><p>{data.loadError}</p></aside>
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
						<td class="max-w-xs truncate" title={item.title}>{item.title}</td>
						<td class="max-w-xs truncate font-mono text-xs text-surface-500" title={item.document}>{item.document}</td>
						<td>{formatPercent(item.percentage)}</td>
						<td class="max-w-xs truncate font-mono text-xs" title={item.progress}>{item.progress}</td>
						<td>{item.device}</td>
						<td>{item.is_latest ? '✓' : ''}</td>
						<td>{formatDate(item.timestamp)}</td>
						<td class="text-center">
							{#if item.abs_synced === true}
								<span title="Synced to ABS" class="cursor-default inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-600 text-white text-xs font-bold select-none">!</span>
							{:else if item.abs_synced === false}
								<span title={item.abs_sync_error ?? 'Sync failed'} class="cursor-default inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-600 text-white text-xs font-bold select-none">!</span>
							{/if}
						</td>
						<td>
							<button
								class="btn btn-sm preset-outlined-error-500"
								onclick={() => { pendingDelete = item; deleteError = null; }}
							>
								Delete
							</button>
						</td>
					</tr>
				{:else}
					<tr>
						<td colspan="9" class="text-center text-surface-500">No progress entries.</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if totalPages > 1}
		<div class="flex items-center justify-end gap-3">
			<button
				class="btn btn-sm preset-tonal"
				disabled={currentPage <= 1}
				onclick={() => navigate({ page: String(currentPage - 1) })}
			>
				Previous
			</button>
			<span class="text-surface-500 text-sm">Page {currentPage} of {totalPages}</span>
			<button
				class="btn btn-sm preset-tonal"
				disabled={currentPage >= totalPages}
				onclick={() => navigate({ page: String(currentPage + 1) })}
			>
				Next
			</button>
		</div>
	{/if}
</div>

<Modal
	open={pendingDelete !== null}
	onclose={() => { pendingDelete = null; deleteError = null; }}
	labelledby="delete-title"
>
	<h3 class="h3" id="delete-title">Delete entry?</h3>
	<p class="text-surface-600-400">
		This will permanently remove this progress entry. It cannot be undone.
	</p>
	{#if deleteError}
		<p class="text-error-500 text-sm">{deleteError}</p>
	{/if}
	<div class="flex justify-end gap-3">
		<button
			type="button"
			class="btn preset-tonal"
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
						pendingDelete = null;
						deleteError = null;
						await update();
					} else {
						deleteError = 'Failed to delete. Please try again.';
						await update();
					}
				};
			}}
		>
			<input type="hidden" name="id" value={pendingDelete?.id} />
			<button type="submit" class="btn preset-filled-error-500">Delete</button>
		</form>
	</div>
</Modal>
