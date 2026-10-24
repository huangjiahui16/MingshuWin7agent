# -*- coding: utf-8 -*-
"""ini 合并工具：保留注释。

configparser.write() 会把所有 # 注释行吃掉——F 盘的 assistant.ini 就是这样
从 1899 字节掉到 551 字节的（内容没丢，但用户看不懂每个旋钮是干什么的）。
这个模块逐行比对，只把目标里缺失的 section/option 追加进去，注释全保留。
"""
import configparser
import io


def _existing(text):
    """解析出目标里已有的 (section, option) 集合。"""
    c = configparser.ConfigParser(interpolation=None)
    try:
        c.read_string(text)
    except Exception:
        return set()
    out = set()
    for sec in c.sections():
        out.add(("", sec))
        for k in c.options(sec):
            out.add((sec, k))
    return out


def merge_ini(dst_text, src_text, header_note=True):
    """把 src 里 dst 缺失的 section/option 补进 dst，保留 dst 原有全部内容与注释。

    做法：缺失的 option 插到它所属段的末尾（原位插入，不重复段头）；
    整个 section 都缺失的，连段头带注释追加到文件末尾。
    """
    have = _existing(dst_text)
    if not have and not dst_text.strip():
        return src_text                     # 目标是空的，直接用源

    missing_opts = {}                       # sec -> [option 行]
    new_secs = []                           # [(sec, [全部行，含段头])]
    cur_sec, buf = None, []

    def flush():
        if cur_sec is None:
            return
        if ("", cur_sec) not in have:
            new_secs.append((cur_sec, list(buf)))
        else:
            opts = [ln for ln in buf
                    if "=" in ln and not ln.strip().startswith("[")
                    and not ln.strip().startswith(("#", ";"))
                    and (cur_sec, ln.split("=", 1)[0].strip()) not in have]
            if opts:
                missing_opts[cur_sec] = opts

    for line in src_text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            flush()
            cur_sec, buf = s[1:-1].strip(), [line]
        elif cur_sec is not None:
            buf.append(line)
    flush()

    if not missing_opts and not new_secs:
        return dst_text

    out = []
    cur = None
    for line in dst_text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if cur in missing_opts:                 # 上一段结束，补它的缺失项
                out.extend(missing_opts.pop(cur))
            out.append(line)
            cur = s[1:-1].strip()
        else:
            out.append(line)
    if cur in missing_opts:                         # 文件结束，补最后一段
        out.extend(missing_opts.pop(cur))

    if new_secs:
        if header_note:
            out.append("")
            out.append("# ------------------------------------------------------------")
            out.append("# 以下为新增配置项（合并脚本追加，不会覆盖你已有的设置）")
        for _sec, lines in new_secs:
            out.append("")
            out.extend(x.rstrip() for x in lines)

    return "\n".join(out).rstrip("\n") + "\n"


def read_text(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text)


if __name__ == "__main__":
    # 自测：注释保留 + 只补缺失 + 不动已有
    dst = u"""# 我的配置
[llm]
base_url = https://api.deepseek.com/v1
# 这是我的 Key，别动
api_key = sk-realkey123456

[agent]
max_steps = 6
"""
    src = u"""[llm]
base_url = https://api.deepseek.com/v1
api_key = 在这里填你的APIKey
# 单次回复上限
max_tokens = 1024

[memory]
# 长期记忆开关
enabled = true
auto = true
"""
    got = merge_ini(dst, src)
    print("=== 合并结果 ===")
    print(got)
    assert "sk-realkey123456" in got, "已有 Key 被改了！"
    assert "max_tokens = 1024" in got, "缺失项没补上"
    assert "[memory]" in got and "enabled = true" in got, "新 section 没补上"
    assert "# 这是我的 Key，别动" in got, "注释丢了！"
    assert got.count("api_key") == 1, "api_key 重复了"
    # 关键断言：补进去的 max_tokens 必须落在 [llm] 段，不能落到 [agent]
    import configparser as _cp
    _c = _cp.ConfigParser(interpolation=None)
    _c.read_string(got)
    assert _c.get("llm", "max_tokens", fallback="") == "1024", "max_tokens 落错段了！"
    assert _c.get("agent", "max_tokens", fallback="") == "", "max_tokens 跑到 agent 段了！"
    assert _c.get("llm", "api_key") == "sk-realkey123456", "Key 被改"
    assert _c.getboolean("memory", "enabled") is True, "新段没生效"
    print("=== 自测通过：Key 未动、缺失已补、注释保留、无重复、段落正确 ===")
