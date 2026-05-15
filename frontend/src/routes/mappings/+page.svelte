<script lang="ts">
	import { enhance } from '$app/forms';
	import type { AbsItemSummary, EbookFileSummary, MappingRead } from '$lib/api';
	import type { ActionData, PageData } from './$types';

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

	$effect(() => {
		mappings = data.mappings;
	});
</script>

<div class="container mx-auto max-w-4xl space-y-8 p-6">
	<h1 class="h2">ABS–Ebook Mappings</h1>

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
					<th>Ebook File</th>
					<th>KOSync Hash</th>
					<th>Created</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each mappings as m (m.id)}
					<tr>
						<td class="max-w-xs truncate">{m.abs_title}</td>
						<td class="max-w-xs truncate">{m.abs_author ?? '—'}</td>
						<td class="max-w-xs truncate font-mono text-sm">{m.ebook_filename}</td>
						<td class="font-mono text-xs">
							{#if m.kosync_document}
								<a href="/?document={m.kosync_document}" class="anchor">{m.kosync_document.slice(0, 8)}…</a>
							{:else}
								—
							{/if}
						</td>
						<td>{formatDate(m.created_at)}</td>
						<td>
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
