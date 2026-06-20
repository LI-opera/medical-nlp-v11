# Medical NLP 项目错误分析（Error Analysis V1）

## Benchmark 概况

测试集规模：

50 条医学缩写测试样本

覆盖类别：

* 单义缩写（Single Meaning）
* 歧义缩写（Ambiguous Abbreviation）
* 多缩写场景（Multi-Abbreviation）
* Coverage Failed
* 低上下文缩写（Low Context Abbreviation）
* 否定表达保持（Negation Preservation）

当前 Benchmark 结果：

| 类别                       | 准确率  |
| ------------------------ | ---- |
| Single Meaning           | 90%  |
| Ambiguous                | 90%  |
| Multi-Abbreviation       | 90%  |
| Coverage Failed          | 100% |
| Low Context Abbreviation | 20%  |
| Negation Preservation    | 70%  |

整体准确率：

80%

---

## 错误类型一：低上下文缩写误扩写

典型案例：

原文：

The patient was evaluated for LMN.

期望结果：

不进行扩写

系统结果：

LMN → Lower Motor Neuron

问题分析：

当前系统在发现候选扩写时，倾向于直接进行扩写。

虽然扩写本身是医学上正确的，但当前上下文并不足以支撑该扩写。

本质问题：

系统缺少“上下文支持度判断”能力。

---

## 错误类型二：歧义缩写消歧失败

典型案例：

The patient has MS with a diastolic murmur.

期望：

MS → Mitral Stenosis

预测：

MS → Multiple Sclerosis

问题分析：

系统能够召回正确候选。

但是在候选选择阶段没有充分利用心脏疾病相关上下文。

本质问题：

上下文消歧能力不足。

---

## 错误类型三：过度保守（Over-Abstention）

典型案例：

The patient denies CP.

期望：

CP → Chest Pain

实验版本预测：

不扩写

问题分析：

引入 Mapping Support Verification 后，

系统开始倾向于拒绝部分本来应该扩写的缩写。

导致准确率下降。

本质问题：

上下文验证策略过于严格。

---

## 当前结论

V9 版本已经能够稳定完成：

* 医学缩写识别
* 候选召回
* 上下文扩写
* SNOMED 标准化
* Verification
* Reflection

整体准确率达到：

92%左右

当前主要问题已经从：

“能不能扩写”

转变为：

“什么时候不应该扩写”

因此下一阶段重点方向为：

低上下文缩写处理策略优化。
