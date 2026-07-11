# 批次 16 · 给 Codex 的指令(可整段复制)· verify 换异质判官(千问),量净收益

## 背景与范围

batch15 已建好 LLM 配置 + 工厂。本批把 **verify 的模型从 DeepSeek 换成千问**(`create_llm(QWEN_CONFIG)`),让 **coverage 仍 DeepSeek(生成)/ verify 用千问(异质检查)**,破"自生自查"(同源生成+校验)。**coverage、fallback、检索等一律不动**——只换 verify 这一处的模型。

> 这是个**可证伪实验**:换完用 concept bench + 主 bench 量净收益。好就留、平/差就退。

**铁律**:只改 `backend/services/abbr_verifier.py` 的 `__init__`(换模型来源)+ 顶部 import;**不改** `verify_mappings` / `propose_requeries` / `verify` 的任何逻辑(接口一致,逻辑零改动);不动其它文件。

工作在 `medical-refactor`。

---

## A · 改 `backend/services/abbr_verifier.py`

**A1. 顶部 import 区**新增两行(放在现有 import 附近):
```python
from utils.llm_config import LLMConfig, QWEN_CONFIG
from utils.llm_factory import create_llm
```

**A2. 把 `ABBVerifier.__init__` 换成下面这版**(用工厂按配置建模型,默认千问=异质判官):
```python
    def __init__(self, config: LLMConfig = QWEN_CONFIG):
        # 异质判官:verify 用千问,与 coverage 的 DeepSeek 不同源,破"自生自查"。
        # 想 A/B 退回 DeepSeek 判官:ABBVerifier(DEEPSEEK_CONFIG)。
        self.llm = create_llm(config)
```
> 删掉原来 `__init__` 里手搓 `ChatDeepSeek(...)` 那段和 `DEEPSEEK_API_KEY` 检查(密钥现在工厂里管)。`self.llm` 接口不变(仍 `.invoke().content`),所以 `verify_mappings` / `propose_requeries` / 老 `verify` **一律不用改**。原来的 `from langchain_deepseek import ChatDeepSeek` 若变成未使用可删可留。

---

## 验收(这批的重点是"量净收益")

1. **编译 + import**:`python -m compileall backend/services backend/utils` 通过;`ABBVerifier` 干净 import。
2. **★concept benchmark(核心尺子)**:`python backend/evaluation/run_concept_benchmark.py`
   - **基线(DeepSeek 判官)= PASS 11/11、canonical 10/11**(SOB=Dyspnea、CAD=Disorder of coronary artery)。
   - 换千问判官后逐项对比:**PASS 有没有掉、canonical 有没有动、CAD/SOB 判得一样吗**。
   - 重点观察:① 是否因千问 JSON 输出格式不同导致**异常多弃码**(parse 失败会让它弃码);② CAD 这种边界千问怎么判。
3. **主 benchmark(控制项,应持平)**:`python backend/evaluation/run_benchmark.py` → 仍 **71/74=0.9595**(verify 不影响扩写判分,这条本就该平;若掉了说明换模型引入了异常)。
4. **判定**:concept bench **不回归**(PASS≥11/11、canonical≥10/11)且主 bench 持平 → 异质判官至少不亏、且破了自生自查,**留**;若 concept 明显回归(如千问乱弃码)→ **退回 DeepSeek**(把默认 config 改回 `DEEPSEEK_CONFIG` 或 revert 本批),记录"此任务上 DeepSeek 判官更好"。

> 诚实预期:可能持平(千问和 DeepSeek 在这 11 例上都够用),那也是有价值的结论——**证明了"换异质判官不掉分",自生自查的循环被打破,且这是可讲的工程动作**。真要看出差异,得靠更大的 concept gold 集 / 真实流量,这一步先把"异质化"这件事做实 + 验证不破坏现有质量。

## 提交

```bash
git add backend/services/abbr_verifier.py
git commit -m "V11 batch16: heterogeneous verify - swap verify LLM to Qwen via factory (coverage=DeepSeek generator / verify=Qwen critic), breaking same-source self-check. Measured on concept + main benchmark."
```
> 面试叙事:**生成和检查不再同源**——coverage 用 DeepSeek 选扩写,verify 用千问选概念,两个不同厂商的模型,失败模式不相关,这才是治"自生自查"的真招(而不是 multi-agent 套壳)。换完用分层 benchmark 量净收益,不正就退。
