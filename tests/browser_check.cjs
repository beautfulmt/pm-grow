const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');
const normal = value => value.normalize('NFKC').toLocaleLowerCase();
let browser;

(async () => {
  const file = path.resolve(process.argv[2]);
  const output = path.resolve(process.argv[3]);
  fs.mkdirSync(output, {recursive:true});
  const executablePath = process.env.PM_GROW_BROWSER_EXECUTABLE;
  browser = await chromium.launch({headless:true,...(executablePath ? {executablePath} : {})});
  const page = await browser.newPage({viewport:{width:1360,height:1000},deviceScaleFactor:1});
  const errors = [], remote = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(/^https?:\/\//, route => { remote.push(route.request().url()); return route.abort(); });
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(() => document.querySelectorAll('article[data-topic]').length > 0);
  const topics = await page.locator('article[data-topic]').evaluateAll(articles => articles.map(article => ({
    id:article.id,
    title:article.querySelector('h2').textContent.trim(),
    text:article.textContent,
    paragraphs:[...article.querySelectorAll('section p')].map(p => p.textContent.trim()).filter(Boolean),
  })));
  const total = topics.length;
  const sourceUrls = await page.locator('.source-url').count();
  assert.equal(await page.locator('article:visible').count(), total);
  assert.equal(await page.locator('nav li[data-topic]:visible').count(), total);
  assert.equal(await page.locator('.source-url:visible').count(), 0);
  const queries = new Set(topics.flatMap(topic => [topic.title, ...topic.paragraphs]).map(text => text.slice(0,80)));
  const firstBody = topics[0].paragraphs[0] || topics[0].title;
  queries.add(topics[0].title + ' ' + firstBody.slice(0,80));
  for (const query of queries) {
    const terms = normal(query).trim().split(/\s+/).filter(Boolean);
    const expected = topics.filter(topic => terms.every(term => normal(topic.text).includes(term))).length;
    assert.ok(expected > 0, 'A search extracted from the handbook must match a topic');
    await page.locator('#search').fill(query);
    assert.equal(await page.locator('article:visible').count(), expected);
    assert.equal(await page.locator('nav li[data-topic]:visible').count(), expected);
  }
  let missing = 'no-such-topic-123';
  while (topics.some(topic => normal(topic.text).includes(missing))) missing += '-absent';
  await page.locator('#search').fill(missing);
  assert.equal(await page.locator('article:visible').count(), 0);
  assert.equal(await page.locator('#empty').isVisible(), true);
  await page.locator('#clear').click();
  assert.equal(await page.locator('article:visible').count(), total);
  await page.locator('nav a').last().click();
  assert.equal(new URL(page.url()).hash, '#' + topics[total - 1].id);
  assert.equal(await page.locator('nav a[aria-current="location"]').count(), 1);
  await page.locator('#search').fill(missing);
  assert.equal(await page.locator('article:visible').count(), 0);
  await page.emulateMedia({media:'print'});
  assert.equal(await page.locator('article:visible').count(), total);
  assert.equal(await page.locator('aside').isVisible(), false);
  assert.equal(await page.locator('.source-url:visible').count(), sourceUrls);
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
  assert.equal(await noJS.locator('article:visible').count(),total);
  console.log(JSON.stringify({ok:true,checks:['offline','topics','search','multiple-terms','no-results','clear','anchors','print-all','responsive','no-js-reading','no-script-errors','no-remote-resources'],screenshots:output},null,2));
})().catch(error => { console.error(error); process.exitCode=1; }).finally(async () => {
  if (browser) await browser.close();
});
