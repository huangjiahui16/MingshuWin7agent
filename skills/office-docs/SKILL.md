---
name: office-docs
description: 读取或生成 Word/Excel/PPT 内容、从文档里提取文字和表格时使用
---

# 办公文档处理

## 读
- .docx/.xlsx/.pptx 是 zip：用标准库 zipfile + 解析 XML 取文字，不需要装 Office。
- .doc/.xls 是老二进制格式，只能启发式提取（找 UTF-16LE 文本片段），结果不完整要说明。
- 大文档先取目录/前 N 段，别整篇塞进上下文（单条结果上限 1.5K 字符）。

## 写
- 首选生成 .docx（用 zipfile 手工拼最小 OOXML），比 CSV 更不容易被 Excel 转码搞坏。
- Excel 导出优先 .csv，但要显式写 UTF-8 BOM，否则 Win7 Excel 打开中文全是乱码。
- 生成完必须把文件路径告诉用户，并用 `open_path` 打开给人看。

## 坑
- 用户机器可能没装 Office：不要假设可以调用 COM（Word.Application）。
- 文件名里的中文在 cmd 里要加引号；写文件时用 UTF-8。
