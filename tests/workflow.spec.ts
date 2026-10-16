import {test, expect} from '@playwright/test';

// Scene shots over ten seconds of map are refused on save (map-hold limit), so tests that save a timeline keep each scene short.
async function shortenScenes(page: import('@playwright/test').Page, count: number) {
  for (let i = 1; i <= count; i++) await page.getByRole('spinbutton', {name: `Scene ${i} seconds`, exact: true}).fill('8');
}

// The story list shows current alerts by default; older (training) stories sit behind a toggle that only appears when needed.
async function storyCheckbox(page: import('@playwright/test').Page, id: RegExp) {
  const topics = page.getByRole('group', {name: 'Bulletin stories', exact: true});
  const box = topics.getByRole('checkbox', {name: id});
  const older = page.getByRole('button', {name: /older or expired/});
  await expect(box.or(older)).toBeVisible();
  if (!(await box.count())) await older.click();
  return box;
}

test('phase 5 imports licensed media and renders a source-linked silent preview', async ({page, request}) => {
  test.setTimeout(90000);
  await request.post('/api/training/load');
  const draft = await (await request.post('/api/scripts', {data: {advisory_id: 'training:cyclone:2'}})).json();
  await page.goto('/');
  await expect(page.getByText('Local service connected')).toBeVisible();
  await page.getByRole('button', {name: 'Media Library', exact: true}).click();
  await page.getByLabel('MEDIA TYPE', {exact: true}).selectOption('image');
  // A synthetic 1×1 PNG tests file upload; it is never presented as observation imagery.
  await page.getByLabel('CHOOSE MEDIA FILE').setInputFiles({name: 'synthetic-ui.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQC/UDAAFWAMID7WKmAAAAAElFTkSuQmCC', 'base64')});
  await page.getByLabel('LICENSE / USAGE TERMS').fill('Owned synthetic browser fixture');
  await page.getByLabel('MEDIA ATTRIBUTION').fill('Browser test creator');
  await page.getByLabel('MEDIA SOURCE', {exact: true}).fill('Synthetic browser test fixture');
  await page.getByLabel('I have checked that these usage terms').check();
  await page.getByRole('button', {name: 'Import media', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Media validated'})).toBeVisible();
  await expect(page.locator('.production-media-card')).toHaveCount(1);
  await page.getByRole('button', {name: 'Create Video', exact: true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('SCRIPT FOR NEW PLAN').selectOption(draft.id);
  await page.getByRole('button', {name: 'Prepare scene plan', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Source-linked scenes prepared'})).toBeVisible();
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  const inputs = page.getByRole('spinbutton', {name: /^Scene \d+ seconds$/});
  for (const input of await inputs.all()) await input.fill('1');
  const media = (await (await request.get('/api/production')).json()).media[0];
  await page.getByLabel('Scene 1 media', {exact: true}).selectOption(media.id);
  await page.getByLabel('Scene 1 transition', {exact: true}).selectOption('fade');
  await page.getByLabel('PROGRAM TITLE').fill('Browser production preview');
  await page.getByRole('button', {name: 'Save timeline', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Timeline saved'})).toBeVisible();
  const timelineId = await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  await page.getByLabel('PROGRAM TITLE').fill('Unsaved title change');
  await expect(page.getByRole('button', {name: 'Render 1080p preview'})).toBeDisabled();
  await page.getByRole('button', {name: 'Discard timeline edits', exact: true}).click();
  await expect(page.getByLabel('SAVED PRODUCTION TIMELINE')).toHaveValue(timelineId);
  await page.getByRole('button', {name: 'Render 1080p preview'}).click();
  await expect(page.locator('.production-job').first()).toContainText('succeeded', {timeout: 60000});
  await expect(page.locator('.production-job').first()).toContainText('full output decoded');
  await page.getByRole('button', {name: 'Preview video', exact: true}).first().click();
  await expect(page.locator('.production-preview video')).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', {name: 'Download MP4', exact: true}).first().click();
  expect((await download).suggestedFilename()).toBe('program.mp4');
  const render = (await (await request.get('/api/production')).json()).renders[0];
  expect(render.broadcast_eligible).toBe(false);
  expect(render.validation.audio_mode).toBe('silent');
  await page.screenshot({path: 'test-results/phase-5-production.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.reload();
  await page.getByRole('button', {name: 'Create Video', exact: true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await expect(page.locator('.production-job').first()).toContainText('succeeded');
});

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
  await expect(page.locator('.panel').filter({has:page.getByRole('heading',{name:'Runtime capabilities',exact:true})})).toContainText('ffmpeg');
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('heading', {name:'Settings', exact:true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('intelligence filters, verification timeline and paused polling settings work', async ({page, request}) => {
  await request.post('/api/training/load');
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

test('newsroom handoffs, revision history and unsupported edits work in the browser', async ({page, request}) => {
  await request.post('/api/training/load');
  await page.goto('/');
  await expect(page.getByText('Local service connected')).toBeVisible();
  await page.getByRole('button', {name:'AI Newsroom', exact:true}).click();
  const evidence = page.getByLabel('SOURCE EVIDENCE');
  await evidence.selectOption('training:cyclone:2');
  await expect(page.getByLabel('WRITER')).toHaveValue('deterministic');
  await page.getByRole('button', {name:'Run newsroom', exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Six newsroom roles completed'})).toBeVisible();
  await expect(page.locator('.agent-handoff')).toHaveCount(6);
  await page.locator('.agent-handoff').nth(3).locator('summary').first().click();
  await expect(page.locator('.agent-handoff').nth(3)).toContainText('evidence_manifest');
  await page.getByRole('button', {name:'Open draft', exact:true}).click();
  await expect(page.locator('.script-text')).toContainText('85 to 100 mph');
  await page.getByRole('button', {name:'Edit narration'}).click();
  const narration = page.getByLabel('NARRATION TEXT');
  const original = await narration.inputValue();
  await narration.fill(original + '\n\nUnsupported test claim: landfall tomorrow with 200 mph winds.');
  await page.getByLabel('EDITOR NAME', {exact:true}).fill('Browser revision editor');
  // Saving an edited script does not require an optional revision note.
  await expect(page.getByRole('button', {name:'Save new revision'})).toBeEnabled();
  await page.getByRole('button', {name:'Save new revision'}).click();
  await expect(page.getByRole('status').filter({hasText:'New revision saved'})).toBeVisible();
  await expect(page.locator('.claim-card.unsupported')).toHaveCount(1);
  await expect(page.locator('.editorial-issues')).toContainText('requires a named source attestation');
  await page.getByLabel('REVIEWER NAME').fill('Browser editor');
  await page.getByRole('button', {name:'Record editorial review'}).click();
  await expect(page.getByRole('alert')).toContainText('remain blocked');
  await page.getByLabel('REVISION HISTORY').selectOption('1');
  await expect(page.locator('.script-text')).not.toContainText('Unsupported test claim');
  await expect(page.getByRole('button', {name:'Record editorial review'})).toBeDisabled();
  await page.getByLabel('REVISION HISTORY').selectOption('latest');
  await expect(page.locator('.script-text')).toContainText('Unsupported test claim');
  await page.reload();
  await page.getByRole('button', {name:'Script Editor', exact:true}).click();
  await expect(page.locator('.script-text')).toContainText('Unsupported test claim');
  await expect(page.getByLabel('REVISION HISTORY')).toContainText('Latest · revision 2');
  const scriptId = await page.getByLabel('SELECT DRAFT').inputValue();
  const document = await (await request.get(`/api/scripts/${scriptId}`)).json();
  expect(document.broadcast_eligible).toBe(false);
  expect(document.revision).toBe(2);
  expect(document.editorial.can_review).toBe(false);
  await page.screenshot({path:'test-results/phase-3-editor.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('edited claims retain named source attestations and remain training-only', async ({page, request}) => {
  await request.post('/api/training/load');
  const draft = await (await request.post('/api/scripts', {data:{advisory_id:'training:cyclone:2'}})).json();
  await page.goto('/');
  await expect(page.getByText('Local service connected')).toBeVisible();
  await page.getByRole('button', {name:'Script Editor', exact:true}).click();
  await page.getByLabel('SELECT DRAFT').selectOption(draft.id);
  await page.getByRole('button', {name:'Edit narration'}).click();
  const narration = page.getByLabel('NARRATION TEXT');
  await narration.fill(draft.text + '\n\nIn this training scenario, maximum winds are reported at 100 mph.');
  await page.getByLabel('EDITOR NAME', {exact:true}).fill('Browser claim editor');
  await page.getByLabel('REVISION NOTE').fill('Add supported training measurement');
  await page.getByRole('button', {name:'Save new revision'}).click();
  await expect(page.getByRole('status').filter({hasText:'New revision saved'})).toBeVisible();
  await expect(page.locator('.claim-card.unsupported')).toHaveCount(1);
  await page.getByLabel('REVIEWER NAME').fill('Browser source checker');
  await page.getByRole('button', {name:'Read preserved source'}).click();
  const sourceText = await page.locator('.source-quote-preview').textContent();
  expect(sourceText).toContain('SYNTHETIC TRAINING SCENARIO');
  await page.getByLabel('EXACT SUPPORTING QUOTE').fill(sourceText!);
  await page.getByLabel('WHY THIS QUOTE SUPPORTS THE CLAIM').fill('The synthetic scenario contains the same wind measurement; this is training-only.');
  await page.getByRole('button', {name:'Record source attestation'}).click();
  await expect(page.getByRole('status').filter({hasText:'Source attestation saved'})).toBeVisible();
  await expect(page.locator('.claim-card.unsupported')).toHaveCount(0);
  const doc = await (await request.get(`/api/scripts/${draft.id}`)).json();
  expect(doc.revision).toBe(3);
  expect(doc.claims.at(-1).status).toBe('human_attested');
  expect(doc.claims.at(-1).support.reviewer).toBe('Browser source checker');
  expect(doc.editorial.can_review).toBe(false);
  await page.getByRole('button', {name:'Record editorial review'}).click();
  await expect(page.getByRole('alert')).toContainText('remain blocked');
  await page.reload();
  await page.getByRole('button', {name:'Script Editor', exact:true}).click();
  await page.getByLabel('SELECT DRAFT').selectOption(draft.id);
  const supported = page.locator('.claim-card').filter({hasText:'human attested'});
  await supported.locator('summary').click();
  await expect(supported).toContainText('Verified by Browser source checker');
  await page.screenshot({path:'test-results/phase-3-attestation.png',fullPage:true});
});

test('visual director renders real geography, labels missing layers and pins scene revisions', async ({page, request}) => {
  await request.post('/api/training/load');
  const draft=await (await request.post('/api/scripts',{data:{advisory_id:'training:cyclone:2'}})).json();
  await page.goto('/');
  await expect(page.getByText('Local service connected')).toBeVisible();
  await page.getByRole('button',{name:'Visual Director',exact:true}).click();
  await expect(page.getByTestId('geographic-map')).toBeVisible();
  await expect.poll(async()=>Number(await page.getByTestId('geographic-map').getAttribute('data-country-features'))).toBeGreaterThan(0);
  const response=await request.get('/api/visuals/basemap');
  const countries=await response.json();expect(countries.features.length).toBe(177);
  await page.getByLabel('VISUAL SOURCE EVIDENCE').selectOption('training:cyclone:2');
  await expect(page.locator('.geographic-note')).toContainText('Only official geographic evidence is plotted');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('button',{name:'Rotate map camera'}).click();
  await page.getByRole('button',{name:'Tilt map camera'}).click();
  await page.getByRole('button',{name:'Satellite',exact:true}).click();
  await expect(page.getByRole('heading',{name:'No satellite observations cached'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Play observations'})).toBeDisabled();
  await page.getByLabel('SCRIPT REVISION').selectOption(draft.id);
  await page.getByRole('button',{name:'Direct scenes',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Source-linked visual plan saved'})).toBeVisible();
  await expect(page.locator('.scene-plan')).toContainText('training');
  const id=await page.getByLabel('SAVED VISUAL PLAN').inputValue();
  const plan=await (await request.get('/api/visuals/plans/'+id)).json();
  expect(plan.script_revision).toBe(1);expect(plan.rendered).toBe(false);expect(plan.broadcast_eligible).toBe(false);
  expect(plan.scenes[1].parameters.unavailable_requested_layer).toBe('satellite');
  const download=page.waitForEvent('download');
  await page.getByRole('link',{name:'Export visual scenes CSV'}).click();
  expect((await download).suggestedFilename()).toBe('visual-scenes.csv');
  await page.getByRole('button',{name:'Radar',exact:true}).click();
  await expect(page.locator('.radar-legend')).toContainText('No timestamped radar frames');
  await page.screenshot({path:'test-results/phase-4-visual-director.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.reload();
  await page.getByRole('button',{name:'Visual Director',exact:true}).click();
  await page.getByLabel('SAVED VISUAL PLAN').selectOption(id);
  await expect(page.locator('.scene-plan')).toContainText('Revision 1');
});

test('broadcast style preserves source revision and exposes the historical benchmark', async ({page, request}) => {
  await request.post('/api/training/load');
  const draft = await (await request.post('/api/scripts', {data: {advisory_id: 'training:cyclone:2'}})).json();
  await page.goto('/');
  await page.getByRole('button', {name: 'Create Video', exact: true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('SCRIPT FOR NEW PLAN').selectOption(draft.id);
  await page.getByRole('button', {name: 'Prepare scene plan', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Source-linked scenes prepared'})).toBeVisible();
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByLabel('VIDEO STYLE').selectOption('broadcast');
  const seconds = page.getByRole('spinbutton', {name: /^Scene \d+ seconds$/});
  for (const input of await seconds.all()) await input.fill('1');
  await page.getByRole('button', {name: 'Save timeline', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Timeline saved'})).toBeVisible();
  const id = await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  const production = await (await request.get('/api/production')).json();
  const saved = production.timelines.find((t: {id: string}) => t.id === id);
  expect(saved.presentation).toBe('broadcast');
  expect(saved.scenes.every((s: {direction: {max_words: number}; transition: string}) => s.direction.max_words === 8 && s.transition === 'fade')).toBeTruthy();
  if (production.benchmark.available) {
    await page.getByText('Example videos, regional sources & long programs',{exact:true}).click();
    await expect(page.getByRole('heading', {name: 'Historical broadcast benchmark · AL092020'})).toBeVisible();
    expect((await request.get('/api/production/benchmark/video', {headers: {Range: 'bytes=0-1023'}})).status()).toBe(206);
  }
});

test('YouTube media origin exposes reuse evidence and short cut preferences', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name: 'Media Library', exact: true}).click();
  await page.getByLabel('MEDIA ORIGIN').selectOption('youtube');
  await expect(page.getByLabel('MEDIA TYPE', {exact: true})).toHaveValue('video');
  await expect(page.getByLabel('MEDIA TYPE', {exact: true})).toBeDisabled();
  await expect(page.getByLabel('YOUTUBE CUT SECONDS')).toHaveValue('3.5');
  await page.getByLabel('YOUTUBE REUSE BASIS').selectOption('cc_by');
  await page.getByLabel('YOUTUBE REUSE EVIDENCE').fill('Synthetic test CC BY declaration');
  await expect(page.getByText('A short cut alone does not grant reuse rights.', {exact: false})).toBeVisible();
  await page.getByLabel('MEDIA ORIGIN').selectOption('local');
  await expect(page.getByLabel('MEDIA TYPE', {exact: true})).toBeEnabled();
  await expect(page.getByLabel('YOUTUBE REUSE EVIDENCE')).toHaveCount(0);
});

test('short template suggests footage, preserves claims and checks timing before saving', async ({page, request}) => {
  await request.post('/api/training/load');
  const script = await (await request.post('/api/scripts', {data: {advisory_id: 'training:cyclone:2'}})).json();
  const plan = await (await request.post('/api/visuals/plans', {data: {script_id: script.id, expected_revision: script.revision}})).json();
  const response = await request.post('/api/production/media', {
    headers: {'X-Media-Metadata': encodeURIComponent(JSON.stringify({name: 'short-template-rain.png', kind: 'image', context: 'illustrative', license: 'Owned synthetic template fixture', attribution: 'Template test creator', source: 'Synthetic template test', rights_confirmed: true}))},
    data: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQC/UDAAFWAMID7WKmAAAAAElFTkSuQmCC', 'base64'),
  });
  // Other workflow tests may already have imported these same synthetic bytes.
  const media = response.ok() ? await response.json() : (await (await request.get('/api/production')).json()).media.find((m: {kind: string}) => m.kind === 'image');
  expect(media).toBeTruthy();
  await page.goto('/');
  await page.getByRole('button', {name: 'Media Library', exact: true}).click();
  const card = page.locator('.production-media-card').filter({has: page.getByRole('heading', {name: media.name, exact: true})});
  await card.getByText('Tag footage for automatic suggestions', {exact: true}).click();
  await page.getByLabel(`${media.name} weather tags`, {exact: true}).fill('wind, rain, storm, waves');
  await card.getByRole('button', {name: 'Save footage tags', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Footage tags saved'})).toBeVisible();
  await page.getByRole('button', {name: 'Create Video', exact: true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('PRODUCTION SCENE PLAN', {exact: true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByRole('button', {name: 'Suggest 30-second edit', exact: true}).click();
  await expect(page.getByRole('region', {name: 'Suggested short edit'})).toBeVisible();
  await page.getByRole('button', {name: 'Apply 30-second draft', exact: true}).click();
  await expect(page.getByLabel('VIDEO STYLE', {exact: true})).toHaveValue('broadcast');
  await expect(page.getByText('30-second short template · 30.00 seconds', {exact: true})).toBeVisible();
  await expect(page.getByRole('spinbutton', {name: /^Scene \d+ seconds$/})).toHaveCount(plan.scenes.length);
  await page.getByRole('button', {name: 'Check visuals & timing', exact: true}).click();
  await expect(page.getByRole('region', {name: 'Timeline checks'})).toContainText('Ready to render after saving');
  await page.getByRole('button', {name: 'Save timeline', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Timeline saved'})).toBeVisible();
  const id = await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  const timeline = (await (await request.get('/api/production')).json()).timelines.find((t: {id: string}) => t.id === id);
  expect(timeline.template).toBe('short_30');
  expect(timeline.seconds).toBe(30);
  expect(timeline.scenes.map((s: {id: string}) => s.id)).toEqual(plan.scenes.map((s: {id: string}) => s.id));
  await page.getByRole('spinbutton', {name: 'Scene 1 seconds', exact: true}).fill('2');
  await expect(page.getByRole('region', {name: 'Timeline checks'})).toHaveCount(0);
  await expect(page.getByRole('button', {name: 'Render 1080p preview'})).toBeDisabled();
  await page.screenshot({path: 'test-results/short-template.png', fullPage: true});
});

test('media discovery previews reviewed sources and filters stock and YouTube archives offline', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name: 'Media Library', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Discover free weather footage', exact: true})).toBeVisible();
  await expect(page.locator('.discovery-card')).toHaveCount(3);
  await expect(page.getByRole('link', {name: 'Search Pexels', exact: true})).toHaveAttribute('href', /pexels.com/);
  await expect(page.getByRole('link', {name: 'Search YouTube', exact: true})).toHaveAttribute('href', /youtube.com/);
  await expect(page.locator('.discovery-card video').first()).toHaveAttribute('preload', 'none');
  await expect(page.getByRole('button', {name: 'Import selected source', exact: true}).first()).toBeDisabled();
  await page.getByLabel('Include live Wikimedia search', {exact: true}).uncheck();
  await page.getByLabel('SEARCH WEATHER FOOTAGE', {exact: true}).fill('waves');
  await page.getByLabel('DISCOVERY SOURCE', {exact: true}).selectOption('youtube');
  await page.getByRole('button', {name: 'Search free sources', exact: true}).click();
  await expect(page.locator('.discovery-card')).toHaveCount(1);
  await expect(page.locator('.discovery-card')).toContainText('Bruce and Tammy Swart');
  await expect(page.locator('.discovery-card')).toContainText('CC BY 3.0');
  await page.getByRole('checkbox', {name: /^Review usage terms for/}).check();
  await expect(page.getByRole('button', {name: 'Import selected source', exact: true})).toBeEnabled();
  await page.getByLabel('DISCOVERY SOURCE', {exact: true}).selectOption('stock');
  await page.getByLabel('SEARCH WEATHER FOOTAGE', {exact: true}).fill('rain');
  await page.getByRole('button', {name: 'Search free sources', exact: true}).click();
  await expect(page.locator('.discovery-card')).toHaveCount(1);
  await expect(page.locator('.discovery-card')).toContainText('Startup MrParag');
  await expect(page.getByRole('button', {name: 'Import selected source', exact: true})).toBeDisabled();
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/media-discovery.png', fullPage: true});
});

test('long report templates flag insufficient footage instead of stretching graphics', async ({page, request}) => {
  await request.post('/api/training/load');
  const script = await (await request.post('/api/scripts', {data:{advisory_id:'training:cyclone:2'}})).json();
  const plan = await (await request.post('/api/visuals/plans', {data:{script_id:script.id,expected_revision:script.revision}})).json();
  await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  for (const seconds of [60,90]) {
    await page.getByLabel('EDIT TEMPLATE',{exact:true}).selectOption(`report_${seconds}`);
    await page.getByRole('button',{name:`Suggest ${seconds}-second edit`,exact:true}).click();
    await expect(page.getByRole('region',{name:'Suggested short edit'})).toContainText('Not enough matching, unused footage');
    await expect(page.getByRole('button',{name:`Apply ${seconds}-second draft`,exact:true})).toBeDisabled();
  }
});

test('story draft exposes rewritten beats and retains original source claims', async ({page, request}) => {
  await request.post('/api/training/load');
  const script = await (await request.post('/api/scripts', {data:{advisory_id:'training:cyclone:2'}})).json();
  const plan = await (await request.post('/api/visuals/plans', {data:{script_id:script.id,expected_revision:script.revision}})).json();
  await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByRole('button',{name:'Build story draft',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Story draft prepared'})).toBeVisible();
  await expect(page.getByText(/Editorial preview: review this rewritten script/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Build story draft',exact:true})).toBeDisabled();
  const id = await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).inputValue();
  const story = await (await request.get(`/api/visuals/plans/${id}`)).json();
  expect(story.parent_plan_id).toBe(plan.id);
  expect(story.scenes[0].story_beat).toBe('hook');
  expect(story.scenes.every((s:{source_claim_text:string})=>!!s.source_claim_text)).toBeTruthy();
  await page.getByRole('button',{name:'Suggest 30-second edit',exact:true}).click();
  await page.getByRole('button',{name:'Apply 30-second draft',exact:true}).click();
  await page.getByRole('button',{name:'Check visuals & timing',exact:true}).click();
  await expect(page.getByRole('region',{name:'Timeline checks'})).toContainText('Ready to render after saving');
});

test('four map treatments can be selected checked and restored from a saved timeline', async ({page,request}) => {
  await request.post('/api/training/load');
  const script=await (await request.post('/api/scripts',{data:{advisory_id:'training:cyclone:2'}})).json();
  const plan=await (await request.post('/api/visuals/plans',{data:{script_id:script.id,expected_revision:1}})).json();
  await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByLabel('VIDEO STYLE',{exact:true}).selectOption('broadcast');
  for (const [i,mode] of ['track','warnings','radar','forecast'].entries()) {
    await page.getByLabel(`Scene ${i+1} map type`,{exact:true}).selectOption(mode);
  }
  await shortenScenes(page, plan.scenes.length);
  await page.getByRole('button',{name:'Check visuals & timing',exact:true}).click();
  await expect(page.getByRole('region',{name:'Timeline checks'})).toContainText('No source warning polygon');
  await expect(page.getByRole('region',{name:'Timeline checks'})).toContainText('No matching timestamped radar');
  await page.getByRole('button',{name:'Save timeline',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Timeline saved'})).toBeVisible();
  const id=await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  await page.getByLabel('SAVED PRODUCTION TIMELINE').selectOption('');
  await page.getByLabel('SAVED PRODUCTION TIMELINE').selectOption(id);
  await expect(page.getByLabel('Scene 4 map type',{exact:true})).toHaveValue('forecast');
});

test('hour chapters expose missing content and new motion graphics retain saved choices', async ({page,request}) => {
  await request.post('/api/training/load');
  const script=await (await request.post('/api/scripts',{data:{advisory_id:'training:cyclone:2'}})).json();
  const plan=await (await request.post('/api/visuals/plans',{data:{script_id:script.id,expected_revision:1}})).json();
  await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByText('Example videos, regional sources & long programs',{exact:true}).click();
  await expect(page.getByRole('region',{name:'One-hour storm deep dive'})).toContainText('12 chapters');
  await page.getByText('Open chapter structure and content assignments',{exact:true}).click();
  await expect(page.getByLabel('Chapter 12 timeline',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Check hour content & repetition',exact:true}).click();
  await expect(page.getByRole('region',{name:'Hour content audit'})).toContainText('More chapter content needed');
  await expect(page.getByRole('region',{name:'Hour content audit'})).toContainText('0s / 3600s');
  await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByLabel('VIDEO STYLE',{exact:true}).selectOption('broadcast');
  await page.getByLabel('Scene 1 motion graphic',{exact:true}).selectOption('source_card');
  await page.getByRole('button',{name:'Save timeline',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Timeline saved'})).toBeVisible();
  const id=await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  await page.getByLabel('SAVED PRODUCTION TIMELINE').selectOption('');
  await page.getByLabel('SAVED PRODUCTION TIMELINE').selectOption(id);
  await expect(page.getByLabel('Scene 1 motion graphic',{exact:true})).toHaveValue('source_card');
});

test('regional workflow blocks other-state footage and restores reviewed focus', async ({page,request})=>{
  await request.post('/api/training/load');
  const script=await (await request.post('/api/scripts',{data:{advisory_id:'training:cyclone:2'}})).json();
  const plan=await (await request.post('/api/visuals/plans',{data:{script_id:script.id,expected_revision:script.revision}})).json();
  await request.post('/api/production/media',{headers:{'X-Media-Metadata':encodeURIComponent(JSON.stringify({name:'regional-synthetic.png',kind:'image',context:'illustrative',license:'Owned synthetic regional fixture',attribution:'Browser test creator',source:'Synthetic region test',rights_confirmed:true}))},data:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQC/UDAAFWAMID7WKmAAAAAElFTkSuQmCC','base64')});
  const media=(await (await request.get('/api/production')).json()).media.find((m:{kind:string})=>m.kind==='image');
  expect(media).toBeTruthy();
  await request.put(`/api/production/media/${media.id}/catalog`,{data:{tags:['rain','wind'],region_codes:['WA'],location_reviewed:true,reference:'https://example.org/synthetic-region-test'}});
  await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByText('Example videos, regional sources & long programs',{exact:true}).click();
  await expect(page.getByRole('heading',{name:'Regional relevance',exact:true})).toBeVisible();
  await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByLabel('VIDEO STYLE',{exact:true}).selectOption('broadcast');
  await page.getByLabel('Scene 1 regional focus',{exact:true}).selectOption('FL');
  await page.getByLabel('Scene 1 media',{exact:true}).selectOption(media.id);
  await page.getByRole('button',{name:'Check visuals & timing',exact:true}).click();
  await expect(page.getByRole('region',{name:'Timeline checks'})).toContainText('needs a matching capture region');
  await page.getByRole('button',{name:'Media Library',exact:true}).click();
  const card=page.locator('.production-media-card').filter({has:page.getByRole('heading',{name:media.name,exact:true})});
  await card.locator('summary').click();
  await card.getByLabel(`${media.name} capture region`,{exact:true}).selectOption(['FL']);
  await card.getByLabel(`${media.name} location reviewed`,{exact:true}).check();
  await card.getByRole('button',{name:'Save footage tags',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Footage tags saved'})).toBeVisible();
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).selectOption(plan.id);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await page.getByLabel('VIDEO STYLE',{exact:true}).selectOption('broadcast');
  await page.getByLabel('Scene 1 regional focus',{exact:true}).selectOption('FL');
  await page.getByLabel('Scene 1 media',{exact:true}).selectOption(media.id);
  await shortenScenes(page, plan.scenes.length);
  await page.getByRole('button',{name:'Save timeline',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Timeline saved'})).toBeVisible();
  const timeline=await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  await page.reload();await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('SAVED PRODUCTION TIMELINE').selectOption(timeline);
  await page.getByRole('button', {name:'Edit visuals & timing',exact:true}).click();
  await expect(page.getByLabel('Scene 1 regional focus',{exact:true})).toHaveValue('FL');
});

test('manual voiceover copies the script, uploads audio and renders with fitted timing', async ({page, request, context}) => {
  test.setTimeout(90000);
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await request.post('/api/training/load');
  const draft = await (await request.post('/api/scripts', {data:{advisory_id:'training:cyclone:2'}})).json();
  const plan = await (await request.post('/api/visuals/plans', {data:{script_id:draft.id, expected_revision:draft.revision}})).json();
  await page.goto('/');
  await page.getByRole('button', {name:'Create Video', exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  await page.getByLabel('PRODUCTION SCENE PLAN', {exact:true}).selectOption(plan.id);
  await expect(page.getByLabel('PROGRAM TITLE',{exact:true})).not.toBeVisible();
  await expect(page.getByRole('navigation',{name:'Video creation steps'})).toBeVisible();
  const panel = page.getByRole('region', {name:'Manual voiceover workflow'});
  const spoken = plan.scenes.map((s:{script_segment:string}) => s.script_segment).join('\n\n');
  await expect(panel.getByLabel('Voiceover script')).toHaveValue(spoken);
  await panel.getByRole('button', {name:'Copy voiceover script', exact:true}).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(spoken);
  await panel.getByLabel('UPLOAD NARRATION AUDIO').setInputFiles({name:'invalid-narration.mp3', mimeType:'audio/mpeg', buffer:Buffer.from('not audio')});
  await panel.getByLabel('I have permission to use this voiceover').check();
  await panel.getByRole('button', {name:'Upload audio for this video', exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'FFprobe'})).toBeVisible();
  // A synthetic tone verifies imported audio reaches the final video without generating speech.
  const seconds = plan.scenes.length * 1.37;
  const samples = Math.round(seconds * 16000);
  const wav = Buffer.alloc(44 + samples * 2);
  wav.write('RIFF',0); wav.writeUInt32LE(wav.length-8,4); wav.write('WAVEfmt ',8);
  wav.writeUInt32LE(16,16); wav.writeUInt16LE(1,20); wav.writeUInt16LE(1,22);
  wav.writeUInt32LE(16000,24); wav.writeUInt32LE(32000,28); wav.writeUInt16LE(2,32); wav.writeUInt16LE(16,34);
  wav.write('data',36); wav.writeUInt32LE(samples*2,40);
  for (let i=0; i<samples; i++) wav.writeInt16LE(Math.round(1000*Math.sin(i*2*Math.PI*440/16000)),44+i*2);
  await panel.getByLabel('UPLOAD NARRATION AUDIO').setInputFiles({name:'manual-browser-voice.wav',mimeType:'audio/wav',buffer:wav});
  await panel.getByLabel('I have permission to use this voiceover').check();
  await panel.getByRole('button', {name:'Upload audio for this video', exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Audio uploaded and selected'})).toBeVisible();
  await expect(page.locator('#production-finish .production-narration audio')).toHaveAttribute('src', /\/api\/production\/media\/.+\/file/);
  await page.getByText('Estimated timing fallback',{exact:true}).click();
  await page.getByRole('button', {name:'Match video length to voiceover',exact:true}).click();
  await page.getByLabel('I listened and this voiceover matches the script.').check();
  await page.getByLabel('Video title', {exact:true}).fill('Manual voiceover integration');
  await page.getByRole('button', {name:'Make final video',exact:true}).click();
  // Make final video starts one saved automatic job: speech matching, planning and the render follow without further input.
  await expect(page.getByRole('status').filter({hasText:'Automatic production started'})).toBeVisible();
  await expect(page.getByRole('status').filter({hasText:'Your video is rendering locally'})).toBeVisible({timeout:120000});
  await expect(page.getByRole('status',{name:'Export progress'})).toContainText('Export');
  await expect(page.getByRole('button',{name:'Rendering video…',exact:true})).toBeDisabled();
  await expect(page.getByLabel('SAVED PRODUCTION TIMELINE')).not.toHaveValue('');
  const id = await page.getByLabel('SAVED PRODUCTION TIMELINE').inputValue();
  const saved = (await (await request.get('/api/production')).json()).timelines.find((t:{id:string}) => t.id===id);
  expect(saved.audio_mode).toBe('imported_narration');
  expect(saved.seconds).toBeCloseTo(Math.round(seconds*30)/30,2);
  expect(saved.template).toBeNull();
  const job = page.locator('.production-job').filter({has:page.getByRole('heading', {name:'Manual voiceover integration',exact:true})});
  await expect(job).toContainText('full output decoded',{timeout:150000});
  await expect(page.locator('#production-finish').getByRole('link',{name:'Download final MP4',exact:true})).toBeVisible();
  const completed = (await (await request.get('/api/production')).json()).renders.find((r:{timeline_id:string}) => r.timeline_id===id);
  expect(completed.validation.audio_mode).toBe('imported_narration');
  expect(completed.validation.seconds).toBeCloseTo(seconds,1);
  await expect(page.locator('.production-preview video')).toBeVisible();
  await expect(job.getByRole('link',{name:'Download MP4',exact:true})).toBeVisible();
  await page.locator('#production-finish').screenshot({path:'test-results/guided-export.png'});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.screenshot({path:'test-results/manual-voiceover.png'});
});

test('newsroom selects searchable multiple topics and produces one source-linked draft', async ({page,request}) => {
  await request.post('/api/training/load');
  await page.goto('/');
  await page.getByRole('button',{name:'AI Newsroom',exact:true}).click();
  await page.getByLabel('SOURCE EVIDENCE').selectOption('training:cyclone:2');
  await page.getByRole('button',{name:'Select multiple topics',exact:true}).click();
  await page.getByRole('button',{name:'Clear selection',exact:true}).click();
  await expect(page.getByRole('button',{name:'Build combined draft (0 topics)',exact:true})).toBeDisabled();
  await page.getByLabel('SEARCH TOPICS OR LOCATIONS').fill('Training Cyclone');
  const topics=page.getByRole('group',{name:'Select advisory topics'}).getByRole('checkbox');
  await expect(topics).toHaveCount(2);
  await topics.nth(0).check();await topics.nth(1).check();
  await page.getByLabel('SEARCH TOPICS OR LOCATIONS').fill('no-such-location');
  await expect(page.getByText('No topics match this search.',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Build combined draft (2 topics)',exact:true})).toBeEnabled();
  await page.getByLabel('SEARCH TOPICS OR LOCATIONS').clear();
  await page.screenshot({path:'test-results/multiple-topic-selection.png',fullPage:true});
  await page.getByRole('button',{name:'Build combined draft (2 topics)',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'2 topics combined into one draft'})).toBeVisible();
  await page.getByRole('button',{name:'Open draft',exact:true}).click();
  await expect(page.locator('.script-text')).toContainText('Training Cyclone');
  const dashboard=await (await request.get('/api/dashboard')).json();
  const combined=dashboard.scripts.find((s:{selected_advisory_ids?:string[]}) => s.selected_advisory_ids?.length===2);
  expect(combined.chapters).toHaveLength(2);
  expect(combined.broadcast_eligible).toBe(false);
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await page.getByText('Continue an existing script or saved video', {exact:true}).click();
  const production=await (await request.get('/api/production')).json();
  if(production.user_report.available){
    await expect(page.getByLabel('Your narrated geographic weather edit')).toBeVisible();
    await expect(page.getByRole('link',{name:'Download revised video',exact:true})).toBeVisible();
    const artifact=await request.get('/api/production/user-report/video',{headers:{Range:'bytes=0-1023'}});
    expect(artifact.status()).toBe(206);
    expect((await artifact.body()).length).toBe(1024);
  }
});

test('Create Video builds ordered flowing narration and restores unfinished work in one tab', async ({page,request})=>{
  await request.post('/api/training/load');
  await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await expect(page.getByLabel('SCRIPT FOR NEW PLAN')).not.toBeVisible();
  await page.getByLabel('Bulletin target length').selectOption('60');
  await page.getByRole('button',{name:/Show \d+ older or expired/}).click();
  const topics=page.getByRole('group',{name:'Bulletin stories',exact:true});
  await (await storyCheckbox(page,/training:cyclone:1$/)).check();
  await topics.getByRole('checkbox',{name:/training:cyclone:2$/}).check();
  await page.getByRole('button',{name:'Move story 2 up',exact:true}).click();
  const response=page.waitForResponse(r=>r.url().endsWith('/api/newsroom/runs')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Build flowing bulletin (2 stories)',exact:true}).click();
  const script=await (await response).json();
  expect(script.selected_advisory_ids).toEqual(['training:cyclone:2','training:cyclone:1']);
  expect(script.bulletin.coverage).toBe('needs_more_material');
  await expect(page.getByRole('heading',{name:'Your complete narration',exact:true})).toBeVisible();
  await expect(page.locator('#bulletin-narration')).toContainText('not padded');
  await expect(page.locator('#production-voiceover')).toBeVisible();
  await expect(page.getByLabel('Video title')).toHaveValue('Weather bulletin · 2 stories');
  const originalPlan=await page.getByLabel('PRODUCTION SCENE PLAN',{exact:true}).inputValue();
  await page.getByRole('button',{name:'Edit narration',exact:true}).click();
  const unfinished=script.text+'\n\nAn unfinished editorial note.';
  await page.getByLabel('EDIT COMPLETE NARRATION').fill(unfinished);
  await page.getByLabel('Bulletin editor name').fill('Local editor');
  await page.getByLabel('Bulletin revision note').fill('Unfinished narration revision');
  await page.reload();
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await expect(page.getByLabel('EDIT COMPLETE NARRATION')).toHaveValue(unfinished);
  await expect(page.getByLabel('Bulletin editor name')).toHaveValue('Local editor');
  await expect(page.getByLabel('Bulletin revision note')).toHaveValue('Unfinished narration revision');
  await expect(page.getByLabel('Bulletin target length')).toHaveValue('60');
  await expect(page.getByLabel('PRODUCTION SCENE PLAN',{exact:true})).toHaveValue(originalPlan);
  await expect(page.locator('#production-voiceover')).toBeVisible();
  await page.getByRole('button',{name:'Discard edits',exact:true}).click();
  await page.screenshot({path:'test-results/create-video-bulletin.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});


test('Create Video imports polished narration with per-paragraph sources', async ({page,request})=>{
  await request.post('/api/training/load');await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  const topics=page.getByRole('group',{name:'Bulletin stories',exact:true});
  await (await storyCheckbox(page,/training:cyclone:1$/)).check();
  await topics.getByRole('checkbox',{name:/training:cyclone:2$/}).check();
  await page.getByRole('button',{name:'Build flowing bulletin (2 stories)',exact:true}).click();
  await expect(page.getByRole('button',{name:'Copy source pack',exact:true})).toBeEnabled();
  const text='Florida residents should review the first storm report and its official guidance.\n\nThe second report gives a later update with its own issue time and measurements.';
  await page.getByLabel('Paste final script',{exact:true}).fill(text);
  await page.getByRole('button',{name:'Match paragraphs to sources',exact:true}).click();
  const first=page.locator('section[aria-label="Polished narration workflow"] details').filter({hasText:'Paragraph 1'});
  await expect(first).toBeVisible();
  if(!await first.locator('select').isVisible())await first.locator('summary').click();
  await page.getByLabel('Source for paragraph 1',{exact:true}).selectOption('training:cyclone:1');
  const second=page.locator('section[aria-label="Polished narration workflow"] details').filter({hasText:'Paragraph 2'});
  if(!await second.locator('select').isVisible())await second.locator('summary').click();
  await page.getByLabel('Source for paragraph 2',{exact:true}).selectOption('training:cyclone:2');
  await page.getByLabel('Final script editor',{exact:true}).fill('Local editor');
  const response=page.waitForResponse(r=>r.url().endsWith('/polished')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Save final script & prepare scenes',exact:true}).click();
  const saved=await (await response).json();
  expect(saved.claims.map((c:any)=>c.primary_advisory_id)).toEqual(['training:cyclone:1','training:cyclone:2']);
  expect(saved.claims.every((c:any)=>c.status==='requires_verification')).toBe(true);
  await expect(page.locator('#bulletin-narration .bulletin-text')).toContainText('Florida residents');
  await expect(page.locator('#production-voiceover')).toContainText('script revision 2');
  await page.reload();await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await expect(page.getByLabel('Paste final script',{exact:true})).toHaveValue(text);
});

test('Create Video automatically saves refined narration without paragraph dropdowns or an editor check', async ({page,request})=>{
  await request.post('/api/training/load');await page.goto('/');
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  const topics=page.getByRole('group',{name:'Bulletin stories',exact:true});
  await (await storyCheckbox(page,/training:cyclone:1$/)).check();
  await topics.getByRole('checkbox',{name:/training:cyclone:2$/}).check();
  await page.getByRole('button',{name:'Build flowing bulletin (2 stories)',exact:true}).click();
  const text='The first storm report describes its winds and official guidance.\n\nThe next report provides an update. Follow the official advice for your area.';
  await page.getByLabel('Paste final script',{exact:true}).fill(text);
  const response=page.waitForResponse(r=>r.url().endsWith('/polished')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Save script & prepare automatically',exact:true}).click();
  const saved=await (await response).json();
  expect(saved.revision).toBe(2);expect(saved.preview_audit.ready).toBe(true);
  expect(saved.broadcast_eligible).toBe(false);
  expect(saved.claims.every((c:any)=>c.status==='requires_verification')).toBe(true);
  await expect(page.locator('#production-voiceover')).toContainText('script revision 2');
  await expect(page.getByRole('button',{name:'Make final video',exact:true})).toBeEnabled();
});

test('Save narration confirms unchanged text is already saved without creating another revision', async ({page,request})=>{
  await request.post('/api/training/load');
  const script=await (await request.post('/api/newsroom/runs',{data:{advisory_id:'training:cyclone:1',advisory_ids:['training:cyclone:1','training:cyclone:2'],engine:'deterministic',refresh_sources:false,bulletin:true,target_minutes:10}})).json();
  await page.goto('/');
  await page.evaluate(s=>localStorage.setItem('wetha-bulletin-builder-v1',JSON.stringify({scriptId:s.id,unsavedText:s.text,baseRevision:s.revision,editing:true,editor:'Local editor'})),script);
  await page.reload();await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await expect(page.getByLabel('EDIT COMPLETE NARRATION')).toHaveValue(script.text);
  await expect(page.getByText('No unsaved text changes.',{exact:false})).toBeVisible();
  const save=page.getByRole('button',{name:'Save narration',exact:true});
  await expect(save).toBeEnabled();await save.click();
  await expect(page.getByLabel('Narration save status')).toContainText(`Narration is already saved as revision ${script.revision}`);
  await expect(page.getByRole('button',{name:'Edit narration',exact:true})).toBeVisible();
  expect((await (await request.get(`/api/scripts/${script.id}`)).json()).revision).toBe(script.revision);
});

test('Save narration validates beside the button, maps sources automatically and preserves a successful save if scene preparation fails', async ({page,request})=>{
  await request.post('/api/training/load');
  const script=await (await request.post('/api/newsroom/runs',{data:{advisory_id:'training:cyclone:1',advisory_ids:['training:cyclone:1','training:cyclone:2'],engine:'deterministic',refresh_sources:false,bulletin:true,target_minutes:10}})).json();
  const text='The first storm report describes its winds and official guidance.\n\nThe next report provides an update. Follow the official advice for your area.';
  await page.goto('/');
  await page.evaluate(s=>localStorage.setItem('wetha-bulletin-builder-v1',JSON.stringify({scriptId:s.id,unsavedText:'Too short',baseRevision:s.revision,editing:true})),script);
  await page.reload();await page.getByRole('button',{name:'Create Video',exact:true}).click();
  const save=page.getByRole('button',{name:'Save narration',exact:true});
  await expect(save).toBeEnabled();await save.click();
  await expect(page.getByLabel('Narration save status')).toContainText('between 50 and 60,000 characters');
  await page.getByLabel('EDIT COMPLETE NARRATION').fill(text);await save.click();
  await expect(page.getByLabel('Narration save status')).toContainText('Enter your editor name before saving');
  await page.getByLabel('Bulletin editor name').fill('Local editor');
  await page.route('**/api/visuals/plans',route=>route.fulfill({status:503,json:{detail:'Test scene service unavailable'}}));
  const response=page.waitForResponse(r=>r.url().endsWith('/polished')&&r.request().method()==='POST');
  await save.click();
  const saved=await (await response).json();
  expect(saved.revision).toBe(script.revision+1);expect(saved.polished_narration).toBe(true);
  expect(saved.claims.every((c:any)=>c.primary_advisory_id)).toBe(true);
  await expect(page.getByLabel('Narration save status')).toContainText(`Narration saved as revision ${saved.revision}, but scenes could not be prepared`);
  await expect(page.locator('#bulletin-narration .bulletin-text')).toContainText('The first storm report');
  expect((await (await request.get(`/api/scripts/${script.id}`)).json()).text).toBe(text);
  await page.unroute('**/api/visuals/plans');
  await page.getByRole('button',{name:'Use this narration for video',exact:true}).click();
  await expect(page.locator('#production-voiceover')).toContainText(`script revision ${saved.revision}`);
  await expect(page.getByLabel('Narration save status').getByRole('alert')).not.toBeVisible();
});

test('Settings exposes safe storage cleanup and the actual render encoder',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Settings',exact:false}).click();
  const panel=page.getByRole('region',{name:'Storage and performance'});
  await expect(panel.getByText('Video encoding:',{exact:false})).toBeVisible();
  await expect(panel.getByRole('button',{name:'Clear scene cache',exact:true})).toBeEnabled();
  await panel.getByRole('button',{name:'Clear source response cache',exact:true}).click();
  await expect(panel.getByRole('status')).toContainText('scripts, uploads and final videos are preserved');
  await expect(panel.getByRole('button',{name:'Compact database',exact:true})).toBeEnabled();
});

test('Create Video recovers from a failed workspace load without discarding a saved draft',async({page,request})=>{
  await request.post('/api/training/load');
  const script=await(await request.post('/api/scripts',{data:{advisory_id:'training:cyclone:2'}})).json();
  const saved={ids:['training:cyclone:2'],minutes:10,scriptId:script.id,editing:true,baseRevision:script.revision,
    editor:'Recovery test',note:'Keep my work',unsavedText:'An unfinished narration stays saved while the connection recovers.'};
  await page.goto('/');
  await page.evaluate(value=>localStorage.setItem('wetha-bulletin-builder-v1',JSON.stringify(value)),saved);
  let failures=0;
  await page.route('**/api/production',async route=>{if(failures++<2)await route.abort('failed');else await route.continue();});
  await page.getByRole('button',{name:'Create Video',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry loading workspace',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Retry loading workspace',exact:true}).click();
  await expect(page.getByLabel('EDIT COMPLETE NARRATION',{exact:true})).toHaveValue(saved.unsavedText);
  await expect(page.getByLabel('Bulletin editor name',{exact:true})).toHaveValue(saved.editor);
  expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('wetha-bulletin-builder-v1')??'{}'))).toMatchObject(saved);
});


test('storage cleanup buttons fit inside the panel at desktop and narrow widths',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Settings',exact:false}).click();
  const panel=page.getByRole('region',{name:'Storage and performance'});
  const names=['Clear scene cache','Clear temporary files','Clear source response cache','Compact database'];
  await expect(panel.getByRole('button',{name:names[3],exact:true})).toBeVisible();
  for(const width of [1440,1200,1000,390]){
    await page.setViewportSize({width,height:1000});
    const bounds=await panel.boundingBox();
    for(const name of names){
      const button=panel.getByRole('button',{name,exact:true});
      await expect(button).toBeVisible();
      const box=await button.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(bounds!.x);
      expect(box!.x+box!.width).toBeLessThanOrEqual(bounds!.x+bounds!.width+1);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
});
