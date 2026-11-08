# 主播评分规则校准交接（更新于 2026-11-06）

## 当前目标

以 `docs/source/主播评分表-20261105.xls` 为评分规则唯一来源；按产品用 20–30 份人工标注样本校准产品讲解（S2）和各主观评分条目，校准达标前不发布自动评分。

## 已完成

### 2026-11-05（上一轮）
- 最新评分表纳入仓库；旧表 `docs/source/主播评分标准-20241025.xls` 只作历史存档。
- S2 从“卖点卡 30 + 结构 20”改为 0–50 的 `fixed_script_accuracy`，标 `CAL-S2-PRODUCT` 和 `calibration_required: true`。

### 2026-11-06（本轮）
- **配置**：`config/rubric/rubric-v0.1.yaml` 改名并升版为 `config/rubric/rubric-v0.2.yaml`（`version: rubric-v0.2`）。原来的 v0.1 配置保存在 `tests/fixtures/rubric-v0.1.yaml`，只用来测旧报告重算。所有条目按评分表改回，逐条对照见 `docs/decisions.md` 第 7 节：
  - P1：穿着、发型不符合要求直接扣 10（T1）；相貌不自动评分。
  - P3：方言一处扣 1（T1）。
  - P5、P6（恢复）、P7、S1、L1、O4：评分表写“根据主观打分”，改为 0–满分的整数直接给分，删除自定的阈值、分档、封顶和拆分。
  - S4：名称改为“逼单”，沉没成本计分。
  - O1、O2 各 3 处 × 10 = 30，O3 2 处 × 10 = 20，O4 20；删除 O5 保险知识。
  - 各维度满分 100；没有道具时 P9 不适用，人设塑造按 95 折算。
- **S2 检测器**（`backend/app/pipeline/detectors/sales.py`）：只出一条 `level` 证据，`ref="fixed_script_accuracy"`，`label` 记下固定话术版本和校准版本，引用必须能在原文定位。卖点卡没有带版本的固定话术，或没有对应话术版本的 S2 校准记录时，检测器拒绝出分（条目缺证据，不当 0 分）。
- **卖点卡**：新增 `fixed_script {version, text}` 和 `s2_calibration {version, fixed_script_version, status, train_samples, holdout_samples, holdout_agreement, anchors, note}`；新增接口 `PUT /api/cards/{id}/s2-calibration`，已发布的卡也能补登，每次修改写审计。“已验证”须至少 20 份校准样本，并有留出验证一致率。
- **提交前检查**（`backend/app/pipeline/readiness.py`）：评分标准与检测器协议对不上，或 S2 缺固定话术、缺校准记录时，提交或重新处理直接返回 422，不会跑失败后通知候选人重录。
- **其他检测器**：P1 视觉只判穿着、发型；P3 用语音评测的逐处问题按方言计次；P5、P6、P7 通过新的 `voice` 能力（能听音频的声音评价模型，目前是 Mock）给分；S1、L1、O4 由大模型直接给分；提示词升为 `prompts-v2`，都引评分表原文。
- **题单与分段**：抽题规则的知识题数默认 0；没有 O5 的评分标准不抽知识题；分段标注支持没有知识题。旧版 rubric-v0.1 不能再生成新题单，也不能提交处理。
- **报告**：模型清单记录 S2 的话术版本、校准版本和状态；校准记录未验证时报告标“非正式”。
- **管理后台**：卖点卡编辑固定话术，登记 S2 校准记录；校准员打分页对照固定话术给 S2 打 0–50 分，P1、P3 改为计次；抽题规则的知识题数可以填 0。
- **演示数据**：demo 卖点卡带演示固定话术和一份草稿校准记录 `demo-uncalibrated`（没有人工样本，只用来跑通流程）。

### 2026-11-08
- 部署方案：公司内网 Mac Studio（M5 Max、64 GB、512 GB）+ NAS 备份，见 README“在 Mac Studio 上部署”和 decisions.md T36。新增 `scripts/backup.sh`、`scripts/daily.sh`、`scripts/macos/com.audition.daily.plist`；媒体目录改为宿主机目录 `MEDIA_DIR`。
- 已用真实容器验证：MinIO 加密写入、数据库迁移、备份、恢复、缺密钥不可解密。应用镜像在 Apple 芯片上尚未跑过，首次部署按 README 检查清单确认。

## 验证状态（2026-11-06）

- `pytest`（计分引擎、流水线、后端接口，PostgreSQL 16）：447 通过，1 跳过（本机没有 Redis 的队列模式测试）。
- 前端 `npm run typecheck` 通过；`scripts/run_e2e.sh`（Playwright）18 步全部通过。
- 端到端测试发现并修复一处引擎问题：单部分 T4 条目省略 `ref` 时，校验只认部分名 `main`，导致校准员给 S2 打分被拒。

## 重要边界（不变）

- 不得把“固定话术完成准确度”替换为卖点卡覆盖率或自定的分数映射。主观评分条目同理，不得再自定分档。
- 每个产品话术不同，S2 必须按产品分别校准，不能共用未验证的阈值。改固定话术就要换版本号，并重新校准。
- 人工标注素材至少包括：产品标识、录像或逐字稿、人工 S2 分、其他条目分、评分依据或批注；原始标注另行保存，不覆盖。
- 训练集之外保留验证样本，检查 AI 与人工在 S2 分数和最终结论上是否一致；未达标的产品继续人工评分。
- P1 不评相貌，相貌也不用于自动录用结论。

## 下一步建议

1. 收集首个产品的 20–30 份人工标注样本，并确认可以用于内部校准。确定 S2 “已验证”的一致率门槛（CAL-S2-PRODUCT），以及主观条目的校准方法（CAL-SUBJECTIVE）。
2. 选型能直接听音频的声音评价模型（P5、P6、P7），实现 `VoiceRater` 接口并在 `providers/registry.py` 注册。
3. 请培训确认 `docs/decisions.md` 7.2 节的待确认项：P-P1-DRESS、Q5、P-P3-PRON、P-O-DISTINCT、Q15。语音评测供应商要能返回逐处方言或发音问题（`details.errors`）。
4. 可选：把 S2 人工标注样本做成系统内的数据集（现在只登记校准结论和样例），从金标准集直接算出留出一致率。
