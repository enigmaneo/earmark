/**
 * Reveal a truncated cell's full text in a small tooltip when tapped on a touch device.
 *
 * `title=` tooltips only appear on hover, which touch devices lack. On coarse
 * pointers, a tap on an actually-truncated element shows the full text in a tooltip
 * positioned at the tap point. On fine pointers (mouse) this is a no-op so hover
 * tooltips and existing click behaviour (e.g. row navigation) are preserved.
 */

const MARGIN = 8;

let activeTip: { el: HTMLElement; cleanup: () => void } | null = null;

function dismiss() {
	if (!activeTip) return;
	activeTip.cleanup();
	activeTip.el.remove();
	activeTip = null;
}

function show(text: string, x: number, y: number) {
	dismiss();

	const el = document.createElement('div');
	el.textContent = text;
	el.className =
		'bg-surface-100-900 border-surface-300-700 pointer-events-none fixed z-50 max-w-64 ' +
		'rounded-lg border px-3 py-2 text-sm break-words shadow-xl';
	document.body.appendChild(el);

	// Measure, then clamp into the viewport (flip above the tap if it would spill off-screen).
	const rect = el.getBoundingClientRect();
	let left = x;
	let top = y + MARGIN;
	if (left + rect.width + MARGIN > window.innerWidth) {
		left = window.innerWidth - rect.width - MARGIN;
	}
	if (left < MARGIN) left = MARGIN;
	if (top + rect.height + MARGIN > window.innerHeight) {
		top = y - rect.height - MARGIN;
	}
	if (top < MARGIN) top = MARGIN;
	el.style.left = `${left}px`;
	el.style.top = `${top}px`;

	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape') dismiss();
	};
	const timer = window.setTimeout(dismiss, 4000);
	// Attach next tick so the creating tap doesn't immediately dismiss it.
	const arm = window.setTimeout(() => {
		window.addEventListener('pointerdown', dismiss, { once: true });
		window.addEventListener('scroll', dismiss, { once: true, capture: true });
		window.addEventListener('resize', dismiss, { once: true });
		window.addEventListener('keydown', onKey);
	}, 0);

	activeTip = {
		el,
		cleanup() {
			window.clearTimeout(timer);
			window.clearTimeout(arm);
			window.removeEventListener('pointerdown', dismiss);
			window.removeEventListener('scroll', dismiss, { capture: true });
			window.removeEventListener('resize', dismiss);
			window.removeEventListener('keydown', onKey);
		},
	};
}

export function revealOnTap(node: HTMLElement, text: string | null | undefined) {
	let current = text;

	function onClick(e: MouseEvent) {
		if (!current) return;
		if (!window.matchMedia('(pointer: coarse)').matches) return;
		if (node.scrollWidth <= node.clientWidth) return;
		e.stopPropagation();
		show(current, e.clientX, e.clientY);
	}

	node.addEventListener('click', onClick);

	return {
		update(text: string | null | undefined) {
			current = text;
		},
		destroy() {
			node.removeEventListener('click', onClick);
			dismiss();
		},
	};
}
