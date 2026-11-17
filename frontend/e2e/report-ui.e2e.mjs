// 启动 frontend/e2e/fixtures/report_preview.py 后执行；只使用明确标记的界面示例。
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { mkdir, readFile } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const base = process.env.REPORT_UI_BASE_URL ?? 'http://127.0.0.1:8766';
const output = fileURLToPath(new URL('../../deliverables/report-ui-preview/', import.meta.url));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport:{width:1440,height:1100} });
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try {
 await page.goto(`${base}/reports`);
 await page.getByRole('link',{name:'陈思远（演示）'}).waitFor();
 assert(await page.getByRole('img',{name:/五维能力图/}).count() >= 1);
 assert.equal(await page.locator('.app-sidebar').getByText('我的试镜记录',{exact:true}).count(),0);
 await page.screenshot({path:output+'reports-desktop.png',fullPage:true});
 await page.getByRole('link',{name:'陈思远（演示）'}).click();
 await page.getByRole('heading',{name:'四类能力与优先改进项'}).waitFor();
 assert.equal(await page.locator('.report-ability-card').count(),4);
 assert.equal(await page.locator('.weakness-link').count(),6); // P2、S1、L1/L2、O1/O2
 assert(await page.locator('.report-profile').textContent().then(t=>t.includes('138****6280')));
 await page.screenshot({path:output+'report-desktop.png',fullPage:true});
 await page.getByRole('button',{name:/需求引导/}).click();
 assert.equal(await page.locator('table').first().locator(':scope > tbody > tr.ant-table-row').count(),1);
 await page.getByText('这里是评分证据的演示文本。',{exact:true}).waitFor();
 await page.getByRole('button',{name:'显示全部条目'}).click();
 assert.equal(await page.locator('table').first().locator(':scope > tbody > tr.ant-table-row').count(),12);
 await page.getByRole('tab',{name:'追溯信息'}).click();
 await page.getByText(/界面示例，非真实评分/).waitFor();
 await page.getByRole('tab',{name:'总览与条目'}).click();
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false);
 await page.screenshot({path:output+'report-mobile.png',fullPage:true});
 if (process.env.E2E_AVATAR_VIDEO) {
  const bytes = await readFile(process.env.E2E_AVATAR_VIDEO);
  await page.route('**/api/reports/demo-report',async route=>{const response=await route.fetch();const d=await response.json();d.candidate_video_asset_id='avatar-video';await route.fulfill({json:d});});
  await page.route('**/api/media/avatar-video',route=>route.fulfill({status:200,contentType:'video/mp4',body:bytes}));
  await page.reload();await page.locator('[title="当前报告录像截图"] img').waitFor();
  assert((await page.locator('[title="当前报告录像截图"] img').getAttribute('src')).startsWith('data:image/jpeg'));
 }
 // 头像媒体不可读时，默认图标继续显示，姓名、电话和报告不受影响。
 await page.route('**/api/reports/demo-report',async route=>{const response=await route.fetch();const d=await response.json();d.candidate_video_asset_id='missing-video';await route.fulfill({json:d});});
 await page.route('**/api/media/missing-video',route=>route.fulfill({status:410,body:'Deleted'}));
 await page.reload();await page.getByRole('heading',{name:'四类能力与优先改进项'}).waitFor();
 await page.locator('[title="暂无可用头像"]').waitFor();
 assert.equal(errors.length,0,errors.join('\n'));
 console.log('PASS: stacked identity, five radar axes, four weakest groups, ties, evidence drilldown, trace objects, mobile, deleted-avatar fallback; no page errors');
} finally { await browser.close(); }
