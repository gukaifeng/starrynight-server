import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(new URL('../admin-web/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const output=process.env.ADMIN_TEST_OUTPUT??'.local/voice-timings-browser';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-proxy-server']});
const page=await browser.newPage({viewport:{width:1512,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(process.env.ADMIN_TEST_BASE??'http://127.0.0.1:18100');
 await page.getByLabel('账号',{exact:true}).fill('owner');await page.getByLabel('密码',{exact:true}).fill((await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE,'utf8')).trim());await page.getByRole('button',{name:'进入控制室'}).click();
 await page.locator('.sidebar').getByRole('button',{name:'语音耗时',exact:true}).click();
 await page.locator('.voice-trace-item').first().click();await expect(page.locator('.voice-waterfall')).toBeVisible();
 await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
 await page.getByLabel(/显示全部/).check();
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'完整 JSON'}).click();const file=await download;await file.saveAs(path.join(output,'trace.json'));
 const trace=JSON.parse(await fs.readFile(path.join(output,'trace.json'),'utf8'));expect(trace.trace_id).toBeTruthy();expect(trace.spans.length).toBeGreaterThan(0);
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.locator('.sidebar').evaluate(el=>el.getBoundingClientRect().right)).toBeLessThanOrEqual(1);expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});expect(errors).toEqual([]);
 const report={passed:true,paid_calls:0,page_errors:errors,trace_id:trace.trace_id,spans:trace.spans.length,viewports:['1512×1050','390×844']};await fs.writeFile(path.join(output,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}
