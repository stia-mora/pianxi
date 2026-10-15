# wx_channel 微信电脑端补丁构建

片析调用 wx_channel 的 API。参考版本 `1d494115df37320c6bf524baf1977dc669797d5c` 配置了 `secret_token` 后，页面 API 客户端读取 `window.__WX_LOCAL_TOKEN__`，但上游未赋值，导致 WebSocket 被拒绝。`deploy/wx-channel-local-auth.patch` 在客户端执行前注入经过 JSON/HTML 转义的令牌，并包含回归测试；无需关闭鉴权。

以下命令在 **Windows 微信电脑**执行。需要 Git、Go 1.24.3 和 MinGW-w64 GCC。本次在 Go 1.24.3 + WinLibs UCRT GCC 验证；现代 GCC 需使用 C11，并应用 Windows 头文件兼容补丁。Go 可从 [官方下载页](https://go.dev/dl/) 获取并校验 SHA256。

在片析仓库根目录运行：

```powershell
$pianxiRoot = (Get-Location).Path
git clone https://github.com/nobiyou/wx_channel.git output/references/wx_channel
Set-Location output/references/wx_channel
git checkout 1d494115df37320c6bf524baf1977dc669797d5c
git apply --check "$pianxiRoot/deploy/wx-channel-local-auth.patch"
git apply "$pianxiRoot/deploy/wx-channel-local-auth.patch"
git apply "$pianxiRoot/deploy/wx-channel-mingw.patch"

# 上游提交遗漏了 go:embed 所需的 DLL，从对应模块版本取回。
$sunnyModule = go mod download -json github.com/qtgolang/SunnyNet@v1.0.3 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or !$sunnyModule.Dir) { throw 'SunnyNet download failed' }
Copy-Item -LiteralPath (Join-Path $sunnyModule.Dir 'Resource/nfapi/dll') `
  -Destination 'pkg/sunnynet/Resource/nfapi/dll' -Recurse

$env:CGO_CFLAGS = '-O2 -g -std=gnu11'
go test -tags nosqlite -ldflags="-extldflags '-static'" ./internal/handlers -run TestInjectedClientReceivesEscapedLocalToken -count=1
if ($LASTEXITCODE -ne 0) { throw 'Local auth test failed' }
go build -tags nosqlite -ldflags="-s -w -extldflags '-static'" -o wx_channel-pianxi.exe .
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
```

已存在的参考仓库不应再次 clone 或覆盖，先核对工作目录和修改。上游将来修复此问题后应重新评估补丁；`git apply --check` 失败时不要强行覆盖。

`nosqlite` 是 torrent 存储模块提供的构建选项，避开它与 wx_channel 自身 SQLite 的重复链接符号；wx_channel 自身的数据库仍保留。此构建仅验证视频号分享下载用途。

按 [视频号接入指南](WECHAT_CHANNELS.md) 创建自己的 `config.yaml`，配置随机 `secret_token`；无云端管理需求时设置 `cloud_enabled: false`、`radar_enabled: false`、`auto_open_channels: false`。以管理员身份启动构建的程序，并使用 `--config` 指定这个 YAML 文件。程序会安装证书和流量代理驱动，运行前需由电脑使用者授权；片析后端不会代为执行。

保持微信登录，打开视频号页面并刷新一次，确保新脚本加载。片析设置中填写同一个令牌并检测连接。不要将真实配置、令牌、微信页面签名 URL 或运行日志提交到 GitHub。

这些补丁仅用于参考项目，未将其全部源码或驱动二进制合入片析。依赖的源码和二进制授权应按各上游许可证处理。
