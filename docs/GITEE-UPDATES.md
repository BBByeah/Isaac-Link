# Gitee 更新镜像发布流程

0.7.3 起客户端依次检查 GitHub Release 和 Gitee Contents API 中的 `updates/stable.json`。后者返回的 Base64 文件内容仍须通过内置公钥的 Ed25519 验证，不把 API 的仓库权限当作签名替代品。

检查成功后，下载依次使用签名清单中的 GitHub、Gitee 附件地址。连接错误、不完整下载或无效签名会尝试下一地址；用户取消则停止。只添加源码镜像、标签或空 Release 不构成可用的更新镜像。

## 发布顺序

1. 更新版本，构建客户端及独立更新器，运行 `scripts/release7.py --out release/v版本`。
2. 将具有仓库权限的 Gitee API 令牌保存到 `%LOCALAPPDATA%\IsaacLinkPublisher\gitee-token.txt`。令牌不进入仓库、客户端或命令行参数。Git 推送凭据不等于 API 令牌；也可在网页登录后手动上传附件。
3. 运行 `scripts/publish_gitee_release.py --folder release/v版本`。它上传客户端和服务端，匿名下载核验，取得真实镜像下载地址，重新签署双源清单，上传清单，并生成 `updates/stable.json`。只在附件可匿名下载、签名正确后写入此索引。
4. 推送代码、标签及签名索引到 Gitee 和 GitHub，运行 `scripts/publish_release.py` 发布同一组 GitHub 附件。
5. 运行 `scripts/verify_gitee_fallback.py`：拦截 GitHub 请求，实际从 Gitee 获取清单和 ZIP 并验证签名。此步骤需要线上附件；单元测试通过不代表镜像已上线。

0.7.2 及以前没有内置 Gitee 检查地址。完全无法访问 GitHub 的旧用户，需要先手动下载一次新版。

本流程在两个站点均上传完毕且回退实测通过前，不应宣称新版本已支持可用的线上镜像。Gitee Release 上传接口见 [Gitee SDK API 文档](https://gitee.com/sdk/gitee5j/blob/main/docs/RepositoriesApi.md)。
