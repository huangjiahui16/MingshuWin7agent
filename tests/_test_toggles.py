# -*- coding: utf-8 -*-
"""测试：两个强制开关（skills_enforced / memory.enabled）真的生效，不是摆设。"""
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
TEST_DIR = os.path.join(BASE, "_test_tmp", "toggles")
os.makedirs(TEST_DIR, exist_ok=True)

import configparser
import sys as _sys, os as _os  # SYS_PATH_PATCHED
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src'))
import win7_assistant as engine

engine.CONFIG_PATH = os.path.join(TEST_DIR, "assistant.ini")
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "memory_md.md")
engine.SKILLS_DIR = os.path.join(TEST_DIR, "skills")
os.makedirs(os.path.join(engine.SKILLS_DIR, "demo"), exist_ok=True)
# 放一个假技能
with open(os.path.join(engine.SKILLS_DIR, "demo", "SKILL.md"), "w",
          encoding="utf-8") as f:
    f.write("---\nname: demo\ndescription: 测试技能用来验证开关\n---\n正文")

ok = [0]
fail = [0]
def check(name, cond):
    if cond:
        ok[0] += 1
        print("PASS  " + name)
    else:
        fail[0] += 1
        print("FAIL  " + name)

def make_cfg(skills, mem):
    c = configparser.ConfigParser(interpolation=None)
    c.add_section("llm")
    c.set("llm", "model", "deepseek-flash")
    c.add_section("assistant")
    c.set("assistant", "system_prompt", "测试")
    c.set("assistant", "skills_enforced", "true" if skills else "false")
    c.add_section("memory")
    c.set("memory", "enabled", "true" if mem else "false")
    c.set("memory", "auto", "false")
    return c

# ---- 关：skills off + memory off ----
cfg = make_cfg(False, False)
sp = engine.build_system_prompt(cfg, plain=False)
check("关: system prompt 不含技能库标题", "【技能库" not in sp)
check("关: system prompt 不含技能名 demo", "demo" not in sp)
m = engine.Memory(memory_path=os.path.join(TEST_DIR, "s1.json"),
                  facts_path=engine.FACTS_PATH)
m.apply_config(cfg)
m.remember("只能写F盘")
check("关: memory_block 为空", m.memory_block() == "")
msgs = m.build_messages(sp)
check("关: 发给模型的 system 无记忆内容", "只能写F盘" not in msgs[0]["content"])

# agent_run 工具列表：load_skill 被摘掉
tools_holder = {}
def fake_chat_raw(cfgx, messages, tools=None, on_delta=None, stop_event=None):
    tools_holder["tools"] = tools
    tools_holder["sys"] = messages[0]["content"]
    return {"content": "完毕", "tool_calls": []}
engine.chat_raw = fake_chat_raw
mem2 = engine.Memory(memory_path=os.path.join(TEST_DIR, "s2.json"),
                     facts_path=engine.FACTS_PATH)
mem2.apply_config(cfg)
final = engine.agent_run(cfg, mem2, "你好", engine.Approver(True, None))
names = [t["function"]["name"] for t in (tools_holder["tools"] or [])]
check("关: 工具列表无 load_skill", "load_skill" not in names)
check("关: 请求里的 system 无技能库", "【技能库" not in tools_holder["sys"])
check("关: 请求里的 system 无记忆", "只能写F盘" not in tools_holder["sys"])
# 顺便验证会话边界提示词
check("关: 含会话边界说明", "会话边界" in tools_holder["sys"])

# ---- 开：都开 ----
cfg2 = make_cfg(True, True)
sp2 = engine.build_system_prompt(cfg2, plain=False)
check("开: system prompt 含技能库", "【技能库" in sp2)
m3 = engine.Memory(memory_path=os.path.join(TEST_DIR, "s3.json"),
                   facts_path=engine.FACTS_PATH)
m3.apply_config(cfg2)
m3.remember("只能写F盘")
check("开: memory_block 注入记忆", "只能写F盘" in m3.memory_block())
tools_holder.clear()
mem4 = engine.Memory(memory_path=os.path.join(TEST_DIR, "s4.json"),
                     facts_path=engine.FACTS_PATH)
mem4.apply_config(cfg2)
engine.agent_run(cfg2, mem4, "你好", engine.Approver(True, None))
names2 = [t["function"]["name"] for t in (tools_holder["tools"] or [])]
check("开: 工具列表有 load_skill", "load_skill" in names2)

# ---- 孤儿记忆回收 ----
m5 = engine.Memory(facts_path=engine.FACTS_PATH)
m5.facts.append({"text": "全局固定记忆条目", "sid": ""})   # 全局（sid 空）
m5.facts.append({"text": "活会话记忆", "sid": "alive1"})
m5.facts.append({"text": "死会话记忆", "sid": "dead sid"})
n = m5.purge_orphan_facts(["alive1"])
check("回收: 返回删除数>0", n > 0)
check("回收: 全局记忆保留", any(engine._fact_text(x) == "全局固定记忆条目"
                              for x in m5.facts))
check("回收: 活会话记忆保留", any(engine._fact_text(x) == "活会话记忆"
                                for x in m5.facts))
check("回收: 孤儿 sid 全没了", all(engine._fact_sid(x) in ("", "alive1")
                                   for x in m5.facts))

print("RESULT: %d passed, %d failed" % (ok[0], fail[0]))
sys.exit(1 if fail[0] else 0)
