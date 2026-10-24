---
name: system-check
description: 查看系统信息、判断能不能装某软件、排查卡顿和启动项时使用
---

# 系统检查

## 基础盘点
- `sys_info` 拿系统版本/位数/内存/磁盘。
- 判断软件兼容性看三点：系统位数（x86/x64）、.NET 版本、是否依赖 Win10+ API。
- Win7 SP1 是底线；没打 SP1 的机器很多现代 TLS/证书都跑不了。

## 卡顿排查
1. `proc_list` 按 CPU/内存排序，找异常进程。
2. 机械硬盘 + 内存不足会出现"换页风暴"，表现像死机：看内存占用是否长期 > 90%。
3. 启动项：`reg_query` 查 HKCU\Software\Microsoft\Windows\CurrentVersion\Run。

## 禁止
不碰驱动、不改系统服务启动类型、不写注册表（除非用户明确要求并批准）。
