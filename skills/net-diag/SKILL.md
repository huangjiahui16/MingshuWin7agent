---
name: net-diag
description: 排查上不了网、接口连不上、DNS/代理/TLS 问题时使用
---

# 网络诊断（Win7）

## 顺序（由轻到重）
1. `net_list` 看有没有建立的连接、监听端口。
2. `run_cmd` ping 网关 / ping 8.8.8.8 / nslookup 域名 —— 分清是"没网"还是"DNS 挂了"。
3. 接口不通时先测 TCP：`powershell Test-NetConnection` 在 Win7 上不存在，改用
   `telnet 主机 443` 或 python 一行 socket 连接测试。
4. HTTPS 失败优先怀疑三件事：系统时间不准、根证书过期（KB931125）、TLS 1.2 没启用（KB3140245）。

## 报告要求
给用户结论要分三层：现象（哪个请求失败）→ 原因（DNS/超时/TLS/证书）→ 下一步（做什么）。
禁止只回一句"网络错误"。

## 代理
用户开了代理就检查 http_proxy 是否影响本机请求；很多"接口 502"其实是代理挂了。
