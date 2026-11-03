import { expect, test } from '@playwright/test';

test('narrow navigation remains visible and keyboard focus has sufficient contrast', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/');
  await page.getByText('Tools & examples', { exact: true }).click();
  const tabs = page.getByRole('navigation', { name: 'Workspace' }).getByRole('link');
  for (const tab of await tabs.all()) {
    const bounds = await tab.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
  }
  await tabs.first().focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  const active = page.getByRole('link', { name: 'Live voice', exact: true });
  await expect(active).toBeFocused();
  await expect(active).toHaveAttribute('aria-current', 'page');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  const contrasts = await page.evaluate(() => {
    const luminance = (color: string) => {
      const sample = document.createElement('span');
      sample.style.color = color;
      document.body.append(sample);
      const resolved = getComputedStyle(sample).color;
      sample.remove();
      const pixel = resolved.match(/[\d.]+/g)!.map(Number);
      return [pixel[0]!, pixel[1]!, pixel[2]!]
        .map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        })
        .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!, 0);
    };
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)];
      return (Math.max(...values) + 0.05) / (Math.min(...values) + 0.05);
    };
    const root = getComputedStyle(document.documentElement);
    const focus = getComputedStyle(document.activeElement!);
    return {
      muted: contrast(root.getPropertyValue('--muted'), root.getPropertyValue('--page')),
      accent: contrast(
        root.getPropertyValue('--accent-deep'),
        root.getPropertyValue('--accent-soft'),
      ),
      pitch: contrast(
        getComputedStyle(document.querySelector('header p')!).color,
        root.getPropertyValue('--page'),
      ),
      focus: contrast(focus.outlineColor, root.getPropertyValue('--page')),
      focusStyle: focus.outlineStyle,
      primary: contrast(root.getPropertyValue('--surface'), root.getPropertyValue('--accent-deep')),
      danger: contrast(root.getPropertyValue('--danger'), root.getPropertyValue('--danger-soft')),
    };
  });
  expect(contrasts.muted).toBeGreaterThanOrEqual(4.5);
  expect(contrasts.accent).toBeGreaterThanOrEqual(4.5);
  expect(contrasts.pitch).toBeGreaterThanOrEqual(4.5);
  expect(contrasts.focus).toBeGreaterThanOrEqual(3);
  expect(contrasts.focusStyle).toBe('solid');
  expect(contrasts.primary).toBeGreaterThanOrEqual(4.5);
  expect(contrasts.danger).toBeGreaterThanOrEqual(4.5);
});
