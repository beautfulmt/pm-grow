// Usage: node tests/report_check.cjs <report.html> <screenshot-dir>
// Checks a rendered growth report offline: no remote requests, no script errors,
// every section present, no horizontal overflow at 390/760/1360, print layout, and no-JS reading.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');
let browser;

(async () => {
  const file = path.resolve(process.argv[2]);
  const output = path.resolve(process.argv[3]);
  fs.mkdirSync(output, {recursive: true});
  const executablePath = process.env.PM_GROW_BROWSER_EXECUTABLE;
  browser = await chromium.launch({headless: true, ...(executablePath ? {executablePath} : {})});
  const page = await browser.newPage({viewport: {width: 1360, height: 1000}, deviceScaleFactor: 1});
  const errors = [], remote = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route(/^(https?|wss?):\/\//, route => { remote.push(route.request().url()); return route.abort(); });
  await page.goto(pathToFileURL(file).href);

  const sections = ['learned', 'problems', 'growth', 'next', 'evidence'];
  for (const id of sections) assert.equal(await page.locator(`section#${id}`).count(), 1, `missing section ${id}`);
  for (const label of ['【本次表现】', '【能力变化】', '【仍在练】']) {
    assert.equal(await page.locator('.tier h3', {hasText: label}).count(), 1, `missing tier ${label}`);
  }
  assert.ok((await page.locator('.problem').count()) > 0, 'problems are rendered');
  for (const problem of await page.locator('.problem').all()) {
    const css = await problem.getAttribute('class');
    assert.match(css, /status-(open|solved|partial|blocked|dropped|closed)/);
    const border = await problem.evaluate(el => getComputedStyle(el).borderLeftColor);
    assert.notEqual(border, 'rgba(0, 0, 0, 0)', 'status colour applies');
  }
  assert.equal(await page.locator('script[src], link[rel="stylesheet"], img[src^="http"], iframe').count(), 0);
  assert.equal(await page.locator('#print').isVisible(), true, 'print button appears with JS');
  for (const hash of sections) {
    await page.locator(`nav.toc a[href="#${hash}"]`).click();
    assert.equal(new URL(page.url()).hash, '#' + hash);
  }
  await page.evaluate(() => { history.replaceState(null, '', location.pathname); window.scrollTo(0, 0); });

  const widths = {};
  for (const width of [390, 760, 1360]) {
    await page.setViewportSize({width, height: 900});
    const fit = await page.evaluate(() => {
      const wide = [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > window.innerWidth + 1)
        .map(el => el.tagName + '.' + el.className).slice(0, 5);
      return {screen: window.innerWidth, body: document.documentElement.scrollWidth, wide};
    });
    assert.ok(fit.body <= fit.screen + 1, `horizontal overflow at ${width}: ${JSON.stringify(fit)}`);
    widths[width] = fit.body;
    await page.screenshot({path: path.join(output, `report-${width}.png`), fullPage: true});
  }

  await page.emulateMedia({media: 'print'});
  assert.equal(await page.locator('nav.toc').isVisible(), false, 'navigation hidden in print');
  assert.equal(await page.locator('#print').isVisible(), false, 'print button hidden in print');
  for (const id of sections) assert.equal(await page.locator(`section#${id}`).isVisible(), true, `section ${id} printed`);
  await page.pdf({path: path.join(output, 'report.pdf'), format: 'A4'});
  await page.emulateMedia({media: 'screen'});

  assert.deepEqual(errors, []);
  assert.deepEqual(remote, []);
  const noJS = await browser.newPage({javaScriptEnabled: false, viewport: {width: 1000, height: 900}});
  await noJS.goto(pathToFileURL(file).href);
  for (const id of sections) assert.equal(await noJS.locator(`section#${id}`).isVisible(), true);
  assert.equal(await noJS.locator('#print').isVisible(), false, 'print button stays hidden without JS');
  console.log(JSON.stringify({ok: true, checks: ['offline', 'no-remote-requests', 'no-script-errors', 'sections', 'two-level-tiers',
    'status-colours', 'anchors', 'responsive-390-760-1360', 'print', 'no-js-reading'], widths, screenshots: output}, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
});
