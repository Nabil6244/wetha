import {test, expect} from '@playwright/test';

test('evidence to script workflow blocks synthetic broadcast review', async ({page}) => {
  await page.goto('/');
  await expect(page.getByRole('heading', {name:'Control center'})).toBeVisible();
  await expect(page.getByText('Local service connected')).toBeVisible();
  await page.getByRole('button', {name:'Load training dataset'}).click();
  await expect(page.getByRole('status').filter({hasText:'Synthetic training dataset loaded'})).toBeVisible();
  await page.getByRole('button', {name:/Training Cyclone.*Jan 01, 2024, 18:00/}).click();
  await expect(page.getByRole('heading', {name:'What changed?'})).toBeVisible();
  await expect(page.locator('.changes')).toContainText('85');
  await expect(page.locator('.changes')).toContainText('100');
  await page.getByRole('button', {name:'Create source-linked script'}).click();
  await expect(page.getByRole('heading', {name:'Script Editor', exact:true})).toBeVisible();
  await expect(page.locator('.script-text')).toContainText('synthetic scenario is not a weather observation');
  await expect(page.locator('.script-text')).toContainText('85 to 100 mph');
  await page.getByLabel('REVIEWER NAME').fill('Browser test editor');
  await page.getByRole('button', {name:'Record editorial review'}).click();
  await expect(page.getByRole('alert')).toContainText('remain blocked');
  const download = page.waitForEvent('download');
  await page.getByRole('link', {name:'Export scene plan CSV'}).click();
  expect((await download).suggestedFilename()).toBe('scene-plan.csv');
  await page.reload();
  await page.getByRole('button', {name:'Script Editor', exact:true}).click();
  await expect(page.locator('.script-text')).toContainText('85 to 100 mph');
  await page.screenshot({path:'test-results/newsroom.png', fullPage:true});
});

test('capabilities and planned modules report actual state', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name:'OBS Controller', exact:true}).click();
  await expect(page.getByText('Phase 6 · not connected')).toBeVisible();
  await page.getByRole('button', {name:'Settings', exact:false}).click();
  await expect(page.getByRole('heading', {name:'Runtime capabilities'})).toBeVisible();
  await expect(page.locator('.settings-rows')).toContainText('ffmpeg');
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('heading', {name:'Settings', exact:true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('intelligence filters, verification timeline and paused polling settings work', async ({page, request}) => {
  await page.goto('/');
  await expect(page.getByText('Local service connected')).toBeVisible();
  await page.getByRole('button', {name:'Weather Intelligence', exact:true}).click();
  await expect(page.getByText('NWS active alerts', {exact:true})).toBeVisible();
  await expect(page.getByText('NHC Atlantic advisories', {exact:true})).toBeVisible();
  await page.getByLabel('Evidence provider').selectOption('TRAINING');
  await page.getByLabel('Evidence versions').selectOption('all');
  await expect(page.locator('.archive-panel .event-row')).toHaveCount(2);
  await page.getByLabel('Search weather evidence').fill('no matching place');
  await expect(page.getByRole('heading', {name:'No matching evidence'})).toBeVisible();
  await page.getByLabel('Search weather evidence').clear();
  await page.locator('.archive-panel .event-row').first().click();
  await expect(page.getByRole('heading', {name:'Evidence verification'})).toBeVisible();
  await expect(page.getByRole('heading', {name:'Visual evidence timeline'})).toBeVisible();
  await expect(page.locator('.evidence-timeline button')).toHaveCount(2);
  await page.getByLabel('NWS polling interval').selectOption('60');
  await expect(page.getByRole('status').filter({hasText:'NWS automatic collection paused'})).toBeVisible();
  const response = await request.get('/api/intelligence');
  const feed = (await response.json()).feeds.find((value:{id:string}) => value.id === 'nws');
  expect(feed.enabled).toBe(false);
  expect(feed.interval_seconds).toBe(60);
  await page.reload();
  await page.getByRole('button', {name:'Weather Intelligence', exact:true}).click();
  await expect(page.getByLabel('NWS polling interval')).toHaveValue('60');
  await expect(page.getByRole('button', {name:'Start polling NWS'})).toBeVisible();
  await page.screenshot({path:'test-results/weather-intelligence.png',fullPage:true});
});
