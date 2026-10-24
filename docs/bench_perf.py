# -*- coding: utf-8 -*-
"""跑 10 个模拟任务，测三段耗时占比：本地执行 / 模型网络 / 界面渲染。

用法（项目根目录）：
    python docs\\bench_perf.py

结论用途：判断"本地读写慢"到底是真慢，还是其实在等模型返回。
模型用固定延迟模拟（默认 500ms/次，接近真实 DeepSeek 往返），不联网。
"""
import os
import sys
import time
import configparser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import win7_assistant as engine          # noqa: E402

TASKS = 10
MODEL_MS = 500          # 模拟一次模型往返
TEST_DIR = os.path.join(ROOT, "tests", "_bench_tmp")
os.makedirs(TEST_DIR, exist_ok=True)

# 造点素材：200 个文件 + 一个较大的文本
sample_dir = os.path.join(TEST_DIR, "folder")
os.makedirs(sample_dir, exist_ok=True)
for i in range(200):
    with open(os.path.join(sample_dir, "file_%03d.txt" % i), "w", encoding="utf-8") as f:
        f.write(("第 %d 个文件的中文内容。" % i) * 30)
big = os.path.join(TEST_DIR, "big.txt")
with open(big, "w", encoding="utf-8") as f:
    f.write("中文行内容测试" * 40000)

cfg = configparser.ConfigParser(interpolation=None)
for sec in ("llm", "assistant", "agent", "memory"):
    cfg.add_section(sec)
cfg.set("agent", "max_steps", "6")
cfg.set("agent", "tool_output_chars", "1500")
cfg.set("memory", "enabled", "false")
cfg.set("assistant", "skills_enforced", "false")

PLAN = [
    [{"id": "c1", "function": {"name": "list_dir",
                               "arguments": '{"path": "%s"}' % sample_dir.replace("\\", "\\\\")}}],
    [{"id": "c2", "function": {"name": "read_file",
                               "arguments": '{"path": "%s", "max_chars": 4000}'
                                            % big.replace("\\", "\\\\")}}],
    [{"id": "c3", "function": {"name": "search_files",
                               "arguments": '{"pattern": "file_1*.txt", "path": "%s"}'
                                            % sample_dir.replace("\\", "\\\\")}}],
]

state = {"task": 0, "step": 0}


def fake_chat(cfgx, messages, tools=None, on_delta=None, stop_event=None):
    """每个任务 4 次模型往返：3 次给工具 + 1 次收尾。"""
    time.sleep(MODEL_MS / 1000.0)
    step = state["step"]
    state["step"] += 1
    if step < len(PLAN):
        return {"content": "", "tool_calls": PLAN[step]}
    return {"content": "已完成：看了一下目录、读了大文件、搜了文件。", "tool_calls": []}


engine._chat_raw_impl = fake_chat
try:
    engine.limits.set_perf_path("")     # 不污染正式 perf.jsonl
except Exception:
    pass

mem = engine.Memory(memory_path=os.path.join(TEST_DIR, "m.json"),
                    facts_path=os.path.join(TEST_DIR, "facts.json"))
mem.apply_config(cfg)

t_all = time.time()
for i in range(TASKS):
    state["step"] = 0
    engine.agent_run(cfg, mem, "第 %d 个任务：看看目录、读文件、找文件" % (i + 1),
                     engine.Approver(True, None))
wall = time.time() - t_all

rep = engine.limits.report()
print()
print("=" * 66)
print("跑了 %d 个任务（每个 4 次模型往返，固定 %dms/次）" % (TASKS, MODEL_MS))
print("总墙钟时间：%.1f 秒" % wall)
print("-" * 66)
for k, label in (("local", "本地执行（读文件/列目录/搜索）"),
                 ("net", "模型网络（等 API 返回）"),
                 ("render", "界面渲染")):
    print("%-28s %5.1f%%   次数 %3d   平均 %7.1f ms   合计 %8.0f ms" % (
        label, rep["share"][k], rep["count"][k], rep["avg_ms"][k], rep["total_ms"][k]))
print("-" * 66)
local_avg = rep["avg_ms"]["local"]
net_avg = rep["avg_ms"]["net"]
if net_avg and local_avg:
    print("一次模型往返 = %.0f ms；一次本地工具 = %.1f ms（约 %.0f 倍）"
          % (net_avg, local_avg, net_avg / max(local_avg, 0.1)))
print("结论：时间几乎都在等模型。优化本地读写收益极小，砍模型轮次才有效。")
print("=" * 66)
