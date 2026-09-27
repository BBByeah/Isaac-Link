以撒联机助手 · 独立服务端部署

需要 Linux、Python 3.10 或更新版本，以及 openssl。无第三方 Python 依赖。
以下操作在你自己的服务器上执行，使用专用普通用户运行。

1. 把服务端压缩包解压到准备长期使用的目录，进入该目录。
2. 生成证书、访问密钥和连接码：
   python3 -m server.server_setup --host 你的公网IPv4或域名
3. 在云安全组和系统防火墙放行 TCP 27668、UDP 27667。
4. 启动服务：
   python3 -m server.coordinator_private --cert server.crt --key server.key --access-key-file access.key
5. 将 server-connection-code.txt 的内容单独发给允许使用服务器的玩家。
   同一队伍需要使用同一个服务器连接码。

后台常驻可以通过 systemd 管理上述启动命令；WorkingDirectory 设置为解压目录，
User 设置为部署用户，Restart 设置为 on-failure。
修改端口时，在生成连接码和启动命令中同时指定 --port、--udp-port，并放行对应端口。

server.key 是证书私钥，access.key 是服务器访问密钥，均不要公开。
连接码包含地址、端口、公开证书指纹和访问密钥，不是加密文件；持有码者可使用服务。
不要把生成的文件放回公开发布包。原始部署包不包含任何现成服务器或访问密钥。
需要撤销旧连接码时，停止服务，替换 access.key 为新随机的 64 位十六进制值，
重新运行 server_setup.py 生成连接码后重启。不要删除已有证书和私钥。
