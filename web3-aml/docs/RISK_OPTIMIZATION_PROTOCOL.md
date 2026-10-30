# 双线路风险评分优化实验

## 目标

保留轻量化 MLP、GraphSAGE、标量 Gate 和三个风险头，检验融合能否在统一的时间划分下
提供稳定收益。训练产物单独保存在 `artifacts/experiments/risk_v2/`，现有模型作为历史基线保留。

## 开发区间

仅使用原训练区间内的已知标签地址：

| 区间 | 训练时间步 | 开发验证时间步 |
|---|---|---|
| early_shift | 1～22 | 23～28 |
| late_train | 1～28 | 29～34 |

中位数、数值变换和标准化参数仅在各区间的训练节点拟合。unknown 可用于消息传播，
但不进入监督损失。训练与验证图分别排除各截止时间后的节点关系。
生命周期聚合特征的静态快照局限仍然存在，不能据此声称在线历史时点预测。

## 预先规定的比较

1. 行为分支：原始标准化、signed-log 标准化、signed-log 加标准化值截断、
   以及截断后移除四个绝对区块高度特征。每种方案比较 Focal 与加权 BCE。
2. 选平均开发 AP 最优的输入与损失方案，以最低区间 AP 作并列排序依据。
3. 在该输入方案上比较 GraphSAGE、原 Gate、LayerNorm 后的 Gate，以及 LayerNorm 后的固定 50/50 融合。
4. 在学习 Gate 的两个方案中按相同开发规则冻结最终融合配置。
5. 最终比较行为单分支、图单分支、选定 Gate、对应固定 50/50 融合和 LightGBM。
   固定融合对照采用与选定 Gate 相同的表示归一化设置。

LayerNorm 只处理两个 64 维表示的尺度，未引入新图模型或时间模型。
固定权重模型仍独立训练，不等同于对同一个已训练 Gate 模型强制改权重；须如实表述消融口径。

## 最终验收

输入方案与融合设置冻结后，用原训练集拟合，原验证集早停、温度校准和选择分类阈值。
三个固定种子为 42、43、44，报告各次结果及均值、标准差。代表融合模型按验证 AP 选择种子，
在任何新测试推理之前保存 `final_freeze.json`。

最后评估原测试集，保存 Precision、Recall、F1、AP、ROC-AUC、Brier、PR/ROC 曲线、
Top-100、Top-500、Top-1%、Top-5% 人工复核命中率及模型参数和文件大小。
人工复核预算统计仅针对测试集中已知标签地址，不能外推为全量 unknown 地址的真实命中率。

原测试集在此前实验中已被查看，后续结果须标明重复评估的局限。
不根据新测试结果反复选择特征、损失、模型配置或种子。
是否上线采用预先写入配置的 AP/F1 门槛，未达门槛则保留当前稳定 Demo。

## 复现

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_risk_experiments.py tests/test_model.py -q
..\.venv\Scripts\python.exe scripts/10_optimize_risk_model.py --stage development
..\.venv\Scripts\python.exe scripts/10_optimize_risk_model.py --stage final
```

参数在 `config/risk_experiments.yaml`。实验签名记录配置与数据 fingerprint。
同名实验的实验配置发生变化时程序拒绝覆盖，须使用新的实验名称。
已有实验恢复时使用 manifest 内冻结的基础模型配置；上线后的主配置修改不会改变历史实验。
完成的训练会自动跳过，未完成的单次训练会从头重跑。
单次训练使用进程级文件锁，独立进程可运行不同区间或最终候选，避免重复写入同一模型。
`--stage fusion_fold --fold late_train` 可协助开发区间；
`--stage final_train --candidate graphsage` 可训练某个最终候选的三个种子。
辅助进程只训练，不运行测试；所有候选完成并冻结代表模型后，再运行 `--stage final`。

最终汇总与达到门槛后的安装入口：

```powershell
..\.venv\Scripts\python.exe scripts/11_summarize_risk_experiments.py
..\.venv\Scripts\python.exe scripts/12_promote_risk_model.py
```

安装前保存 `previous_demo/` 备份。安装后须执行 06～08 脚本并验收，再重启网页服务。
上线门槛是配置中预先记录的历史 GraphSAGE AP/F1；与本轮新 GraphSAGE、固定融合的收益
另外如实报告，达到上线门槛不等同于融合已经超过本轮所有对照。

### 加权损失的概率处理

加权 BCE 的最优赔率会乘以正类权重。导出时对风险头偏置减去 `log(pos_weight)`，
恢复未加权赔率尺度，再在验证集做 Temperature Scaling。
这是按训练集类别比例计算的固定偏置修正，不改变风险排序，不增加网络层或拟合参数。
旧的训练模型保存在 `model_weighted_training.pt`，修正前验证指标也单独保存。
校准后的模型仍使用 `100 × sigmoid(fused_logit / T)`，修正只执行一次。

LightGBM 使用 balanced class weights，同样恢复赔率后在验证集做温度校准；其原始分类器
仍输出加权概率，解释概率须结合保存的 `lightgbm_calibration.json`。
该处理在任何新的最终测试前确定。类别先验来自已知训练标签，不能保证未知标签地址的概率校准。

## 推理与解释一致性

训练拟合的输入处理参数嵌入模型 checkpoint。全量风险预计算和行为 IG 使用相同变换。
旧模型未配置变换和 LayerNorm 时保持原有计算方式。
新风险表记录模型与校准参数的 hash，邻域统计、Evidence 和前端缓存绑定风险版本。
