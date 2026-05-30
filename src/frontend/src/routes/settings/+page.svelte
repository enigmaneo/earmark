<script lang="ts">
	import { enhance } from '$app/forms';
	import type { AppSetting } from '$lib/api';
	import type { ActionData, PageData } from './$types';
	import { toaster } from '$lib/toaster';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const timezones = Intl.supportedValuesOf('timeZone');

	const SECTIONS: { title: string; keys: string[] }[] = [
		{
			title: 'Audiobookshelf',
			keys: ['audiobookshelf_url', 'audiobookshelf_api_key'],
		},
		{
			title: 'Calibre Web',
			keys: ['cwa_url', 'cwa_username', 'cwa_password'],
		},
		{
			title: 'Application',
			keys: ['timezone', 'sync_interval_seconds', 'sync_abs_idle_seconds'],
		},
	];

	let settingsByKey = $derived(
		Object.fromEntries((data.settings as AppSetting[]).map((s) => [s.key, s]))
	);

	$effect(() => {
		if (form?.success) {
			toaster.create({ type: 'success', title: 'Setting saved' });
		} else if (form?.cleared) {
			toaster.create({ type: 'success', title: 'Setting cleared' });
		} else if (form?.error) {
			toaster.create({ type: 'error', title: form.error });
		}
	});
</script>

<div class="container mx-auto max-w-3xl space-y-8 p-6">
	<h1 class="h2">Settings</h1>

	{#if data.loadError}
		<aside class="alert preset-filled-error-500"><p>{data.loadError}</p></aside>
	{/if}

	{#each SECTIONS as section}
		{@const sectionSettings = section.keys.map((k) => settingsByKey[k]).filter(Boolean)}
		{#if sectionSettings.length}
			<div class="card bg-surface-100-900 space-y-6 p-6">
				<h2 class="h3">{section.title}</h2>

				{#each sectionSettings as setting (setting.key)}
					<div class="space-y-2">
						<div class="flex items-center gap-2">
							<label class="font-medium" for="input-{setting.key}">{setting.label}</label>
							{#if setting.is_secret && setting.has_db_value}
								<span class="badge preset-filled-success-500 text-xs">Currently set</span>
							{/if}
						</div>
						<p class="text-surface-600-400 text-sm">{setting.description}</p>

						<div class="flex gap-2">
							<form
								method="POST"
								action="?/update"
								class="flex flex-1 gap-2"
								use:enhance
							>
								<input type="hidden" name="key" value={setting.key} />
								{#if setting.value_type === 'timezone'}
									<select
										id="input-{setting.key}"
										name="value"
										value={setting.display_value}
										class="select flex-1"
									>
										{#if setting.display_value && !timezones.includes(setting.display_value)}
											<option value={setting.display_value}>{setting.display_value}</option>
										{/if}
										{#each timezones as tz}
											<option value={tz}>{tz}</option>
										{/each}
									</select>
								{:else if setting.value_type === 'int'}
									<input
										id="input-{setting.key}"
										type="number"
										min="1"
										step="1"
										name="value"
										value={setting.display_value}
										class="input flex-1"
									/>
								{:else}
									<input
										id="input-{setting.key}"
										type={setting.is_secret ? 'password' : 'text'}
										name="value"
										value={setting.is_secret ? '' : setting.display_value}
										placeholder={setting.is_secret ? '••••••••' : ''}
										autocomplete="off"
										class="input flex-1"
									/>
								{/if}
								<button type="submit" class="btn preset-tonal">Save</button>
							</form>

							{#if setting.has_db_value}
								<form method="POST" action="?/clear" use:enhance>
									<input type="hidden" name="key" value={setting.key} />
									<button type="submit" class="btn preset-tonal-error">Clear</button>
								</form>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/each}
</div>
