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


// 先进入主要栏目，再进入栏目内页签；权限过滤后只有一个页面时直接进入。
const NAV_TARGETS = {
  "试镜录像": ["试镜管理", "/recordings"],
  "候选人": ["试镜管理", "/candidates"],
  "试镜题单": ["试镜管理", "/sheets"],
  "报告与排名": ["评分报告", "/reports"],
  "看板": ["评分报告", "/dashboard"],
  "评分标准": ["培训资料", "/rubrics"],
  "产品与题库": ["培训资料", "/products"],
  "朗读稿": ["培训资料", "/reading-scripts"],
  "红线词表": ["培训资料", "/redlines"],
  "金标准与校准": ["评分校准", "/calibration/sets"],
  "我的校准任务": ["评分校准", "/calibration/tasks"],
  "我的试镜记录": ["我的试镜记录", "/reports"],
};
const primaryMenu = (page) => page.getByRole("menu", { name: "主要栏目", exact: true });
async function navigate(page, label) {
  if (label === "账号管理" || label === "审计日志") {
    await page.getByRole("button", { name: "系统管理", exact: true }).click();
    await page.getByRole("menuitem", { name: label, exact: true }).click();
    await page.waitForURL((url) => url.pathname === (label === "账号管理" ? "/users" : "/audit"));
    return;
  }
  const [group, path] = NAV_TARGETS[label];
  await primaryMenu(page).getByRole("menuitem", { name: group, exact: true }).click();
  const groupPaths = Object.values(NAV_TARGETS).filter(([name]) => name === group).map(([, route]) => route);
  await page.waitForURL((url) => groupPaths.includes(url.pathname));
  if (new URL(page.url()).pathname !== path) {
    await page.getByRole("tab", { name: label, exact: true }).click();
  }
  await page.waitForURL((url) => url.pathname === path);
}

try {
  const page = await (await browser.newContext()).newPage();
  await step("管理员登录后仅显示四个核心栏目，默认进入试镜录像", async () => {
    await loginAs(page, "e2e-admin");
    await page.waitForURL((url) => url.pathname === "/recordings");
    assert.deepEqual(await primaryMenu(page).getByRole("menuitem").allTextContents(), ["试镜管理", "评分报告", "培训资料", "评分校准"]);
    await page.getByRole("heading", { name: "试镜录像", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "系统管理", exact: true }).count(), 1);
  });

  await step("评分标准草稿显示发布阻碍，发布按钮不可用", async () => {
    await navigate(page, "评分标准");
    await page.getByRole("link", { name: "rubric-v0.2" }).click();
    await page.getByText(/项待确认规则或测试占位值，不能发布/).waitFor();
    assert.equal(await page.getByRole("button", { name: "发 布" }).isDisabled(), true);
  });

  await step("卖点卡：固定话术带版本，改版本提示 S2 须重新校准；保存为新版本", async () => {
    await navigate(page, "产品与题库");
    await page.getByRole("link", { name: "少儿医疗险（演示）" }).click();
    await page.getByText("S2 校准 demo-uncalibrated（草稿）").waitFor();
    await page.getByRole("button", { name: "基于最新版本修改" }).click();
    const ver = page.locator('input[id="fixed_script_version"]');
    await ver.fill("demo-script-2");
    await page.getByText(/话术版本已改，原 S2 校准记录（demo-uncalibrated）不再适用/).waitFor();
    await ver.fill("demo-script-1");
    assert.equal(await page.getByText(/话术版本已改/).count(), 0);
    await page.getByRole("button", { name: "保存为新版本（草稿）" }).click();
    await page.getByText("第 2 版").waitFor();
  });

  await step("生成试镜题单：4 条异议按时间点，不抽知识题（评分表 20261105 已删除 O5）", async () => {
    await navigate(page, "试镜题单");
    await page.getByRole("button", { name: "生成题单" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("产品").click();
    await page.getByTitle("少儿医疗险（演示）").click();
    await dlg.getByLabel("评分标准版本").click();
    await page.getByTitle("rubric-v0.2（草稿）").click();
    await dlg.getByRole("button", { name: /确\s*定|OK/ }).click();
    await page.getByText(/^题单 TS/).waitFor();
    for (const t of ["04:00", "05:30", "07:00", "08:00"]) await page.getByText(t, { exact: true }).waitFor();
    assert.equal(await page.locator(".ant-list").nth(1).locator(".ant-list-item").count(), 0);
    await page.getByText(/报告会标注“非正式”/).waitFor();
  });

  const comp = await (await browser.newContext()).newPage();
  await step("合规可编辑红线词表，看不到账号管理", async () => {
    await loginAs(comp, "e2e-compliance");
    assert.equal(await comp.getByRole("button", { name: "系统管理", exact: true }).count(), 0);
    await navigate(comp, "红线词表");
    await comp.getByRole("button", { name: "基于最新版本修改" }).waitFor();
  });

  const hr = await (await browser.newContext()).newPage();
  await step("HR 能看题单但不能生成，红线词表只读", async () => {
    await loginAs(hr, "e2e-hr");
    await hr.waitForURL((url) => url.pathname === "/recordings");
    assert.deepEqual(await primaryMenu(hr).getByRole("menuitem").allTextContents(), ["试镜管理", "评分报告", "培训资料"]);
    assert.equal(await hr.getByRole("button", { name: "系统管理", exact: true }).count(), 0);
    await navigate(hr, "试镜题单");
    await hr.getByText(/^TS/).first().waitFor();
    assert.equal(await hr.getByRole("button", { name: "生成题单" }).count(), 0);
    await navigate(hr, "红线词表");
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
    assert.equal(await primaryMenu(pr).count(), 0);
    await pr.getByText(firstObjection).waitFor();
    await pr.goto(`${sheetUrl}/print?copy=candidate`);
    await pr.getByText("录制时逐条给出，不提前提供").waitFor();
    assert.equal(await pr.getByText(firstObjection).count(), 0);
    assert.equal(await pr.getByText(/\d+\s*分(?!钟)/).count(), 0); // 不含任何分值（“15 分钟”这类时长除外）
    await pr.getByText("产品讲解固定话术：").waitFor();
  });

  await step("HR 新建候选人，未登记授权时先登记，再选题单、达标线、有无道具并分片上传", async () => {
    await navigate(hr, "试镜录像");
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
    const marks = [1, 16]; // 主体段、朗读段（新版题单没有知识题）
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

  // ───────────── 里程碑 5：报告、逐句评分、导出、新主播只看本人 ─────────────
  await step("从录像打开报告：结论标签、维度分、条目与证据", async () => {
    await hr.getByRole("button", { name: "查看报告" }).click();
    await hr.getByText("王小明 的试镜报告").waitFor();
    assert.match(await hr.getByTestId("label").textContent(), /^(推荐|待定|不推荐)$/);
    await hr.getByText("非正式报告").waitFor();
    await hr.getByText("人设塑造").first().waitFor();
    await hr.getByText("P2 语言干净").waitFor();
  });

  await step("逐句评分：点句子时间跳到视频对应位置，有问题的句子附 AI 示范说法", async () => {
    await hr.getByRole("tab", { name: "逐句评分" }).click();
    const rows = hr.getByTestId("sentence");
    assert.ok((await rows.count()) > 5);
    await hr.getByText(/示范说法（AI 生成）/).first().waitFor();
    const v = hr.getByTestId("report-video");
    await v.evaluate((el) => new Promise((res) => (el.readyState >= 1 ? res() : el.addEventListener("loadedmetadata", res, { once: true }))));
    const target = rows.nth(3);
    const label = await target.locator("a").first().textContent();
    await target.locator("a").first().click();
    await hr.waitForTimeout(500);
    const t = await v.evaluate((el) => el.currentTime);
    const [mm, ss] = label.split(":").map(Number);
    assert.ok(Math.abs(t - (mm * 60 + ss)) < 2, `视频时间 ${t} 与句子时间 ${label} 对不上`);
  });

  await step("导出 PDF 与 Excel", async () => {
    const reportUrl = hr.url();
    const id = reportUrl.split("/reports/")[1];
    const pdf = await hr.request.get(`${BASE}/api/reports/${id}/pdf`);
    assert.equal(pdf.status(), 200);
    assert.equal((await pdf.body()).subarray(0, 5).toString(), "%PDF-");
    await navigate(hr, "报告与排名");
    await hr.getByText("王小明").waitFor();
    const xlsx = await hr.request.get(`${BASE}/api/reports/export.xlsx`);
    assert.equal(xlsx.status(), 200);
    assert.match(xlsx.headers()["content-type"], /spreadsheetml/);
  });

  await step("管理员建新主播账号，HR 关联后新主播只看到本人记录", async () => {
    await navigate(page, "账号管理");
    await page.getByRole("button", { name: "新建账号" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("用户名").fill("e2e-anchor");
    await dlg.getByLabel("姓名").fill("王小明");
    await dlg.getByLabel("角色").click();
    await page.getByTitle("新主播").click();
    await dlg.getByLabel("初始密码").fill(PW);
    await dlg.getByRole("button", { name: /确\s*定|OK/ }).click();
    await page.getByText("已创建").waitFor();
    await navigate(hr, "候选人");
    await hr.getByRole("cell", { name: "王小明" }).click();
    await hr.getByText("关联新主播账号").waitFor();
    await hr.locator(".ant-drawer .ant-select", { hasText: "录用后关联本人" }).click();
    await hr.getByTitle("王小明（e2e-anchor）").click();
    await hr.getByText("已关联").waitFor();
    const an = await (await browser.newContext()).newPage();
    await loginAs(an, "e2e-anchor");
    await an.waitForURL((url) => url.pathname === "/reports");
    assert.deepEqual(await primaryMenu(an).getByRole("menuitem").allTextContents(), ["我的试镜记录"]);
    assert.equal(await an.getByRole("button", { name: "系统管理", exact: true }).count(), 0);
    await navigate(an, "我的试镜记录");
    await an.getByRole("link", { name: "王小明" }).click();
    await an.getByText("王小明 的试镜报告").waitFor();
    assert.equal(await primaryMenu(an).getByRole("menuitem", { name: "试镜管理", exact: true }).count(), 0);
  });

  // ───────────── 里程碑 6：金标准、背对背打分、对比、看板 ─────────────
  await step("管理员建金标准集、加入样本、分配 2 位校准员", async () => {
    await navigate(page, "金标准与校准");
    await page.getByRole("button", { name: "新建金标准集" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("名称").fill("上线前金标准（演示）");
    await dlg.getByLabel("评分标准版本").click();
    await page.getByTitle("rubric-v0.2").click();
    await dlg.getByRole("button", { name: /确\s*定|OK/ }).click();
    await page.getByRole("heading", { name: "上线前金标准（演示）" }).waitFor();
    await page.locator(".ant-select", { hasText: "选择已出报告的录像加入" }).click();
    await page.getByTitle(/王小明/).click();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "加入样本" }).click();
    await page.getByRole("cell", { name: "王小明" }).waitFor();
    await page.locator(".ant-select", { hasText: "选 2–3 位校准员" }).click();
    await page.getByTitle("校准员1").click();
    await page.getByTitle("校准员2").click();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "分配给全部样本" }).click();
    await page.getByText("已分配").waitFor();
  });

  async function scoreAsCalibrator(user) {
    const c = await (await browser.newContext()).newPage();
    await loginAs(c, user);
    await c.waitForURL((url) => url.pathname === "/calibration/tasks");
    assert.equal(await primaryMenu(c).getByRole("menuitem", { name: "评分报告", exact: true }).count(), 0); // 校准员看不到 AI 报告
    await navigate(c, "我的校准任务");
    await c.getByRole("link", { name: /^TS/ }).first().click();
    await c.getByTestId("item-P1").waitFor();
    await c.evaluate(() => {
      const skip = new Set(["答错", "没回答", "钩子不实或诱导", "主体段口音明显"]);
      for (const item of document.querySelectorAll('[data-testid^="item-"]')) {
        for (const g of item.querySelectorAll(".ant-radio-group")) g.querySelector(".ant-radio-button-wrapper")?.click();
        for (const cb of item.querySelectorAll(".ant-checkbox-wrapper")) if (!skip.has(cb.textContent.trim())) cb.click();
      }
    });
    for (const [id, v] of [["S2", "40"], ["L1", "15"], ["O4", "14"]]) await c.getByTestId(`item-${id}`).locator("input").fill(v); // 0–满分直接打分
    await c.getByTestId("item-P2").getByRole("button", { name: "+ 那么" }).click(); // 计次类：看到一次点一次
    await c.getByRole("button", { name: "提 交" }).click();
    await c.getByRole("button", { name: /确\s*定|OK/ }).click();
    const ok = c.getByText("已提交。所有校准员提交后");
    const err = c.locator(".ant-message-error");
    await Promise.race([ok.waitFor(), err.waitFor()]);
    if (await err.count()) throw new Error(`校准提交被拒绝：${await err.first().textContent()}`);
  }

  await step("两位校准员背对背打分并提交（不看 AI 结果）", async () => {
    await scoreAsCalibrator("e2e-cal1");
    await scoreAsCalibrator("e2e-cal2");
  });

  await step("金标准定稿，显示与 AI 的逐项对比和一致率", async () => {
    await page.reload();
    await page.getByText("已定稿").first().waitFor();
    await page.getByText(/维度档位相差 ≤ 1 档/).waitFor();
    await page.getByRole("cell", { name: "王小明" }).click();
    await page.getByText("金标准总档位").waitFor();
    await page.getByText("AI 总档位").waitFor();
  });

  await step("看板：一致率与效率", async () => {
    await page.keyboard.press("Escape");
    await navigate(page, "看板");
    await page.getByText("上线前金标准（演示）").waitFor();
    await page.getByRole("tab", { name: "效率" }).click();
    await page.getByText("处理时长（分钟）中位数 / p95 / 最长").waitFor();
    await page.getByText("各条目低置信比例").waitFor();
  });

  console.log(`\n端到端测试通过：${steps.length} 步`);
} finally {
  await browser.close();
}
