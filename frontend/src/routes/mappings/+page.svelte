<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidateAll } from '$app/navigation';
	import type { AbsItemSummary, EbookFileSummary, MappingRead } from '$lib/api';
	import type { ActionData, PageData } from './$types';
	import { toaster } from '$lib/toaster';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let mappings = $state<MappingRead[]>([]);
	let selectedAbsItemId = $state<string>('');
	let selectedEbookPath = $state<string>('');

	let selectedAbs = $derived(
		(data.absItems as AbsItemSummary[]).find((a) => a.abs_item_id === selectedAbsItemId) ?? null
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

	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(async () => {
			if (!mappings.some((m) => m.sync_status && ACTIVE_STATUSES.has(m.sync_status))) {
				clearInterval(pollTimer!);
				pollTimer = null;
				return;
			}
			await invalidateAll();
		}, 2000);
	}

	let anyActive = $derived(
		mappings.some((m) => m.sync_status && ACTIVE_STATUSES.has(m.sync_status))
	);

	$effect(() => {
		const updated = data.mappings;
		mappings = updated;
		if (updated.some((m) => m.sync_status && ACTIVE_STATUSES.has(m.sync_status))) {
			startPolling();
		}
		return () => {
			if (pollTimer) {
				clearInterval(pollTimer);
				pollTimer = null;
			}
		};
	});
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
			method="POST"
			action="?/createMapping"
			use:enhance={() => {
				return async ({ result, update }) => {
					if (result.type === 'success' && result.data?.created) {
						mappings = [result.data.created as MappingRead, ...mappings];
						selectedAbsItemId = '';
						selectedEbookPath = '';
						toaster.create({ type: 'success', title: 'Mapping added' });
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
				{#if (data.absItems as AbsItemSummary[]).length === 0}
					<select class="select" disabled>
						<option>No audiobooks found</option>
					</select>
				{:else}
					<select class="select" bind:value={selectedAbsItemId}>
						<option value="">Choose audiobook…</option>
						{#each data.absItems as abs (abs.abs_item_id)}
							<option value={abs.abs_item_id}>
								{abs.title}{abs.author ? ` — ${abs.author}` : ''}
							</option>
						{/each}
					</select>
				{/if}
			</label>

			<label class="label">
				<span>Ebook</span>
				{#if (data.ebookFiles as EbookFileSummary[]).length === 0}
					<select class="select" disabled>
						<option>No ebooks found — check EBOOK_LOCAL_ROOT</option>
					</select>
				{:else}
					<select class="select" bind:value={selectedEbookPath}>
						<option value="">Choose ebook…</option>
						{#each data.ebookFiles as ebook (ebook.path)}
							<option value={ebook.path}>{ebookLabel(ebook)}</option>
						{/each}
					</select>
				{/if}
			</label>

			<div class="flex justify-end sm:col-span-2">
				<button
					type="submit"
					class="btn variant-filled-primary"
					disabled={!selectedAbsItemId || !selectedEbookPath}
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
					<th>KOSync Hash</th>
					<th>Cache</th>
					<th>Progress</th>
					<th>Created</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each mappings as m (m.id)}
					<tr>
						<td class="max-w-xs truncate">{m.abs_title}</td>
						<td class="max-w-xs truncate">{m.abs_author ?? '—'}</td>
						<td class="font-mono text-xs">
							{#if m.kosync_document}
								<a href="/?document={m.kosync_document}" class="anchor">{m.kosync_document.slice(0, 8)}…</a>
							{:else}
								—
							{/if}
						</td>
						<td>
							{#if m.cache_intact === true}
								<span class="badge variant-filled-success text-xs">Cached</span>
							{:else if m.cache_intact === false}
								<span class="badge variant-filled-warning text-xs">Stale</span>
							{:else}
								<span class="text-surface-400 text-xs">—</span>
							{/if}
						</td>
						<td class="min-w-[140px]">
							{#if m.sync_progress != null}
								<div class="flex items-center gap-2">
									<div class="bg-surface-300 h-2 flex-1 overflow-hidden rounded-full">
										<div
											class="bg-primary-500 h-2 rounded-full transition-all duration-500"
											style="width: {m.sync_progress}%"
										></div>
									</div>
									<span class="w-8 text-right text-xs tabular-nums">{m.sync_progress}%</span>
								</div>
							{:else}
								<span class="text-surface-400 text-xs">—</span>
							{/if}
						</td>
						<td>{formatDate(m.created_at)}</td>
						<td class="flex gap-2">
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
						<td colspan="8" class="text-center text-surface-500">
							No mappings yet. Add one above.
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
