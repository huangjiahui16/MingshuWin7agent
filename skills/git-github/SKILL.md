---
name: git-github
description: 用 git 提交代码、整理仓库、准备上传到 GitHub 时使用
---

# Git / GitHub

## 提交前
1. `git status` 看改动，确认没有把密钥文件（assistant.ini、api.md 里的 key）提交上去。
2. 加 .gitignore：sessions/、logs/、clip/、*.log、__pycache__/、dist/、build/。
3. 大文件（>50MB，比如便携 Python 运行时）不要进仓库，用 Releases 或 .gitignore 排除。

## 提交
- 一次提交只做一件事，message 用中文说清"改了什么、为什么"。
- 不要 `git add -A` 盲加，先看 status。

## Win7 注意
- 老版本 git（2.10 以前）对中文路径支持差，建议 2.30+ 的 32 位版。
- 提交信息里不要用 emoji（老终端/网页显示成方块）。
