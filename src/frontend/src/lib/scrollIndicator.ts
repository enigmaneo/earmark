export function scrollIndicator(node: HTMLElement) {
	let before: HTMLSpanElement | null = null;
	let after: HTMLSpanElement | null = null;

	const scrollForward = () => {
		const remaining = node.scrollWidth - node.clientWidth - node.scrollLeft;
		node.scrollBy({ left: Math.min(remaining, node.clientWidth * 0.75), behavior: 'smooth' });
	};
	const scrollBack = () => {
		node.scrollBy({ left: -Math.min(node.scrollLeft, node.clientWidth * 0.75), behavior: 'smooth' });
	};

	const update = () => {
		const overflows = node.scrollWidth > node.clientWidth;
		const atEnd = node.scrollLeft >= node.scrollWidth - node.clientWidth - 1;
		const atStart = node.scrollLeft <= 0;

		if (overflows && !atEnd) {
			if (!after) {
				after = document.createElement('span');
				after.className = 'scroll-hint';
				after.textContent = '›';
				after.addEventListener('click', scrollForward);
				node.parentElement?.appendChild(after);
			}
		} else if (after) {
			after.remove();
			after = null;
		}

		if (overflows && !atStart) {
			if (!before) {
				before = document.createElement('span');
				before.className = 'scroll-hint';
				before.textContent = '‹';
				before.addEventListener('click', scrollBack);
				node.parentElement?.insertBefore(before, node);
			}
		} else if (before) {
			before.remove();
			before = null;
		}
	};

	node.addEventListener('scroll', update);
	update();
	const ro = new ResizeObserver(update);
	ro.observe(node);

	return {
		destroy: () => {
			ro.disconnect();
			node.removeEventListener('scroll', update);
			before?.remove();
			after?.remove();
		}
	};
}
