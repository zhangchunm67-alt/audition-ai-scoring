# 部署方案与运维 SOP（公司内网服务器）

适用：把本系统部署到公司内网的一台服务器上，只在内网使用，NAS 做备份。主线按 **Mac Studio（Apple 芯片，64 GB 内存）** 写；服务器是 Linux 的，差异见文末附录 A。

README 里有每一步的原理说明，本文只给按顺序执行的步骤、负责人和验收标准。每完成一步在方框里打勾，整份留档。

---

## 0. 角色与分工

| 角色 | 负责 |
|---|---|
| 部署负责人（技术） | 第 1–8 步全部操作；日常运维 |
| IT / 网络 | 固定内网 IP 或内网域名、NAS 共享和账号、防火墙、UPS |
| 系统管理员（业务） | 建账号、录入产品和话术、发布评分标准、评委排班 |
| 培训 / 法务 | 确认评分口径（README“交付状态”里的待确认项）、保存期限 |

## 1. 部署前准备清单（开工前全部到位）

- [ ] 服务器：Mac Studio，系统已更新，**单独建一个本地用户**（如 `audition`）专门跑本系统
- [ ] 固定内网 IP，或内网 DNS 名称（如 `audition.lan`）指向它 → 下文记作 `<APP_HOST>`
- [ ] NAS：单独一个共享（如 `audition-backup`），单独一个账号，只给这台服务器读写
- [ ] 公司密码管理器里建一个条目，用来存 `.env` 和 `models.env`
- [ ] （可选）企业微信 / 钉钉 / 飞书群机器人 webhook，用于备份失败告警
- [ ] UPS（开了 FileVault，断电重启后要有人到场登录）
- [ ] 服务器能访问：GitHub（拉代码）、Docker Hub（拉镜像）、Hugging Face 或模型镜像站（下模型）、Homebrew。不能上外网的，见附录 B“离线部署”

## 2. 服务器初始化（约 30 分钟）

- [ ] 打开 FileVault：系统设置 → 隐私与安全性
- [ ] 防休眠、断电后自动开机：

```bash
sudo pmset -a sleep 0 disksleep 0 autorestart 1
```

- [ ] 打开防火墙：系统设置 → 网络 → 防火墙。只放行 Docker
- [ ] 安装 Homebrew（按 brew.sh 官网的一行命令），然后：

```bash
brew install git llama.cpp
```

- [ ] 安装 Docker，二选一：
  - Docker Desktop（公司规模大的商用要订阅）：Resources 给 8 核、16 GB 内存，勾选“登录时启动”
  - Colima（免费）：

```bash
brew install colima docker docker-compose
```

```bash
colima start --cpu 8 --memory 16 --disk 60 --vm-type vz --mount-type virtiofs --mount ~/audition:w
```

```bash
brew services start colima
```

验收：`docker run --rm hello-world` 成功。

## 3. 拉代码、生成配置（约 15 分钟）

部署目录固定为 `~/audition`。**不要放在“桌面”“文稿”“下载”下面**：macOS 会拦截后台任务访问这些目录。

```bash
git clone https://github.com/zhangchunm67-alt/audition-ai-scoring.git ~/audition
```

```bash
cd ~/audition && git log --oneline -1
```

把输出的提交号记到部署记录里（回滚时要用）。

```bash
./scripts/gen_env.sh && mkdir -p data/minio data/logs
```

编辑 `~/audition/.env`，必须填写的：

| 变量 | 填什么 |
|---|---|
| `APP_HOST` | 第 1 步定的 `<APP_HOST>` |
| `BACKUP_DIR` | NAS 挂载目录，如 `/Volumes/audition-backup` |
| `BACKUP_ALERT_WEBHOOK` | 群机器人地址（可留空） |
| `APP_RETENTION_DAYS` | 未录用候选人视频保存天数，**等法务给正式值**，先保持 30 |

其余密钥由脚本随机生成，不要手改。

- [ ] **把整个 `.env` 存进密码管理器**。丢了它，数据库备份解不开，视频也无法解密

## 4. 启动服务（约 20 分钟，首次要构建镜像）

```bash
cd ~/audition && docker compose up -d --build
```

```bash
docker compose ps
```

验收：caddy、api、worker（2 个）、postgres、redis、minio 都是 running；migrate 是 exited (0)。

导入评分标准和检测配置（正式环境不要用 `seed-demo`，那会导入演示产品）：

```bash
docker compose exec api python -m app.cli init-config
```

建第一个管理员（会提示输入密码，至少 10 位）：

```bash
docker compose exec api python -m app.cli create-user --username admin --role admin --display-name 管理员
```

## 5. 启用 HTTPS（约 15 分钟 + 给每台员工电脑装证书）

导出根证书：

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./audition-root.crt
```

把 `audition-root.crt` 发给 IT，装到每台员工电脑上：

- Mac：双击加入“钥匙串访问 → 系统”，双击证书，“信任”改为“始终信任”
- Windows：双击 → 安装证书 → 本地计算机 → “受信任的根证书颁发机构”；有域控的用组策略统一下发

验收：

- [ ] 员工电脑浏览器打开 `https://<APP_HOST>`，没有安全警告，能看到登录页
- [ ] 用 admin 登录成功
- [ ] 从另一台电脑访问 `http://<APP_HOST>:8000` **打不开**（明文端口只对本机开放）

## 6. 本地模型（约 1–2 小时，主要是下载）

现状：语音识别、笑声检测已有可用的本地模型；文本、视觉、声音三类千问模型的具体版本**还没在这台机器上实测选定**，先按下面装，上线前必须做第 8 步的压测。普通话评测没有本地模型，这一条固定由评委打分。

1. 下载语音识别和笑声模型（约 1.3 GB）：

```bash
cd ~/audition && ./scripts/download_models.sh
```

2. 在 `~/audition` 下建 `models.env`，写好后 `chmod 600 models.env`，存进密码管理器：

```
LLAMA_SERVER=/opt/homebrew/bin/llama-server
MODEL_API_KEY=<一个随机长串>
LLM_MODEL=<千问文本模型 GGUF 路径或仓库名>
LLM_PORT=8081
LLM_CTX=32768
VLM_MODEL=<千问视觉模型>
VLM_PORT=8082
VLM_CTX=16384
OMNI_MODEL=<千问 Omni 模型>
OMNI_PORT=8083
OMNI_CTX=32768
```

随机串可以这样生成：`python3 -c 'import secrets;print(secrets.token_urlsafe(32))'`

3. 三个模型各装一个开机自启（`llm`、`vlm`、`omni` 各执行一次，下面以 `llm` 为例）：

```bash
sed "s|__DEPLOY_DIR__|$HOME/audition|g; s|__NAME__|llm|g" scripts/macos/com.audition.model.plist > ~/Library/LaunchAgents/com.audition.model.llm.plist
```

```bash
launchctl load ~/Library/LaunchAgents/com.audition.model.llm.plist
```

4. 在 `.env` 里把模拟模型换成本地模型（变量清单见 README“3b. 在 Mac 上运行本地模型”第 4 步），`APP_OPENAI_API_KEY` 填 `models.env` 里的 `MODEL_API_KEY`。然后：

```bash
docker compose up -d
```

验收：

- [ ] `launchctl list | grep audition` 能看到三个模型
- [ ] 容器能连上模型（每个端口各试一次）：

```bash
docker compose exec api curl -fsS -H "Authorization: Bearer $(sed -n 's/^APP_OPENAI_API_KEY=//p' .env)" http://host.docker.internal:8081/v1/models
```

- [ ] 不带 API key 访问被拒绝（上面的命令去掉 `-H ...` 那段，应返回 401）

注意：**不要**为了连通把模型改成监听 `0.0.0.0`，那样内网任何人都能调用。

## 7. 备份（约 30 分钟）

1. 挂载 NAS：访达 → 前往 → 连接服务器 → `smb://<NAS地址>/audition-backup`，勾选“记住密码”；把这个共享拖进“系统设置 → 通用 → 登录项”。
2. 放标记文件（没有它备份脚本会拒绝写入，防止 NAS 没挂上时写到本机）：

```bash
touch /Volumes/audition-backup/.audition-backup
```

3. 手动跑一次：

```bash
cd ~/audition && ./scripts/daily.sh
```

4. 装每日任务（每天 02:30：中断检查 → 到期删除 → 备份）：

```bash
sed "s|__DEPLOY_DIR__|$HOME/audition|g" scripts/macos/com.audition.daily.plist > ~/Library/LaunchAgents/com.audition.daily.plist
```

```bash
launchctl load ~/Library/LaunchAgents/com.audition.daily.plist
```

验收：

- [ ] NAS 上有 `db/audition-*.dump.enc` 和 `media/<日期时间>/`
- [ ] 管理后台“看板”顶部显示“上次成功备份”（绿色）
- [ ] 推出 NAS 后再跑一次 `./scripts/backup.sh`：脚本报失败，群机器人收到告警，看板标红。重新挂上 NAS

## 8. 上线验收（约半天）

技术验收（部署负责人）：

- [ ] 用一段真实试镜录像（或直播录播）走完全流程：上传 → 标分段 → 提交 → 等待评委打分 → 评委打分 → 出报告
- [ ] 报告能导出 PDF 和 Excel，中文正常
- [ ] 压测：连续提交 5 条，记录每条耗时和服务器内存峰值（“活动监视器”看内存压力，不能长时间是红色）。耗时超过 30 分钟或内存吃紧的，换小一号的千问模型，或把视觉条目交给评委
- [ ] 断电演练：拔电源再接上 → 有人登录 Mac → 5 分钟内服务自动恢复；之前处理中的录像在 3 小时内自动标为失败，页面上“重新处理”能跑完
- [ ] **恢复演练**：请一位非开发同事，在另一台电脑上按第 10.4 节从 NAS 恢复，能登录、能看到报告和视频。走不通的地方补进本文

业务准备（系统管理员）：

- [ ] 在“系统管理 → 账号”建好 HR、评委、校准员、合规账号。初始密码单独告诉本人，本人首次登录必须改密码
- [ ] 录入产品、卖点卡、固定话术、异议库、朗读稿
- [ ] 评分标准目前是草稿，报告会标“非正式”。培训确认完待确认项后才能发布；在此之前报告只作参考，不作录用依据
- [ ] 安排评委：每条录像要评委补打普通话标准，并确认语调、音色、节奏、激发需求、产品讲解、电梯法则、节奏与气氛等条目

---

## 9. 日常运维 SOP

### 9.1 每天（自动，无需操作）

02:30 每日任务依次：把卡住超过 3 小时的录像标为失败 → 删除到期视频 → 备份。日志在 `~/audition/data/logs/daily.log`。

### 9.2 每周一（部署负责人，5 分钟）

- [ ] 看板顶部：上次成功备份在 36 小时内（绿色）
- [ ] 看板顶部：“等待评委打分”的录像数，积压的提醒评委
- [ ] 试镜录像列表里有没有“处理失败”，有的按 9.5 处理
- [ ] 磁盘：`df -h ~/audition`，用量超过 80% 提前扩容或请法务确认能否缩短保存期限

### 9.3 每月（系统管理员 + 校准员）

- [ ] 校准与看板 → 月度抽检：抽 10–20 条，分给两位校准员背对背打分，定稿后看一致率
- [ ] 一致率低于目标的条目，继续留在评委打分名单里

### 9.4 每季度（部署负责人）

- [ ] 恢复演练一次（见 10.4），记录耗时
- [ ] 系统更新（见 9.6）；`brew upgrade`；macOS 安全更新

### 9.5 常见故障

| 现象 | 处理 |
|---|---|
| 录像“处理失败” | 打开录像看失败原因。模型连不上 → 查 `launchctl list \| grep audition` 和 `data/logs/model-*.log`，恢复后点“重新处理”。多半是系统问题，先别让候选人重录 |
| 录像一直“处理中” | 超过 3 小时会自动转失败；急的话等到 3 小时后在页面点“重新处理”，或 `docker compose restart worker`（worker 启动时会清理中断的任务） |
| 打不开网页 | `docker compose ps` 看哪个服务没在跑，`docker compose logs --tail 100 <服务名>` 看原因；`docker compose up -d` 拉起 |
| 浏览器提示证书不安全 | 那台电脑没装根证书，按第 5 步装 |
| 备份失败告警 | 多半是 NAS 没挂载：重新挂载后手动跑 `./scripts/backup.sh`。如果提示“媒体文件数骤降”，**先别删 `.file-count`**，查清本机视频为什么少了 |
| 忘了管理员密码 | `docker compose exec api python -m app.cli create-user --username admin2 --role admin --display-name 管理员2`，用新账号登录后重置原账号 |
| 候选人要求删除资料 | 管理员核实书面申请后，调用删除接口或运行 `docker compose exec api python -m app.cli erase-candidate --id <候选人编号> --reason "<申请说明>"`。不可恢复，申请材料另行存档 |

### 9.6 系统更新（有新版本时）

1. 选在没人用的时段，提前通知
2. 先备份：

```bash
cd ~/audition && ./scripts/backup.sh
```

3. 记下当前版本，然后更新：

```bash
git log --oneline -1
```

```bash
git pull origin main && docker compose up -d --build
```

数据库迁移由 migrate 服务自动执行。

4. 验收：登录、打开一份旧报告、看板备份状态正常
5. **出问题回滚**：

```bash
git checkout <第 3 步记下的提交号> && docker compose up -d --build
```

如果新版本已经改过数据库结构，回滚代码后旧代码可能读不了新库：按 10.4 用更新前那份备份恢复数据库。所以第 2 步不能省。

## 10. 恢复 SOP

### 10.1 单个服务挂了

```bash
docker compose up -d
```

### 10.2 整台机器重启后服务没起来

登录 Mac → 确认 Docker（或 Colima）已启动 → `cd ~/audition && docker compose up -d`。

### 10.3 误删了某条录像的视频

从 NAS 最近一份 `media/<日期时间>/` 快照里找回。快照里是 MinIO 加密后的文件，按原路径复制回 `data/minio/` 即可，不需要解密。

### 10.4 整机损坏，换新机器恢复

需要三样：NAS 上的 `db/` 和 `media/`、密码管理器里的 `.env`、`models.env`。

1. 新机器按第 2、3 步装好软件、拉代码（不运行 `gen_env.sh`）
2. 放回配置并恢复媒体：

```bash
cd ~/audition && cp <密码管理器里的 .env> .env && cp <密码管理器里的 models.env> models.env && chmod 600 .env models.env
```

```bash
mkdir -p data && cp -a "/Volumes/audition-backup/media/$(ls /Volumes/audition-backup/media | grep '^20' | tail -n 1)" data/minio
```

3. 恢复数据库：

```bash
docker compose up -d postgres minio
```

```bash
./scripts/restore_db.sh /Volumes/audition-backup/db/<最新的 .dump.enc 文件>
```

4. 全部启动：`docker compose up -d`
5. HTTPS 根证书会变（新机器新生成），按第 5 步重新导出、重新下发给员工电脑
6. 按第 6、7 步重装模型和每日任务
7. 验收：登录、打开旧报告和视频、看板备份状态

---

## 附录 A：服务器是 Linux（如 Ubuntu）时的差异

- Docker 直接装 Docker Engine 和 compose 插件，不需要 Docker Desktop / Colima
- 媒体目录须归 uid 1001 所有（MinIO 容器的用户）：`sudo chown -R 1001:1001 data/minio`
- 本地模型：有 NVIDIA 显卡时用带 CUDA 的 llama.cpp。**容器访问不到宿主机的 127.0.0.1**，模型改为监听 Docker 网桥地址（`ip addr show docker0` 查到的地址，通常是 `172.17.0.1`），在 `models.env` 里加 `MODEL_HOST=172.17.0.1`，并用防火墙禁止其他机器访问 8081–8083 端口；API key 照样要设
- 开机自启：用 systemd 代替 launchd。每日任务用 cron：`30 2 * * * cd /opt/audition && ./scripts/daily.sh >> data/logs/daily.log 2>&1`
- `backup.sh` 里的 macOS 弹窗通知在 Linux 上会自动跳过，告警靠群机器人
- NAS 用 `/etc/fstab` 挂载 SMB 或 NFS，挂载点里同样放 `.audition-backup` 标记文件

## 附录 B：服务器不能上外网（离线部署）

在一台能上网、和服务器同架构（Apple 芯片对 Apple 芯片，x86 对 x86）的电脑上准备：

1. 代码：`git clone` 后打包整个目录
2. 镜像：在该电脑上 `docker compose build`，然后导出全部镜像：

```bash
docker save -o audition-images.tar audition-ai-scoring:latest postgres:16 redis:7 bitnamilegacy/minio:2025.5.24 caddy:2.8
```

（镜像名以 `docker compose config --images` 的输出为准）

3. 模型：在该电脑上运行 `./scripts/download_models.sh`，连同千问的 GGUF 文件一起拷走

拷到服务器后：`docker load -i audition-images.tar`，其余按第 3–8 步，`docker compose up -d` 不加 `--build`。
