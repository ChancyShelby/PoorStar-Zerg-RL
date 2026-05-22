# PoorStar Macro-RL 当前可运行版说明（V3.6 hotfix）

这版仍然是 **正常地图宏观运营 / 战术控制版本**，不是 MicroGym 平地刷兵训练环境。  
推荐先继续在 `AutomatonLE` 上验证运营、侦察、防守、升本、采气、转型和出门时机。

## 这次整理修改了什么

1. 修复 `rl_v1/rl_controller.py` 的终局 summary 状态问题：
   - 以前 `finish_episode()` 优先使用 `self.last_obs`，可能导致认输理由显示“工人/部队已经崩了”，但 final summary 仍然显示上一轮 RL 决策时的旧健康状态。
   - 现在终局会优先重新调用 `extract_observation(self.bot)`，失败时才回退到 `last_obs`。

2. 修复脚本路径混乱：
   - `scripts/run_eval_v2.ps1`
   - `scripts/run_train_3eps_v2.ps1`
   - `scripts/run_train_20eps_v2.ps1`
   - `scripts/analyze.ps1`
   都改成了 `cd $PSScriptRoot\..`，不再写死旧目录 `RL_v2_8_gas_perf_baseline_fix`。

3. 新增当前推荐脚本：
   - `scripts/run_eval_current.ps1`
   - `scripts/run_train_3eps_current.ps1`
   - `scripts/run_train_20eps_current.ps1`

4. `analyze_rl_runs.py` 默认分析目录改为 `runs_v28`。

## 推荐运行方式

在 PowerShell 里进入项目根目录后：

```powershell
.\scripts\run_eval_current.ps1
```

训练 3 局 smoke test：

```powershell
.\scripts\run_train_3eps_current.ps1
```

训练 20 局：

```powershell
.\scripts\run_train_20eps_current.ps1
```

分析历史 episode：

```powershell
.\scripts\analyze.ps1
```

## 重要提醒

- 这版不要直接拿你刚做的 `ZergMicroFlat.SC2Map` 平地图跑 `train_rl_v2.py`。
- 这版依赖正常天梯图的矿、气、出生点和扩张点。
- 平地图后面应该单独接 MicroGym / debug_create_unit 刷兵环境。

## 我建议你接下来先看什么

跑完一局后，重点看：

```text
runs_v28/episode_xxxx/rl_logs/episode_summary.json
```

尤其看这些字段：

```text
result
final.workers
final.army_supply
final.bases
final.minerals / final.vespene
final.gas_worker_count / final.gas_worker_target
final.resign_reason
final.strategic_stage
final.army_plan
final.plan_stuck
final.plan_unrealized
```

如果再次出现“认输理由和 final 数值明显对不上”，优先把该局的 `episode_summary.json` 发给我。
