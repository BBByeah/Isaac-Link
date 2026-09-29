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

## 0.7.3 线上验证（2026-09-29）

- GitHub 和 Gitee Release 均已发布客户端、服务端及签名清单；两处清单内容一致。
- Gitee 附件经过免登录完整下载，客户端 ZIP 为 97,583,728 字节，Ed25519 验证通过。
- `python scripts/verify_gitee_fallback.py --direct` 通过：使用生产 UpdateManager，拦截 GitHub 清单和安装包两个请求，实际从 Gitee API 获取清单并下载公开附件，最终状态为 ready，签名有效。直连仅绕过测试环境代理，未模拟 Gitee 响应。
- 普通环境代理路径也已成功回退获取清单；下载因代理速度缓慢而中止，未计为完整通过。上面的完整结果来自直连测试。
- 12 项更新自动测试通过，覆盖主源检查失败、签名无效、下载失败、镜像验签、取消和安装目录占用修复。

机器可读结果：[gitee-update-test-result.json](gitee-update-test-result.json)。本次验证范围为更新源回退、完整下载和签名；没有把它等同于真实 Steam 联机验收或另一轮 GUI 覆盖安装测试。
