# Frontend Design Principles

## Theming

All pages must be fully themeable. Use Skeleton UI's built-in theme system as the single source of truth for colors, fonts, and design tokens. Never hardcode color values, font families, or font sizes — always reference Skeleton UI theme tokens or CSS custom properties derived from them.

- Define and switch themes via Skeleton UI's theme configuration
- Extend or override theme tokens in one place; do not scatter overrides across component styles

## Skeleton UI Components

Use Skeleton UI components wherever the library provides a suitable solution. Do not build custom equivalents for things Skeleton UI already handles (buttons, modals, cards, toasts, navigation, etc.).

- Reach for the Skeleton UI docs before writing a new component
- When a Skeleton UI component almost fits, prefer customizing it through its props and theme tokens over replacing it

## Systematic Design

Use a consistent spacing scale and reference design tokens — never hardcode pixel values or arbitrary numbers.

- All spacing (margin, padding, gap) must come from the Tailwind spacing scale or a CSS custom property
- No magic numbers: if a value isn't in the scale, question whether it belongs
- Keep layout concerns in layout components, not in leaf components

## Modern Layout

Use Flexbox and CSS Grid as the primary layout tools. Follow a mobile-first responsive workflow.

- Write base styles for the smallest viewport first, then layer breakpoints upward
- Prefer CSS Grid for two-dimensional layouts; prefer Flexbox for one-dimensional alignment
- Avoid absolute positioning for layout; reserve it for overlays and decorative elements

## Semantic HTML & Visual Hierarchy

Use semantic HTML elements and maintain a clear, logical heading structure on every page.

- Use landmark elements (`<header>`, `<nav>`, `<main>`, `<footer>`, `<aside>`, `<section>`) to structure pages
- Heading levels (`h1`–`h6`) must reflect document hierarchy, not visual sizing — style headings with CSS, not by choosing a lower heading level
- Interactive elements must be keyboard-accessible and carry appropriate ARIA labels when the visible label is insufficient
- Prefer `<button>` for actions and `<a>` for navigation; do not make non-interactive elements clickable
