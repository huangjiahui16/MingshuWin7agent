---
name: win7-pitfall
description: 写脚本或调用 Win32 API 前想确认 Win7 有哪些坑时使用
---

# Win7 编程坑清单（按杀伤力排序）

1. **ctypes 必须给返回句柄的 API 设 restype**：GetDC、OpenProcess、CreateToolhelp32Snapshot
   等默认按 32 位 int 收，x64 上高位被砍 → 段错误。x86 上不暴露，客户跑 x64 才炸。
2. **编码**：系统 ANSI 是 GBK(936)。subprocess 输出要按 utf-8/gbk/utf-16 逐个试；
   写文本给用户看优先 UTF-8 带 BOM（否则记事本乱码）。
3. **路径 260 上限**：拼接前检查长度，必要时截断并提示。
4. **DPI**：不声明 DPI 感知时，125% 缩放下截图/坐标全偏移；程序已调 SetProcessDPIAware。
5. **子进程管道**：必须 communicate() 或独立读线程，否则 64KB 缓冲满会死锁。
6. **TLS**：Win7 默认不启用 TLS 1.2，需要 KB3140245；证书链要 KB931125 更新。
7. **GDI 泄漏**：截一次图至少 3 个 GDI 对象，漏 DeleteObject 几百次就花屏。
8. **会话状态**：锁屏/RDP 断开后 SendInput 无效、截图全黑，但 API 都返回成功。
9. **杀软**：360/火绒对 SendInput + TerminateProcess + 全局钩子极敏感，会被拦。
