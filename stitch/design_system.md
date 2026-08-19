---
name: R2Sync Pro Dark
colors:
  surface: '#111418'
  surface-dim: '#111418'
  surface-bright: '#36393E'
  surface-container-lowest: '#0b0e12'
  surface-container-low: '#191c20'
  surface-container: '#1D2024'
  surface-container-high: '#272a2e'
  surface-container-highest: '#323539'
  on-surface: '#e1e2e8'
  on-surface-variant: '#A58C7D'
  inverse-surface: '#e1e2e8'
  inverse-on-surface: '#2e3135'
  outline: '#a58c7d'
  outline-variant: '#564336'
  surface-tint: '#ffb786'
  primary: '#ffb786'
  on-primary: '#502400'
  primary-container: '#f6821f'
  on-primary-container: '#5b2a00'
  inverse-primary: '#964900'
  secondary: '#c4c6cb'
  on-secondary: '#2e3135'
  secondary-container: '#494c50'
  on-secondary-container: '#babcc1'
  tertiary: '#4ae176'
  on-tertiary: '#003915'
  tertiary-container: '#02ba55'
  on-tertiary-container: '#004219'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdcc6'
  primary-fixed-dim: '#ffb786'
  on-primary-fixed: '#311300'
  on-primary-fixed-variant: '#723600'
  secondary-fixed: '#e1e2e8'
  secondary-fixed-dim: '#c4c6cb'
  on-secondary-fixed: '#191c20'
  on-secondary-fixed-variant: '#44474b'
  tertiary-fixed: '#6bff8f'
  tertiary-fixed-dim: '#4ae176'
  on-tertiary-fixed: '#002109'
  on-tertiary-fixed-variant: '#005321'
  background: '#111418'
  on-background: '#e1e2e8'
  surface-variant: '#323539'
  orange-gradient-end: '#FFB786'
typography:
  metric:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  page-title:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  section-title:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  caption:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 24px
  element-gap: 12px
  list-item-gap: 8px
  margin-sm: 16px
  margin-md: 24px
  sidebar-width: 260px
---

## Brand & Style

The design system is engineered for a high-performance, local-first data utility. The aesthetic is a fusion of **Corporate Modern** and **Minimalism**, optimized for dark environments where technical precision and focus are paramount.

The core personality is **Quiet, Native, and Premium**. It avoids decorative flourishes, relying instead on structural integrity, 1px precision borders, and a sophisticated layering system. The emotional response should be one of absolute stability and trust—the user should feel their data is managed by a tool that is both powerful and meticulously organized. The introduction of the vibrant orange accent provides a warm, energetic contrast to the professional, near-black interface, signaling activity and synchronization.

## Colors

The color palette is built on a "Deep Space" foundation of near-black neutrals, allowing the new **Vibrant Orange (#F6821F)** brand color to serve as a high-visibility beacon for interactive states and primary actions.

- **Surface Layering:** Depth is created through luminance steps. The base background is the darkest, with containers becoming lighter as they rise in hierarchy.
- **Brand Orange:** Used for primary buttons, active toggle states, and progress indicators. For decorative elements or complex states, a subtle gradient from `#F6821F` to `#FFB786` can be used to reflect the logo's depth.
- **Success & Status:** The tertiary green (`#4AE176`) is calibrated for high legibility against dark surfaces, used exclusively for "Completed" or "Healthy" states.
- **Borders & Outlines:** Use `on-surface-variant` at low opacity for non-interactive borders to maintain the minimal, technical feel.

## Typography

**Inter** is the primary typeface, chosen for its exceptional legibility in technical, data-heavy interfaces. Its neutral character supports the professional "utility" feel of the system.

- **Information Density:** The scale is condensed for desktop efficiency. 13px is the standard size for body text and list items.
- **Data Emphasis:** For transfer speeds and file counts, use the `metric` style. This provides immediate visual hierarchy in dashboard views.
- **Native Fallback:** If Inter is unavailable, the system should fall back to Segoe UI Variable to maintain a native Windows 11 appearance.

## Layout & Spacing

This design system uses a **Fixed-Fluid hybrid** model. A fixed-width sidebar provides global navigation and persistent sync status, while the main content area expands to fill the remaining viewport.

- **Baseline Grid:** All spacing is derived from a 4px unit. Use 8px for internal component spacing and 12px-16px for logical grouping.
- **Density:** The layout is "Efficient." While margins are clear, the system avoids excessive whitespace to keep as much data visible as possible without scrolling.
- **Alignment:** Technical logs, file lists, and data tables must be strictly left-aligned to a consistent vertical axis to facilitate rapid scanning.

## Elevation & Depth

This design system utilizes **Tonal Layering** rather than traditional drop shadows to define hierarchy.

- **Low-Contrast Outlines:** Every container and interactive surface uses a 1px border. This creates a "blueprint" aesthetic that feels precise and technical.
- **Interaction Depth:** Hover states are indicated by a luminance shift (moving from `surface-container` to `surface-bright`) rather than an increase in shadow depth.
- **Shadows:** Restricted to temporary overlays like context menus or tooltips. These use a tight, dark ambient shadow (`0 4px 12px rgba(0, 0, 0, 0.5)`) to separate the floating element from the content below.

## Shapes

The shape language is structured and professional.

- **Standard UI Elements:** Buttons, inputs, and cards use 8px (`rounded-md`) to provide a modern but disciplined feel.
- **Outer Shells:** Main application panels or large modal windows use 16px (`rounded-xl`) to define the primary architecture of the software.
- **Iconography:** Icons should follow a 2px stroke weight to match the visual weight of the Inter typeface and the 1px UI borders.

## Components

- **Buttons:**
  - **Primary:** Solid `#F6821F` fill with black text (for maximum contrast). 8px radius.
  - **Ghost/Outline:** 1px border using `on-surface-variant` with brand-colored text on hover.
- **Input Fields:** Use `surface-container-high` as the background with a 1px border. The focus state uses a 2px brand orange border and a subtle glow.
- **Sync Status Cards:** The centerpiece of the UI. Features a 1px border and a thin 4px progress bar at the very bottom. Status icons use either brand orange (active) or success green (done).
- **Data Tables:** High-density 40px row height. Use subtle horizontal dividers only; avoid vertical lines to maintain a clean, modern look.
- **Activity Log:** Uses a monospaced font (JetBrains Mono) for the raw log output, while metadata (timestamps, levels) remains in Inter.
