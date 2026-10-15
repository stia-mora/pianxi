# 片析服务器部署指南（Linux + Docker + 云端 API）

代码仓库：https://github.com/stia-mora/pianxi

适用于 Ubuntu 24.04 / Debian 12 等 Linux 主机，Docker Engine + Compose v2。推荐至少 2 核、4 GB 内存、30 GB 可用磁盘。采用已有云端视觉 API 和云端 ASR，无需 NVIDIA GPU、Conda 或本地模型权重。Docker 镜像包含前端、后端、FFmpeg、Chromium；旧的 Windows 命令行脚本也保留在源码中。

## 1. 准备服务器

先通过 Docker 官方说明安装 Engine 和 Compose 插件：

- Ubuntu：https://docs.docker.com/engine/install/ubuntu/
- Debian：https://docs.docker.com/engine/install/debian/

验证 `docker version` 和 `docker compose version`。以下命令假定当前用户有 Docker 权限；否则加 `sudo`。安装 Git 后：

```bash
git clone https://github.com/stia-mora/pianxi.git
cd pianxi
cp .env.example .env
mkdir -p server-secrets
chmod 700 server-secrets
docker compose build
```

构建需要访问 Docker Hub、npm、PyPI 和 Playwright 下载站。单机只启动一个应用实例，使用一个 worker，SQLite 与任务队列不支持多副本共享。

## 2. 上传独立私密包

把本机收到的 `pianxi-private-*.zip` 通过 SCP/SFTP 上传到 `pianxi/server-secrets/`。不要放入 Git、GitHub Release、网页静态目录或公共对象存储。

包中包含：视觉模型 API 地址/名称/Key、云端 ASR 地址/名称/Key、团队名称、当前存在的抖音/YouTube/哔哩哔哩 Netscape Cookie。包内自动选择 `provider=api`、`asr_provider=cloud`，不会照搬 Windows 本地模型路径。

不包含：本机管理员密码、用户表、登录会话、历史任务/报告/视频、模型权重、GitHub 凭据或系统其他软件凭据。首次部署会单独创建新管理员。此 ZIP **没有加密**，含有效凭据，只应通过可信通道传输。

在服务器上，将上传文件重命名为固定路径并允许容器用户只读：

```bash
mv server-secrets/pianxi-private-*.zip server-secrets/pianxi-private.zip
# 仅在目录里确实只有这一个目标 ZIP 时使用上述通配符。
sudo chown -R 10001:10001 server-secrets
sudo chmod 700 server-secrets
sudo chmod 600 server-secrets/pianxi-private.zip
```

如果包本来就叫 `pianxi-private.zip`，跳过 `mv`。Docker 使用 UID 10001 运行应用。

## 3. 导入并启动

```bash
docker compose run --rm --no-deps pianxi \
  python scripts/deployment_bundle.py import /run/pianxi-secrets/pianxi-private.zip
docker compose up -d
docker compose ps
docker compose logs --tail=80 pianxi
curl -I http://127.0.0.1:8765/
```

导入命令的入口会先初始化数据库和随机管理员；Cookie 导入到持久卷 `/app/data/cookies`，模型配置保存在 `/app/data/platform.sqlite3`。随后镜像升级/重建均保留。日志只输出设置数量，不输出密钥。

为避免误覆盖，已有配置时导入会失败。如果确认要替换服务器配置，先停服务、备份数据卷，再在同一导入命令末尾加 `--overwrite`。不要在运行中的采集任务期间导入。

只在私密终端查看首次登录密码：

```bash
docker compose exec pianxi cat /app/data/first-login.txt
```

通过 SSH 隧道连接后可在本机浏览器登录：

```bash
ssh -L 8765:127.0.0.1:8765 your-user@your-server
```

浏览器打开 `http://localhost:8765`，首次登录后修改密码。默认端口仅绑定服务器回环地址。

## 4. 域名与 HTTPS

把域名解析到服务器。在服务器宿主机安装 Caddy，将 `deploy/Caddyfile.example` 中域名替换为实际域名，作为 Caddy 的配置。需要开放公网 TCP 80/443；应用 8765 保持回环绑定。

```caddyfile
pianxi.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

在 `.env` 设置 `PIANXI_HTTPS=1` 并运行 `docker compose up -d`，然后重载 Caddy。Caddy 自动申请证书的条件是 DNS、端口与证书服务连通正常。启用该设置后应通过 HTTPS 域名访问；HTTP 登录无法使用 Secure Cookie。

其他反向代理需保留原始 `Host` 和请求来源头。接口有同源校验，错误的 Host 转发会产生 403。不建议直接把明文 8765 暴露公网。

## 5. 部署验收

1. `docker compose ps` 显示 healthy，首页能打开。
2. 新管理员登录后，在系统设置检测“云端 VLM”和“云端 ASR”。这两次检测会向已配置服务发请求，可能产生少量费用；不得把 API Key 或完整设置响应复制到日志。
3. 先提交一条可公开访问的短视频，确认完成采集、下载、音频、转写、视觉分析。
4. 确认视频播放、文案、画面、评论和 Markdown/JSON 导出可用。播放量未公开时显示“未提供”属预期。
5. 重启容器，确认配置和任务仍在。
6. 验证完成后删除服务器上的原 ZIP；配置已持久化。离线保留一份私密备份即可。

```bash
sudo rm -- server-secrets/pianxi-private.zip
```

本机跑通不保证服务器 IP 能访问抖音；平台可能针对数据中心 IP 或异地登录要求验证码、拒绝返回详情。出现“浏览器验证”时需在可信浏览器完成验证并更新 Cookie，不能承诺绕过平台验证。云端 API 的地址、模型、额度及可达性也需在服务器实际检测。

## 6. 更新、备份和恢复

更新源码并重建：

```bash
git pull --ff-only
docker compose up -d --build
```

Cookie 在系统设置更新后也保存在同一数据卷。更换 API Key 可在系统设置保存。普通服务器保持 `PIANXI_ALLOW_FAKE_IP=0`；只有配置可信本地 Fake-IP 代理时才设置为 `1`。

完整数据备份：先停服务，再打包 `/app/data`，避免复制活动中的 SQLite/WAL 文件。备份包含用户密码哈希、密钥和素材，按私密数据保管：

```bash
mkdir -p backups
chmod 700 backups
docker compose stop pianxi
docker compose run --rm --no-deps --user root --entrypoint sh \
  -v "$PWD/backups:/backup" pianxi \
  -c 'umask 077; tar -C /app/data -czf /backup/pianxi-data.tar.gz .'
docker compose up -d
```

恢复到停止状态的同名数据卷（会覆盖同名文件，只用于明确的备份恢复）：

```bash
docker compose stop pianxi
docker compose run --rm --no-deps --user root --entrypoint sh \
  -v "$PWD/backups:/backup:ro" pianxi \
  -c 'tar -C /app/data -xzf /backup/pianxi-data.tar.gz && chown -R 10001:10001 /app/data'
docker compose up -d
```

`docker compose down` 保留卷；**不要加 `-v`**，否则删除所有服务数据。当前私密配置包不等于全量历史数据备份。

## 7. 重新生成配置包（本机）

```powershell
.venv\Scripts\python.exe scripts\deployment_bundle.py export artifacts\pianxi-private-new.zip
```

此命令只读取平台设置和 Cookie；如输出文件已存在则拒绝覆盖。两项云端 API Key 均需已保存。

## 给服务器 Agent 的任务

直接使用仓库里的 [SERVER_AGENT_PROMPT.md](SERVER_AGENT_PROMPT.md)，补上域名和私密包绝对路径。Agent 应完成构建、配置导入、启动、验收及必要的 HTTPS 配置，再报告实际测试结果。
