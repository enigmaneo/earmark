<script lang="ts">
	import { untrack } from 'svelte';
	import { enhance } from '$app/forms';
	import { goto } from '$app/navigation';
	import type { AbsItemSummary, EbookFileSummary, MappingRead } from '$lib/api';
	import type { ActionData, PageData } from './$types';
	import { toaster } from '$lib/toaster';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let mappings = $state<MappingRead[]>([]);
	let selectedAbsItemId = $state<string>('');
	let selectedEbookPath = $state<string>('');
	let showSyncConfirmModal = $state(false);
	let addFormEl = $state<HTMLFormElement | null>(null);

	let selectedAbs = $derived(
		(data.absItems as AbsItemSummary[]).find((a) => a.abs_item_id === selectedAbsItemId) ?? null
	);

	let usedAbsIds = $derived(new Set(mappings.map((m) => m.abs_item_id)));
	let usedEbookPaths = $derived(new Set(mappings.map((m) => m.ebook_path)));

	let availableAbsItems = $derived(
		(data.absItems as AbsItemSummary[]).filter((a) => !usedAbsIds.has(a.abs_item_id))
	);
	let availableEbookFiles = $derived(
		(data.ebookFiles as EbookFileSummary[]).filter((e) => !usedEbookPaths.has(e.path))
	);

	function ebookLabel(e: EbookFileSummary): string {
		if (e.title) return e.author ? `"${e.title}" — ${e.author}` : e.title;
		return e.filename;
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString();
	}

	const ACTIVE_STATUSES = new Set([
		'pending',
		'fetching_audio',
		'fetching_ebook',
		'parsing_epub',
		'aligning',
		'assembling'
	]);

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function pollMappings() {
		const res = await fetch('/mappings/poll');
		if (!res.ok) return;
		const updated = (await res.json()) as MappingRead[];
		for (const m of updated) {
			const prev = mappings.find((p) => p.id === m.id);
			if (m.sync_status === 'failed' && prev && ACTIVE_STATUSES.has(prev.sync_status ?? '')) {
				toaster.create({ type: 'error', title: `Alignment failed for "${m.abs_title}"` });
			}
		}
		mappings = updated;
	}

	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(async () => {
			if (!mappings.some((m) => m.sync_status && ACTIVE_STATUSES.has(m.sync_status))) {
				clearInterval(pollTimer!);
				pollTimer = null;
				return;
			}
			await pollMappings();
		}, 2000);
	}

	let anyActive = $derived(
		mappings.some((m) => m.sync_status && ACTIVE_STATUSES.has(m.sync_status))
	);

	$effect(() => {
		const updated = data.mappings;
		untrack(() => {
			for (const m of updated) {
				const prev = mappings.find((p) => p.id === m.id);
				if (m.sync_status === 'failed' && prev && ACTIVE_STATUSES.has(prev.sync_status ?? '')) {
					toaster.create({ type: 'error', title: `Alignment failed for "${m.abs_title}"` });
				}
			}
			mappings = updated;
			if (updated.some((m) => m.sync_status && ACTIVE_STATUSES.has(m.sync_status))) {
				startPolling();
			}
		});
		return () => {
			if (pollTimer) {
				clearInterval(pollTimer);
				pollTimer = null;
			}
		};
	});

	function handleRowClick(m: MappingRead) {
		if (m.kosync_document) {
			goto(`/?document=${m.kosync_document}`);
		}
	}
</script>

<div class="container mx-auto max-w-5xl space-y-8 p-6">
	<h1 class="h2">ABS–Ebook Mappings</h1>

	{#if data.loadError}
		<aside class="alert variant-filled-error"><p>{data.loadError}</p></aside>
	{/if}

	<div class="card bg-surface-100-900 space-y-4 p-6">
		<h2 class="h3">Add Mapping</h2>

		{#if form?.error}
			<aside class="alert variant-filled-error">
				<p>{form.error}</p>
			</aside>
		{/if}

		<form
			bind:this={addFormEl}
			method="POST"
			action="?/createMapping"
			use:enhance={() => {
				return async ({ result, update }) => {
					showSyncConfirmModal = false;
					if (result.type === 'success' && result.data?.created) {
						mappings = [result.data.created as MappingRead, ...mappings];
						selectedAbsItemId = '';
						selectedEbookPath = '';
						startPolling();
						toaster.create({ type: 'success', title: 'Mapping added — alignment started' });
					} else {
						await update();
					}
				};
			}}
			class="grid grid-cols-1 gap-4 sm:grid-cols-2"
		>
			<input type="hidden" name="abs_item_id" value={selectedAbsItemId} />
			<input type="hidden" name="abs_title" value={selectedAbs?.title ?? ''} />
			<input type="hidden" name="abs_author" value={selectedAbs?.author ?? ''} />
			<input type="hidden" name="ebook_path" value={selectedEbookPath} />

			<label class="label">
				<span>ABS Audiobook</span>
				{#if availableAbsItems.length === 0}
					<select class="select" disabled>
						<option>No audiobooks found</option>
					</select>
				{:else}
					<select class="select" bind:value={selectedAbsItemId}>
						<option value="">Choose audiobook…</option>
						{#each availableAbsItems as abs (abs.abs_item_id)}
							<option value={abs.abs_item_id}>
								{abs.title}{abs.author ? ` — ${abs.author}` : ''}
							</option>
						{/each}
					</select>
				{/if}
			</label>

			<label class="label">
				<span>Ebook</span>
				{#if availableEbookFiles.length === 0}
					<select class="select" disabled>
						<option>No ebooks found — check EBOOK_LOCAL_ROOT</option>
					</select>
				{:else}
					<select class="select" bind:value={selectedEbookPath}>
						<option value="">Choose ebook…</option>
						{#each availableEbookFiles as ebook (ebook.path)}
							<option value={ebook.path}>{ebookLabel(ebook)}</option>
						{/each}
					</select>
				{/if}
			</label>

			<div class="flex justify-end sm:col-span-2">
				<button
					type="button"
					class="btn variant-filled-primary"
					disabled={!selectedAbsItemId || !selectedEbookPath}
					onclick={() => (showSyncConfirmModal = true)}
				>
					Add
				</button>
			</div>
		</form>
	</div>

	<div class="table-wrap">
		<table class="table table-hover">
			<thead>
				<tr>
					<th>Audiobook</th>
					<th>Author</th>
					<th>Mapping</th>
					<th>Progress</th>
					<th>Created</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each mappings as m (m.id)}
					<tr
						class="hover:bg-surface-200-800 transition-colors {m.kosync_document ? 'cursor-pointer' : ''}"
						onclick={() => handleRowClick(m)}
					>
						<td class="max-w-xs truncate">{m.abs_title}</td>
						<td class="max-w-xs truncate">{m.abs_author ?? '—'}</td>
						<td>
							{#if ACTIVE_STATUSES.has(m.sync_status ?? '')}
								<span class="text-xs tabular-nums">{m.sync_progress ?? 0}%</span>
							{:else if m.sync_status === 'failed'}
								<span class="badge variant-filled-error text-xs" title={m.sync_error ?? undefined}>Failed</span>
							{:else if m.cache_intact === true || m.sync_status === 'complete'}
								<span class="badge variant-filled-success text-xs">Mapped</span>
							{:else}
								<span class="badge variant-filled-warning text-xs">Unmapped</span>
							{/if}
						</td>
						<td class="min-w-[140px]">
							{#if m.reading_percentage != null}
								<div class="flex items-center gap-2">
									<div class="bg-surface-300 h-2 flex-1 overflow-hidden rounded-full">
										<div
											class="bg-primary-500 h-2 rounded-full transition-all duration-500"
											style="width: {m.reading_percentage * 100}%"
										></div>
									</div>
									<span class="w-8 text-right text-xs tabular-nums">{Math.round(m.reading_percentage * 100)}%</span>
								</div>
							{:else}
								<span class="text-surface-400 text-xs">—</span>
							{/if}
						</td>
						<td>{formatDate(m.created_at)}</td>
						<td class="flex gap-2" onclick={(e) => e.stopPropagation()}>
							<form
								method="POST"
								action="?/syncMapping"
								use:enhance={() => {
									return async ({ result, update }) => {
										if (result.type === 'success' && result.data?.synced) {
											const synced = result.data.synced as MappingRead;
											mappings = mappings.map((x) => (x.id === synced.id ? synced : x));
											startPolling();
											toaster.create({ type: 'success', title: 'Sync started' });
										} else {
											const msg = result.type === 'failure' ? (result.data?.error as string | undefined) : undefined;
											toaster.create({ type: 'error', title: msg ?? 'Sync failed' });
											await update();
										}
									};
								}}
							>
								<input type="hidden" name="id" value={m.id} />
								<button type="submit" class="btn btn-sm variant-ghost-primary" disabled={anyActive}>
									{m.sync_status === 'complete' || m.sync_status === 'failed' ? 'Re-sync' : 'Sync'}
								</button>
							</form>
							<form
								method="POST"
								action="?/deleteMapping"
								use:enhance={() => {
									return async ({ result, update }) => {
										if (result.type === 'success' && result.data?.deleted != null) {
											mappings = mappings.filter(
												(x) => x.id !== (result.data?.deleted as number)
											);
										} else {
											const msg = result.type === 'failure' ? (result.data?.error as string | undefined) : undefined;
											toaster.create({ type: 'error', title: msg ?? 'Delete failed' });
											await update();
										}
									};
								}}
							>
								<input type="hidden" name="id" value={m.id} />
								<button type="submit" class="btn btn-sm variant-ghost-error">Remove</button>
							</form>
						</td>
					</tr>
				{:else}
					<tr>
						<td colspan="6" class="text-center text-surface-500">
							No mappings yet. Add one above.
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>

{#if showSyncConfirmModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		role="dialog"
		aria-modal="true"
		aria-labelledby="sync-confirm-title"
	>
		<div class="card bg-surface-100-900 w-full max-w-md space-y-6 p-6 shadow-xl">
			<h2 class="h3" id="sync-confirm-title">Begin Alignment</h2>
			<p class="text-surface-700-300 text-sm leading-relaxed">
				Adding this mapping will immediately begin the alignment process, which analyzes and
				synchronizes your audiobook and ebook. This process may take several minutes depending on
				the length of the audiobook. Please ensure you have a stable connection before proceeding.
			</p>
			<p class="text-surface-700-300 text-sm">Would you like to proceed?</p>
			<div class="flex justify-end gap-3">
				<button
					type="button"
					class="btn variant-ghost"
					onclick={() => (showSyncConfirmModal = false)}
				>
					Cancel
				</button>
				<button
					type="button"
					class="btn variant-filled-primary"
					onclick={() => addFormEl?.requestSubmit()}
				>
					Proceed
				</button>
			</div>
		</div>
	</div>
{/if}
