const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const file = path.resolve(process.argv[2]);
  const output = path.resolve(process.argv[3]);
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1360,height:1000},deviceScaleFactor:1});
  const errors = [], remote = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(/^https?:\/\//, route => { remote.push(route.request().url()); return route.abort(); });
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(() => document.querySelectorAll('article').length === 2);
  assert.equal(await page.locator('article:visible').count(), 2);
  assert.equal(await page.locator('.source-url:visible').count(), 0);
  await page.locator('#search').fill('优先级');
  assert.equal(await page.locator('article:visible').count(), 1);
  await page.locator('#search').fill('优先级 证据');
  assert.equal(await page.locator('article:visible').count(), 1);
  await page.locator('#search').fill('no-such-topic-123');
  assert.equal(await page.locator('article:visible').count(), 0);
  assert.equal(await page.locator('#empty').isVisible(), true);
  await page.locator('#clear').click();
  assert.equal(await page.locator('article:visible').count(), 2);
  await page.locator('nav a').nth(1).click();
  assert.equal(new URL(page.url()).hash, '#topic-priority-tradeoffs');
  await page.locator('#search').fill('看板');
  assert.equal(await page.locator('article:visible').count(), 1);
  await page.emulateMedia({media:'print'});
  assert.equal(await page.locator('article:visible').count(), 2);
  assert.equal(await page.locator('aside').isVisible(), false);
  assert.equal(await page.locator('.source-url:visible').count(), 1);
  await page.emulateMedia({media:'screen'});
  await page.locator('#clear').click();
  await page.evaluate(() => { history.replaceState(null, '', location.pathname); window.scrollTo(0,0); });
  await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
  for (const width of [390, 760, 1360]) {
    await page.setViewportSize({width,height:950});
    const fit = await page.evaluate(() => ({
      screen:window.innerWidth,
      body:document.documentElement.scrollWidth,
      articles:[...document.querySelectorAll('article')].map(a=>a.getBoundingClientRect().width),
    }));
    assert.ok(fit.body <= fit.screen + 1, JSON.stringify(fit));
  }
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
  assert.deepEqual(errors, []);
  assert.deepEqual(remote, []);
  const noJS = await browser.newPage({javaScriptEnabled:false,viewport:{width:1000,height:900}});
  await noJS.goto(pathToFileURL(file).href);
  assert.equal(await noJS.locator('article:visible').count(),2);
  await browser.close();
  console.log(JSON.stringify({ok:true,checks:['offline','topics','search','multiple-terms','no-results','clear','anchors','print-all','responsive','no-js-reading','no-script-errors','no-remote-resources'],screenshots:output},null,2));
})().catch(error => { console.error(error); process.exitCode=1; });
