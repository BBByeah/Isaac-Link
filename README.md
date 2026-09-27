# Isaac-Link

以撒联机助手，用于 Windows 上 Steam 版《以撒的结合：忏悔＋》官方在线联机。
已验证的游戏版本为忏悔＋ J460，其他版本尚未验证。

**[下载最新版本](https://github.com/BBByeah/Isaac-Link/releases/latest)**：普通玩家下载 `client` 压缩包，解压后运行“以撒联机助手.exe”；部署服务器下载同版本的 `server` 压缩包。

通过本机浏览器操作，支持 2～4 人。Steam 仍负责登录、邀请和官方房间；助手为玩家之间选择数据传输线路。

## 功能

- IPv6 直连、IPv4 打洞、自建服务器中转、Steam 线路。
- 连接图、手动固定线路及服务器模式下的自动测试。
- 服务器模式提供全队延迟监视、四帧捎带冗余、5/10 ms 输入副本和抓包。
- 墨绿、黑＋酒红、黑金、黑＋紫主题。
- 启动检测 IPv6，提供使用说明及“以后不再提示”。
- 关闭最后一个助手页面后自动退出后台；刷新页面不会退出。

程序没有预置公共服务器。服务器连接码由自行部署服务端的管理员提供。

四帧冗余默认启用（服务器模式）：新输入立即携带前三份不同的输入发送，接收端逐份去重并立即交给游戏。游戏重发的同一输入不会挤占四个不同输入的位置。连续发送时不再额外发 5 ms 副本；没有新输入时，在约 50、100、200 ms 做最多三次补发，原有游戏重发继续保留。游戏 `OnlineInputDelay` 不作修改。

0.6.5 加入局域网线路，协调服务端及全队客户端需统一更新到 0.6.5。不使用服务器时仍使用原有 IPv6 / Steam 直通模式。

使用 Radmin 等虚拟局域网时，主持人在每个成员卡片中填写该成员的 IPv4 地址并保存，包括主持人自己的地址。随后点击两人之间的连线选择“局域网”，或点击“自动测试”比较各条线路。地址只是告诉助手往哪里发包，不会修改网卡配置；Radmin 需已连接同一个网络，允许助手的 UDP 27667 通信。局域网游戏数据直接发往填写的地址，协调服务器只负责同步配置。

## 使用

先从 Steam 启动忏悔＋，停在主菜单。所有人使用相同版本的助手和同一种模式。

### 使用服务器

1. 每人填入同一个**服务器码**及自己的五个英文字母 ID，点击“连接游戏”。
2. 将生成的**个人连接码**发给主持人。主持人添加所有队友。
3. 主持人点击“自动测试”，或点击连线指定线路。
4. 全员已接管后，进入官方联机房间。

服务器码连接成功后自动保存在本机，下次启动自动填入。

### 不使用服务器

1. 留空服务器码，填写 ID 并连接游戏。
2. 每个人添加所有其他队友的个人连接码，然后各自点击“启用直连”。
3. 双方都有公网 IPv6 时尝试直连，否则使用 Steam 原生。IPv6 不通时，可由双方把对应连线都改成 Steam 后再启用。
4. 进入官方联机房间。

此模式需要每个人手动配置，不会同步全队设置；不提供全队监视、输入副本或完整抓包。换组需断开并重新交换连接码。

## 从源码运行

在 Windows 上安装 Python 3.13，进入项目目录：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m isaac_link.browser_app
```

游戏需要已启动；网页会自动打开。玩家 ID、主题和提示设置保存在当前 Windows 用户的 `LocalAppData\IsaacLink\profile.json`。

## 构建 Windows 程序

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm scripts/Isaac-Link.spec
.\.venv\Scripts\python.exe scripts/package_release.py
```

在 `release/` 下生成客户端 ZIP 和独立服务端 ZIP。打包脚本使用明确的文件清单，不包含本地日志、抓包或服务器密钥。

客户端和服务端共用 `isaac_link/version.py` 中的版本号。发布时更新这一处，重新构建并打包两端；压缩包名称、客户端界面、抓包记录及两端的 `--version` 均读取此版本。发布标签使用 `v版本号`，同时上传两份 ZIP 和 `SHA256SUMS.txt`。

## 部署自己的服务器

服务端使用 Python 标准库，通过 TLS 协调组队，通过 UDP 打洞及中转。
需要 Python 3.10+ 和 OpenSSL，默认放行 TCP 27668、UDP 27667。

详细步骤见 [服务端部署](docs/server-deployment.md)。首次部署在服务器上生成自己的证书、私钥、访问密钥和连接码；这些文件不能提交到 Git。

只运行 `server/coordinator_private.py` 作为公开服务入口；`server/coordinator_server.py` 和 `server/coordinator_v5.py` 是其内部实现，单独运行不会强制验证服务器连接码。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node tests/test_carrier_shutdown.cjs
```

Python 测试使用本机模拟客户端、IPv4/IPv6 回环和临时文件；第二条需安装 Node.js，用于模拟 Steam 轮询异常和退出顺序。测试不会自动接管正在运行的游戏。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| `isaac_link/` | 客户端、传输逻辑、游戏接口和网页 |
| `server/` | 独立组队协调与中转服务 |
| `scripts/` | Windows 构建和发布打包 |
| `tests/` | 本机回归测试 |
| `docs/` | 服务端部署说明 |
| `licenses/` | 第三方许可声明 |

日志和抓包可能包含玩家标识、网络地址及游戏数据。反馈问题前请检查内容，不要直接提交完整运行目录。

## 许可证

[MIT](LICENSE)。第三方依赖见 [许可说明](licenses/THIRD_PARTY_NOTICES.md)。
