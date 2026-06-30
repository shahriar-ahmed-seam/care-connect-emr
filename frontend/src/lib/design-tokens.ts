export const colors = {
  brand500: "#0d6e74",
  brand600: "#0b585d",
  brand700: "#094649",
  surface: "#ffffff",
  surfaceMuted: "#f4f7f8",
  ink: "#1f2933",
  inkMuted: "#46535e",
  inkSubtle: "#5f6b76",
  danger: "#b42318",
  success: "#0f7b52",
} as const;

export interface ColorPair {
  readonly name: string;
  readonly foreground: string;
  readonly background: string;
}

export const textColorPairs: ReadonlyArray<ColorPair> = [
  { name: "ink-on-surface", foreground: colors.ink, background: colors.surface },
  { name: "ink-on-muted", foreground: colors.ink, background: colors.surfaceMuted },
  { name: "ink-muted-on-surface", foreground: colors.inkMuted, background: colors.surface },
  { name: "ink-subtle-on-surface", foreground: colors.inkSubtle, background: colors.surface },
  { name: "white-on-brand", foreground: colors.surface, background: colors.brand500 },
  { name: "white-on-brand600", foreground: colors.surface, background: colors.brand600 },
  { name: "brand-on-surface", foreground: colors.brand600, background: colors.surface },
  { name: "danger-on-surface", foreground: colors.danger, background: colors.surface },
  { name: "success-on-surface", foreground: colors.success, background: colors.surface },
];

export function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return [r, g, b];
}

export function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(foreground: string, background: string): number {
  const l1 = relativeLuminance(foreground);
  const l2 = relativeLuminance(background);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}
