// 管理后台端到端冒烟测试：由 scripts/run_e2e.sh 启动后端（含演示数据）后运行。
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8765";
const PW = process.env.E2E_PASSWORD;

const browser = await chromium.launch();
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`✓ ${name}`);
};

async function loginAs(page, user) {
  await page.goto(BASE);
  await page.getByLabel("用户名").fill(user);
  await page.getByLabel("密码").fill(PW);
  await page.getByRole("button", { name: "登 录" }).click();
  await page.getByRole("button", { name: "退 出" }).waitFor();
}

try {
  const page = await (await browser.newContext()).newPage();
  await step("管理员登录", () => loginAs(page, "e2e-admin"));

  await step("评分标准草稿显示发布阻碍，发布按钮不可用", async () => {
    await page.getByRole("menuitem", { name: "评分标准" }).click();
    await page.getByRole("link", { name: "rubric-v0.1" }).click();
    await page.getByText(/项待确认规则或测试占位值，不能发布/).waitFor();
    assert.equal(await page.getByRole("button", { name: "发 布" }).isDisabled(), true);
  });

  await step("卖点卡要点合计不等于 30 时不能保存，等于 30 时保存为新版本", async () => {
    await page.getByRole("menuitem", { name: "产品与题库" }).click();
    await page.getByRole("link", { name: "少儿医疗险（演示）" }).click();
    await page.getByRole("button", { name: "基于最新版本修改" }).click();
    const price = page.locator('input[id="checklist_7_points"]');
    await price.fill("4");
    await page.getByText("分值合计 31 / 30").waitFor();
    assert.equal(await page.getByRole("button", { name: "保存为新版本（草稿）" }).isDisabled(), true);
    await price.fill("3");
    await page.getByText("分值合计 30 / 30").waitFor();
    await page.getByRole("button", { name: "保存为新版本（草稿）" }).click();
    await page.getByText("第 2 版").waitFor();
  });

  await step("生成试镜题单：4 条异议按时间点、6 道知识题", async () => {
    await page.getByRole("menuitem", { name: "试镜题单" }).click();
    await page.getByRole("button", { name: "生成题单" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("产品").click();
    await page.getByTitle("少儿医疗险（演示）").click();
    await dlg.getByLabel("评分标准版本").click();
    await page.getByTitle("rubric-v0.1（草稿）").click();
    await dlg.getByRole("button", { name: /确\s*定|OK/ }).click();
    await page.getByText(/^题单 TS/).waitFor();
    for (const t of ["04:00", "05:30", "07:00", "08:00"]) await page.getByText(t, { exact: true }).waitFor();
    assert.equal(await page.locator(".ant-list").nth(1).locator(".ant-list-item").count(), 6);
    await page.getByText(/报告会标注“非正式”/).waitFor();
  });

  const comp = await (await browser.newContext()).newPage();
  await step("合规可编辑红线词表，看不到账号管理", async () => {
    await loginAs(comp, "e2e-compliance");
    assert.equal(await comp.getByRole("menuitem", { name: "账号管理" }).count(), 0);
    await comp.getByRole("menuitem", { name: "红线词表" }).click();
    await comp.getByRole("button", { name: "基于最新版本修改" }).waitFor();
  });

  const hr = await (await browser.newContext()).newPage();
  await step("HR 能看题单但不能生成，红线词表只读", async () => {
    await loginAs(hr, "e2e-hr");
    await hr.getByRole("menuitem", { name: "试镜题单" }).click();
    await hr.getByText(/^TS/).first().waitFor();
    assert.equal(await hr.getByRole("button", { name: "生成题单" }).count(), 0);
    await hr.getByRole("menuitem", { name: "红线词表" }).click();
    await hr.getByText("仅合规角色可以编辑红线词表").waitFor();
  });

  console.log(`\n端到端测试通过：${steps.length} 步`);
} finally {
  await browser.close();
}
