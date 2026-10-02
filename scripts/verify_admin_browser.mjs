// Real-browser verification. Credentials and captures stay in ignored .local.
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(new URL('../admin-web/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const base=process.env.ADMIN_TEST_BASE??'http://127.0.0.1:18100';
const password=(await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE,'utf8')).trim();
const output=process.env.ADMIN_TEST_OUTPUT??'.local/admin-verification';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:process.env.ADMIN_TEST_DIRECT==='true'?['--no-proxy-server']:[]});
const context=await browser.newContext({viewport:{width:1512,height:1050}});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
const nav=name=>page.locator('.sidebar').getByRole('button',{name,exact:true});
try{
  await page.goto(base);await expect(page.getByRole('heading',{name:'回到控制室'})).toBeVisible();
  await page.screenshot({path:path.join(output,'login-desktop.png'),fullPage:true,animations:'disabled'});
  await page.getByLabel('账号',{exact:true}).fill(process.env.ADMIN_TEST_USERNAME??'owner');
  await page.getByLabel('密码',{exact:true}).fill(password);
  await page.getByRole('button',{name:'进入控制室'}).click();await page.locator('.sidebar').getByRole('button',{name:'后台数据维度',exact:true}).click();await page.locator('.sidebar').getByRole('button',{name:'总览',exact:true}).click();
  await expect(page.getByRole('heading',{name:'照看每一次相遇'})).toBeVisible();
  await expect(page.getByText('服务连接正常',{exact:true})).toBeVisible();
  await page.screenshot({path:path.join(output,'dashboard-desktop.png'),fullPage:true,animations:'disabled'});
  await nav('角色目录').click();await expect(page.locator('tbody tr').first()).toBeVisible();
  await page.locator('tbody tr').first().click();await expect(page.getByRole('tab',{name:'原始数据'})).toBeVisible();
  await page.screenshot({path:path.join(output,'characters-desktop.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('tab',{name:'编辑',exact:true}).click();await expect(page.getByRole('button',{name:'保存修改'})).toBeVisible();
  await page.locator('.detail-panel').getByRole('button',{name:'关闭详情'}).click();
  await nav('AI 角色设定').click();await expect(page.locator('tbody tr').first()).toBeVisible();
  await page.locator('tbody tr').first().click();await page.getByRole('tab',{name:'编辑',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'职业',exact:true})).toBeVisible();await page.screenshot({path:path.join(output,'ai-settings-desktop.png'),fullPage:true,animations:'disabled'});
  await page.locator('.detail-panel').getByRole('button',{name:'关闭详情'}).click();
  if(process.env.ADMIN_TEST_CREATE_FIXTURE==='true'){
    await nav('用户账户').click();await page.getByRole('button',{name:'新建',exact:true}).click();
    const panel=page.getByRole('dialog');const username='browser_'+Date.now();
    await panel.getByLabel('登录账号',{exact:true}).fill(username);await panel.getByLabel('新密码',{exact:true}).fill(password);await panel.getByLabel('显示名称',{exact:true}).fill('浏览器验证账户');
    const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/create/users')&&r.request().method()==='POST'),panel.getByRole('button',{name:'创建记录'}).click()]);
    expect(response.status()).toBe(200);const result=await response.json();await fs.writeFile(path.join(output,'created-fixture-user-id.txt'),result.result.id,{mode:0o600});
    await expect(panel).not.toBeVisible();await page.getByLabel('搜索当前分类').fill(username);await expect(page.locator('tbody tr')).toHaveCount(1);
    await page.locator('tbody tr').first().click();await page.getByRole('tab',{name:'编辑',exact:true}).click();
    const editor=page.locator('.json-field textarea');const profile=JSON.parse(await editor.inputValue());profile.display_name='浏览器编辑成功';await editor.fill(JSON.stringify(profile,null,2));await page.getByRole('button',{name:'保存修改'}).click();
    await expect(page.getByText('已完成，最新数据已刷新',{exact:true})).toBeVisible();await expect(page.locator('tbody tr')).toContainText('浏览器编辑成功');
    await page.locator('.detail-panel').getByRole('button',{name:'关闭详情'}).click();
  }
  await nav('场景预缓存').click();await expect(page.getByRole('heading',{name:'场景预缓存',exact:true})).toBeVisible();
  await nav('管理员').click();await expect(page.locator('tbody tr').first()).toBeVisible();await page.locator('tbody tr').first().click();
  await page.getByRole('button',{name:'重置密码',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'取消',exact:true}).click();await expect(page.getByRole('dialog')).not.toBeVisible();await page.locator('.detail-panel').getByRole('button',{name:'关闭详情'}).click();
  await nav('总览').click();await page.setViewportSize({width:390,height:844});await expect(page.getByRole('button',{name:'打开导航'})).toBeVisible();await page.screenshot({path:path.join(output,'dashboard-mobile.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'打开导航'}).click();await nav('角色目录').click();await page.locator('tbody tr').first().click();await expect(page.locator('.detail-panel').getByRole('button',{name:'关闭详情'})).toBeVisible();await page.screenshot({path:path.join(output,'detail-mobile.png'),fullPage:true,animations:'disabled'});await page.locator('.detail-panel').getByRole('button',{name:'关闭详情'}).click();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);expect(errors).toEqual([]);
  const result={passed:true,base,real_api:true,paid_calls:0,page_errors:errors,viewport_checks:['1512×1050','390×844']};await fs.writeFile(path.join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close()}
