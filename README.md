# MailAggregator Pro

多邮箱 IMAP 聚合 + 规则打标签 + Telegram 推送的小控制台。

---

## 技术栈（简要）

- **后端**：FastAPI、SQLAlchemy（异步）、SQLite
- **前端**：React、TypeScript、Vite
- **部署**：Docker + docker-compose（一容器同时跑前后端）

---

## Docker 部署（推荐）

1. **进入目录并克隆代码**

   ```bash
   mkdir -p /opt/mail-tool
   cd /opt/mail-tool
   git clone https://github.com/gblaowang-i/MailAggregator_Pro.git .
   ```

2. **编辑 `docker-compose.yml`**

   主要修改 `environment` 段（其他保持默认即可）：

   - `ENCRYPTION_KEY`：加密密钥与登录配置（首次部署留空，会自动生成，迁移时务必一起备份）
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD`：后台登录账号密码（请改成你自己的强密码）。
   - `JWT_SECRET`：JWT 签名密钥，改成随机长字符串。
   - `API_TOKEN`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`WEBHOOK_URL`：按需填写或留空。

3. **启动服务**

   ```bash
   # 第一次或更新镜像时
   docker compose up -d --build

   # 查看运行状态和日志
   docker compose ps
   docker compose logs -f app
   ```

   默认：

   - 访问地址：`http://服务器IP:8000`
   - 数据库存储：Docker 数据卷 `mail-tool-data`（由 compose 自动创建并持久化）

4. **日常运维**

   ```bash
   # 停止
   docker compose down

   # 更新代码 + 重新部署
   git pull
   docker compose up -d --build
   ```

   如需改端口，在 `docker-compose.yml` 的 `ports` 中把 `8000:8000` 改成例如 `8080:8000`。

---

## 首次使用流程

1. **启动完成后访问控制台**

   - 浏览器打开：`http://服务器IP:8000`
   - 使用你在 `docker-compose.yml` 中配置的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。

2. **加密密钥（ENCRYPTION_KEY）的生成与迁移**

   - `docker-compose.yml` 里的 `ENCRYPTION_KEY` 可以**留空**。  
   - 第一次启动时，后端会在容器内自动生成一条合规的 Fernet 密钥，并写入 `.env`，之后一直复用。
   - **迁移 / 备份时务必一起备份**：
     - 数据卷 `mail-tool-data`（里面是 SQLite 数据库）。
     - 以及 `.env` 中自动生成的 `ENCRYPTION_KEY`（或者在部署环境里重新设置相同的值）。
   - 不建议把真正的密钥写死到仓库里，生产环境统一通过部署时的环境变量来配置。

3. **准备邮箱账号的登录信息**

   控制台里「邮箱账号 → 新建账号」需要：

   - 邮箱地址（如 `xxx@qq.com`、`xxx@gmail.com`）
   - IMAP Host / 端口（大部分常见邮箱已有预设，可直接选；也可手动修改）
   - **邮箱授权码 / 应用专用密码**（多数邮箱不支持直接使用登录密码）
   - 轮询间隔（秒）：单个账号的拉取频率，留空则使用全局默认（`POLL_INTERVAL_SECONDS`）。

4. **添加第一个账号并测试拉取**

   - 在「邮箱账号」中创建账号，填好授权码。
   - 创建完成后，等一轮自动轮询，或在「邮件列表」里选择该账号并点击「从邮箱拉取一次」进行测试。
   - 若有错误，可在：
     - 账号列表「最近错误」列查看具体异常；
     - 或在服务器上看日志：

       ```bash
       docker compose logs -f app
       ```

5. **配置 Telegram 推送（可选）**

   - 在 `.env` / `docker-compose.yml` 中填：
     - `TELEGRAM_BOT_TOKEN`
     - `TELEGRAM_CHAT_ID`
   - 重启容器后，在控制台「系统设置」里能看到当前是否已配置。
   - 在「邮箱账号 → 编辑」中：
     - 勾选「启用推送」；
     - 可选择推送模板（完整邮件 / 摘要 / 短摘要 / 仅标题）；
     - 可为每个账号单独配置 Telegram 过滤规则（允许 / 拒绝，按发件人、域名、主题、正文关键字匹配）。

   推送逻辑内置防轰炸策略：

   - 新账号首次全量同步 **不推送历史邮件**，只入库。
   - 之后轮询只推送「新增且在最近一段时间（默认 12h）内收到」的邮件。
   - 单轮每个账号有并发和数量控制，避免短时间大量通知刷屏。

6. **Webhook（可选）**

   - 在系统设置里配置 `WEBHOOK_URL` 后，每当有新邮件入库，后端会向该 URL 发送一条 JSON。
   - 可用于对接你自己的系统（如自动开工单、通知其它 IM 系统等）。

---

## 项目结构（简要）

```text
mail-tool/
├── app/                 # Python 后端
│   ├── api/             # FastAPI 路由（账号、邮件、规则、设置、统计等）
│   ├── core/            # 配置、数据库、加密、认证
│   ├── models/          # SQLAlchemy 模型
│   ├── schemas/         # Pydantic 请求 / 响应
│   ├── services/        # 邮件拉取、规则引擎、Telegram、Webhook
│   └── worker/          # 后台轮询任务
├── frontend/            # 前端工程（React/Vite，构建后由后端静态托管）
├── main.py              # FastAPI 入口，挂载 API + 前端静态资源
├── requirements.txt     # 后端依赖
├── Dockerfile           # 多阶段构建镜像
├── docker-compose.yml   # 一键启动配置（推荐只改 environment）
├── .env.example         # 环境变量示例（实际生产用 docker-compose 环境变量）
└── README.md
```

---

## 常见问题（FAQ）

- **Q: 我需要自己在本地生成 ENCRYPTION_KEY 吗？**

  **A:** 不需要。留空即可，应用会在服务器上首次启动时自动生成并写入 `.env`。  
  若之后迁移到新服务器，确保把旧服务器的 `ENCRYPTION_KEY` 一并迁移（否则以前存的密码无法解密）。

- **Q: 多人部署该项目，需要共用同一套密钥吗？**

  **A:** 每个独立部署建议有自己的 `ENCRYPTION_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`、`JWT_SECRET` 等。  
  只有在做「同一实例迁移」时，才需要保持密钥一致。

- **Q: 如何查看轮询是否正常？**

  - 控制台右上角会显示「上次轮询完成时间」。
  - 也可以直接调用：

    ```bash
    curl http://服务器IP:8000/api/health
    ```

  - 或看日志：

    ```bash
    docker compose logs -f app | grep -E "\\[poller\\]|\\[telegram\\]"
    ```

- **Q: 如何备份？**

  - 备份 Docker 卷 `mail-tool-data`（数据库）。
  - 备份 `.env` 或你在部署环境里设置的关键环境变量（尤其是 `ENCRYPTION_KEY`、`JWT_SECRET`）。

