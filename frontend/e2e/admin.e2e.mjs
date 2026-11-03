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

  // ───────────── 里程碑 3：登记候选人和授权、上传、标分段、提交、打印题单 ─────────────
  const sheetUrl = page.url();
  const sheetCode = (await page.getByText(/^题单 TS/).textContent()).replace("题单 ", "").trim();
  const firstObjection = (await page.locator(".ant-list").first().locator(".ant-list-item").first().textContent()).replace(/^\d\d:\d\d/, "").trim();

  await step("打印题单：工作人员联有异议，候选人联不含异议和分值", async () => {
    const pr = await (await browser.newContext()).newPage();
    await loginAs(pr, "e2e-admin");
    await pr.goto(`${sheetUrl}/print?copy=staff`);
    await pr.getByText("主体段异议（到时间点时提出）").waitFor();
    await pr.getByText(firstObjection).waitFor();
    await pr.goto(`${sheetUrl}/print?copy=candidate`);
    await pr.getByText("录制时逐条给出，不提前提供").waitFor();
    assert.equal(await pr.getByText(firstObjection).count(), 0);
    assert.equal(await pr.getByText(/\d+\s*分(?!钟)/).count(), 0); // 不含任何分值（“15 分钟”这类时长除外）
    await pr.getByText("必讲要点：").waitFor();
  });

  await step("HR 新建候选人，未登记授权时先登记，再选题单、达标线、有无道具并分片上传", async () => {
    await hr.getByRole("menuitem", { name: "试镜录像" }).click();
    await hr.getByRole("button", { name: "上传录像" }).click();
    await hr.getByRole("button", { name: "新 建" }).click();
    const dlg = hr.getByRole("dialog");
    await dlg.getByLabel("姓名").fill("王小明");
    await dlg.getByLabel("手机号（可选）").fill("13700001111");
    await dlg.getByRole("button", { name: /确\s*定|OK/ }).click();
    await hr.getByText("该候选人还没有登记书面同意，未登记不能上传").waitFor();
    await hr.getByLabel("同意书版本").fill("consent-v1");
    await hr.getByRole("button", { name: "登 记" }).click();
    await hr.getByText("consent-v1，签署于").waitFor();
    await hr.getByLabel("试镜题单").click();
    await hr.getByTitle(new RegExp(sheetCode)).click();
    await hr.getByText("新主播内部试播（总档位 < 15）").click();
    await hr.getByText("有", { exact: true }).click();
    await hr.locator('input[type="file"]').last().setInputFiles(process.env.E2E_VIDEO);
    await hr.getByRole("button", { name: "开始上传" }).click();
    await hr.getByText("保存分段").waitFor({ timeout: 30000 });
  });

  await step("边看边标分段和异议时间，提交后自动评分完成", async () => {
    const setTime = (sec) => hr.locator('[data-testid="marker-video"]').evaluate((v, t) => { v.currentTime = t; }, sec);
    const tables = hr.locator(".ant-table");
    const segRows = tables.nth(0).locator("tbody tr");
    const marks = [1, 9, 10, 11, 12, 13, 14, 16];
    for (let i = 0; i < marks.length; i++) {
      await setTime(marks[i]);
      await segRows.nth(i).getByRole("button", { name: "设为当前时间" }).click();
    }
    const objRows = tables.nth(1).locator("tbody tr");
    const objs = [3, 4.5, 6, 7];
    for (let i = 0; i < objs.length; i++) {
      await setTime(objs[i]);
      await objRows.nth(i).getByRole("button", { name: "设为当前时间" }).click();
    }
    await hr.getByRole("button", { name: "保存分段" }).click();
    await hr.getByText("分段已保存").waitFor();
    await hr.getByRole("button", { name: "提交处理" }).click();
    await hr.getByRole("button", { name: /确\s*定|OK/ }).click();
    await hr.getByText("已出报告").waitFor({ timeout: 90000 }); // inline 模式：提交后同步跑完 Mock 流水线
    await hr.getByText("评分已完成").waitFor();
  });

  await step("刷新后视频经后端代理播放（Range 请求）", async () => {
    const media = [];
    hr.on("response", (r) => r.url().includes("/api/media/") && media.push(`${r.status()} ${r.request().headers()["range"] ?? ""}`));
    await hr.reload();
    await hr.locator("video").first().waitFor();
    const ok = await hr.locator("video").first().evaluate((v) => new Promise((res) => {
      if (v.readyState >= 1) return res(true);
      v.addEventListener("loadedmetadata", () => res(true), { once: true });
      v.addEventListener("error", () => res(false), { once: true });
      setTimeout(() => res(false), 15000);
    }));
    const diag = await hr.locator("video").first().evaluate((v) => ({ rs: v.readyState, ns: v.networkState, err: v.error?.code, msg: v.error?.message }));
    assert.equal(ok, true, `视频未能加载：${JSON.stringify(diag)}；媒体请求：${media.join(", ")}`);
    assert.ok(media.some((m) => m.startsWith("206")), `应有 206 区间响应：${media.join(", ")}`);
    assert.match(await hr.locator("video").first().getAttribute("src"), /^\/api\/media\//);
  });

  console.log(`\n端到端测试通过：${steps.length} 步`);
} finally {
  await browser.close();
}
