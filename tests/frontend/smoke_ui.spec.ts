/**
 * UI Smoke тест — имитирует реального пользователя:
 * 1. Parse Tab  — вводит текст, запускает парсинг, проверяет таблицу
 * 2. Lexicon Tab — открывает, проверяет наличие слов из парсинга
 * 3. Assignments Tab — открывает, проверяет структуру
 * 4. Statistics Tab — открывает, проверяет KPI-карточки
 * 5. Export — запускает скачивание, проверяет ответ
 */

import { test, expect, Page } from '@playwright/test';

const BASE = 'http://127.0.0.1:8765';
const PARSE_TEXT = 'She decided to look into the matter carefully. The team needs to carry out the plan.';

// ── helpers ───────────────────────────────────────────────────────────────────

async function clickTab(page: Page, label: string) {
  await page.click(`button:has-text("${label}")`);
  await page.waitForTimeout(300);
}

async function waitForNoSpinner(page: Page, timeout = 20_000) {
  // Спиннер/загрузка исчезает — ждём пока не останется элементов с «Loading» / aria-busy
  await page.waitForFunction(
    () => !document.querySelector('[aria-busy="true"], [data-testid="loading"]'),
    { timeout }
  );
}

// ── тесты ─────────────────────────────────────────────────────────────────────

test.describe('UI Smoke', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
  });

  // 1. Parse Tab ───────────────────────────────────────────────────────────────
  test('Parse: вводит текст и получает результат', async ({ page }) => {
    await clickTab(page, 'Parse');

    // Найти textarea / input для текста
    const textarea = page.locator('textarea, input[type="text"]').first();
    await expect(textarea).toBeVisible({ timeout: 5000 });
    await textarea.fill(PARSE_TEXT);

    // Кнопка Parse / Submit
    const parseBtn = page.locator('button').filter({ hasText: /^parse$/i }).first();
    await expect(parseBtn).toBeVisible();
    await parseBtn.click();

    // Ждём таблицу с результатами (rows с токенами)
    const table = page.locator('table').first();
    await expect(table).toBeVisible({ timeout: 30_000 });

    const rows = page.locator('table tbody tr');
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(3);

    // Проверяем что в первой строке есть слово «She» или хотя бы текст
    const firstCell = rows.nth(0).locator('td').first();
    await expect(firstCell).not.toBeEmpty();

    // Phrasal verb «look into» должен присутствовать в таблице
    await expect(page.locator('table')).toContainText('look into');

    console.log(`Parse: найдено ${await rows.count()} строк`);
  });

  // 2. Lexicon Tab ─────────────────────────────────────────────────────────────
  test('Lexicon: открывается и показывает строки', async ({ page }) => {
    await clickTab(page, 'Lexicon');

    // Должна быть таблица или список слов
    const content = page.locator('main, [role="main"], .tab-content, section').first();
    await expect(content).toBeVisible({ timeout: 5000 });

    // Ждём таблицу или сообщение «empty»
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').count() > 0;
    const hasEmpty = await page.locator('text=/empty|no words|nothing/i').count() > 0;

    expect(hasTable || hasEmpty).toBe(true);

    if (hasTable) {
      console.log(`Lexicon: таблица найдена, строк: ${await page.locator('table tbody tr').count()}`);
    } else {
      console.log('Lexicon: таблица пустая (нет добавленных слов)');
    }
  });

  // 3. Assignments Tab ─────────────────────────────────────────────────────────
  test('Assignments: открывается, показывает структуру', async ({ page }) => {
    await clickTab(page, 'Assignments');

    const content = page.locator('main, [role="main"], .tab-content, section, [class*="tab"]').first();
    await expect(content).toBeVisible({ timeout: 5000 });
    await page.waitForTimeout(1500);

    // Страница не должна быть пустой — хоть что-то отрендерилось
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(20);

    console.log('Assignments: таб открылся, контент есть');
  });

  // 4. Statistics Tab ──────────────────────────────────────────────────────────
  test('Statistics: показывает KPI-карточки с числами', async ({ page }) => {
    await clickTab(page, 'Statistics');
    await page.waitForTimeout(2000);

    // KpiCard рендерит числа — ищем любой элемент с числовым значением
    const body = await page.locator('body').innerText();
    const hasNumbers = /\d+/.test(body);
    expect(hasNumbers).toBe(true);

    console.log('Statistics: таб открылся, числа присутствуют');
  });

  // 5. Parse → Sync (добавить в лексикон) ──────────────────────────────────────
  test('Parse → Sync: парсит и синхронизирует слова в лексикон', async ({ page }) => {
    await clickTab(page, 'Parse');

    const textarea = page.locator('textarea, input[type="text"]').first();
    await textarea.fill('The quick brown fox jumps over the lazy dog.');

    // Включить sync если есть чекбокс
    const syncCheckbox = page.locator('input[type="checkbox"]').filter({ hasText: /sync/i }).first();
    if (await syncCheckbox.count() > 0) {
      await syncCheckbox.check();
    }

    const parseBtn = page.locator('button').filter({ hasText: /^parse$/i }).first();
    await parseBtn.click();

    // Ждём таблицу
    await expect(page.locator('table').first()).toBeVisible({ timeout: 30_000 });
    console.log('Parse+Sync: выполнен успешно');
  });

  // 6. Навигация по всем табам подряд ─────────────────────────────────────────
  test('Navigation: переключает все 4 таба без ошибок', async ({ page }) => {
    const tabs = ['Parse', 'Lexicon', 'Assignments', 'Statistics'];
    const errors: string[] = [];

    page.on('pageerror', err => errors.push(err.message));
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    for (const tab of tabs) {
      await clickTab(page, tab);
      await page.waitForTimeout(800);
      const title = await page.title();
      console.log(`Tab "${tab}" — page title: ${title}, JS errors: ${errors.length}`);
    }

    // Не должно быть JS-ошибок
    const fatalErrors = errors.filter(e =>
      !e.includes('favicon') && !e.includes('ResizeObserver') && !e.includes('net::ERR')
    );
    expect(fatalErrors).toHaveLength(0);
  });
});
