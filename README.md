# Isaac-Link

《以撒的结合：忏悔＋》联机助手，支持 Windows 上 Steam 版的 2～4 人官方在线联机。

在浏览器中组队、测试延迟，为每对玩家选择连接线路，再进入 Steam 官方联机房间。

**[下载最新版本](https://github.com/BBByeah/Isaac-Link/releases/latest)**

- 玩家下载 `client` 压缩包，解压后运行“以撒联机助手.exe”。
- 部署服务器下载同版本的 `server` 压缩包。
- 当前版本为 **0.6.5**，客户端与服务端请使用同一版本。游戏测试版本：忏悔＋ J460。

## 功能

- 五种线路：IPv6 直连、IPv4 打洞、局域网、自建服务器中转、Steam 原生。
- 在连接图上为任意两人固定线路，或自动测试并选择连接方案。
- 全队延迟监视、数据抓包和四帧输入冗余。
- 服务器码成功连接后自动保存，下次启动自动填入。
- 墨绿、酒红、黑金、紫色四种主题。
- 关闭最后一个助手页面即退出程序，刷新页面可继续使用。

## 开始使用

先从 Steam 启动忏悔＋，停在主菜单，再打开助手。

### 服务器组队

向服务端管理员获取服务器码，按以下步骤操作：

1. 每人填写服务器码和自己的五字母玩家 ID，点击“连接游戏”。
2. 队友将生成的个人连接码发给主持人，由主持人添加成员。
3. 主持人点击“自动测试”，或点击两人之间的连线指定线路。
4. 等待全员显示“已接管”，进入官方联机房间。

### 使用 Radmin 或局域网

1. 全员加入同一个 Radmin 网络或局域网，完成助手组队。
2. 主持人在每个成员卡片中填写该成员的 IPv4 地址并保存，包括自己的地址。
3. 点击两人之间的连线，选择“局域网”；也可以通过“自动测试”比较线路。

局域网线路使用 UDP 27667，游戏数据直接发往填写的地址。防火墙需允许助手通过对应网络通信。

### 手动交换连接码

此模式使用 IPv6 直连或 Steam 原生线路：

1. 留空服务器码，填写玩家 ID 并连接游戏。
2. 每个人添加其他所有队友的个人连接码。
3. 双方都有公网 IPv6 时尝试直连；需要使用 Steam 时，双方将对应连线改为“Steam 原生”。
4. 各自点击“启用直连”，进入官方联机房间。

每个人独立管理自己的连接。换组时断开连接，重新交换连接码。自动选路、全队监视、输入冗余和抓包通过服务器组队模式使用。

## 输入冗余

服务器组队默认启用四帧冗余：每次发送当前输入时，带上此前三份不同的输入。接收端去重后立即交给游戏，迟到或丢失的输入可以从后续包中补齐。

输入停顿时，助手在约 50、100、200 ms 各补发一次。游戏自身的输入缓存和重发机制继续工作。

## 部署服务器

服务端需要 Python 3.10+ 和 OpenSSL，使用 TLS 协调组队、UDP 探测及中转。默认端口：

| 协议 | 端口 | 用途 |
| --- | --- | --- |
| TCP | 27668 | 组队与配置同步 |
| UDP | 27667 | 公网端点发现与中转 |

按 [服务端部署说明](docs/server-deployment.md) 生成证书和服务器码，通过 `server.coordinator_private` 启动服务，将服务器码发给玩家。

## 从源码运行

在 Windows 上安装 Python 3.13，进入项目目录：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m isaac_link.browser_app
```

启动后会自动打开网页。玩家 ID、主题和提示设置保存在 `%LOCALAPPDATA%\IsaacLink\profile.json`。

## 构建与发布

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm scripts/Isaac-Link.spec
.\.venv\Scripts\python.exe scripts/package_release.py
```

构建产物位于 `release/`，包含客户端 ZIP、服务端 ZIP 和 `SHA256SUMS.txt`。

两端共用 `isaac_link/version.py` 中的版本号。发布时更新版本、重新打包，以 `v版本号` 创建 Git 标签并上传这三个文件。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node tests/test_carrier_shutdown.cjs
```

Python 测试覆盖本机模拟组队、IPv4/IPv6 传输、选路和数据处理。Node.js 测试覆盖 Steam 接口异常与退出流程。TLS 回归测试需要额外安装 `cryptography`。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| `isaac_link/` | 客户端、传输逻辑、游戏接口和网页 |
| `server/` | 组队协调与中转服务 |
| `scripts/` | 构建、打包和界面验证 |
| `tests/` | 回归测试 |
| `docs/` | 部署说明与网络诊断 |
| `licenses/` | 第三方许可声明 |

## 许可证

[MIT](LICENSE)。第三方依赖见 [许可说明](licenses/THIRD_PARTY_NOTICES.md)。
