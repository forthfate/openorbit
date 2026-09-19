import { expect, test } from '@playwright/test'
import en from '../src/locales/languages/en.json' with { type: 'json' }
import ko from '../src/locales/languages/ko.json' with { type: 'json' }
import ja from '../src/locales/languages/ja.json' with { type: 'json' }

test.use({ baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3001' })

for (const language of [en, ko, ja]) {
  test(`preserves and discards prompt drafts deliberately in ${language.id}`, async ({ page }) => {
    const copy = language.messages.promptDraft
    const close = language.messages.ui.closeDialog
    const draftKey = 'orbit.prompt-template-draft.draft-regression'
    await page.goto(`/e2e/fixtures/prompt-draft.html?locale=${language.id}`)
    await page.getByText('Draft regression template', { exact: true }).click()
    const editor = page.getByRole('dialog')
    const body = editor.locator('textarea')
    await body.fill('Unsaved prompt')
    await editor.getByRole('button', { name: close, exact: true }).click()
    const confirm = page.getByRole('dialog', { name: copy.title, exact: true })
    await expect(confirm).toContainText(copy.closeDescription)
    await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key)!).content, draftKey)).toBe('Unsaved prompt')
    await confirm.getByRole('button', { name: copy.cancel, exact: true }).click()
    await expect(body).toHaveValue('Unsaved prompt')

    await editor.getByRole('combobox').selectOption('1')
    await expect(confirm).toContainText(copy.switchDescription)
    await confirm.getByRole('button', { name: copy.cancel, exact: true }).click()
    await expect(body).toHaveValue('Unsaved prompt')
    await expect(editor.getByRole('combobox')).toHaveValue('2')
    await editor.getByRole('combobox').selectOption('1')
    await confirm.getByRole('button', { name: copy.discard, exact: true }).click()
    await expect(body).toHaveValue('Previous prompt')
    await expect(editor.getByRole('combobox')).toHaveValue('1')

    // A saved historical version is clean and must not survive as a draft.
    await expect.poll(() => page.evaluate(key => localStorage.getItem(key), draftKey)).toBeNull()
    await editor.getByRole('button', { name: close, exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByText('Draft regression template', { exact: true }).click()
    await expect(body).toHaveValue('Current prompt')
    await expect(editor.getByRole('combobox')).toHaveValue('2')

    // A genuine edit based on v1 restores both its content and version.
    await editor.getByRole('combobox').selectOption('1')
    await body.fill('Edited previous prompt')
    await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key)!).content, draftKey)).toBe('Edited previous prompt')
    await page.reload()
    await page.getByText('Draft regression template', { exact: true }).click()
    await expect(body).toHaveValue('Edited previous prompt')
    await expect(editor.getByRole('combobox')).toHaveValue('1')
    await editor.getByRole('button', { name: close, exact: true }).click()
    await confirm.getByRole('button', { name: close, exact: true }).click()
    await expect(body).toHaveValue('Edited previous prompt')
    await editor.getByRole('button', { name: close, exact: true }).click()
    await confirm.getByRole('button', { name: copy.discard, exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(await page.evaluate(key => localStorage.getItem(key), draftKey)).toBeNull()
    await page.getByText('Draft regression template', { exact: true }).click()
    await expect(body).toHaveValue('Current prompt')
    await editor.getByRole('button', { name: close, exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
}
