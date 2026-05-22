cd "C:\Users\DELL\Desktop\PoorStar_Zerg_RL_OpenSource"

@'
# PoorStar Zerg RL / 虫族宏观强化学习 Bot

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## English

PoorStar Zerg RL is a StarCraft II Zerg bot framework built with `python-sc2`.

It combines rule-based macro control, safety scaffolding, tactical decision logic, and macro-level reinforcement learning. The project is designed as a practical engineering route toward a playable and extensible Zerg agent.

The current repository focuses on macro decision making and bot infrastructure. It does **not** include private replay datasets, trained checkpoints, API keys, local logs, or StarCraft II game files.

---

## Motivation

StarCraft II is a complex real-time strategy environment involving long-horizon planning, partial information, resource management, technology progression, and combat control.

Instead of training an end-to-end agent from scratch, this project follows a more practical path:

1. Build a stable rule-based macro baseline.
2. Add macro-level reinforcement learning for strategic decisions.
3. Use hard safety logic to prevent obviously broken behavior.
4. Keep economy, scouting, defense, tech, combat, and advanced unit logic modular.
5. Leave room for future specialized micro-control agents.

The goal is **not** to reproduce AlphaStar.  
The goal is to build a debuggable and extensible Zerg bot pipeline that can actually run and improve step by step.

---

## Main Features

### Macro-Level Reinforcement Learning

The RL agent does not directly control every unit. Instead, it selects high-level strategic actions such as:

- economy-focused macro
- scouting focus
- defensive hold
- ling pressure
- roach pressure
- roach-hydra timing
- fast lair tech
- fast hive tech
- upgrade focus
- maxed army attack

This keeps the action space manageable and allows rule-based modules to handle low-level execution.

### Rule-Based Safety Scaffold

The bot includes safety logic to reduce obviously unstable behavior, such as:

- supply blocking
- failure to spend resources
- missing critical tech
- poor gas/mineral balance
- delayed expansion
- lack of defensive response
- unstable worker flow

### Economy and Tech Support

The project includes modules for:

- drone production
- overlord production
- gas management
- expansion logic
- lair and hive tech progression
- upgrade planning
- resource spending pressure
- basic army composition support

### Tactical and Combat Logic

The bot contains tactical support for:

- target selection
- high-ground placement fixes
- army coordination
- combat command ownership
- advanced unit control hooks
- resignation detection for hopeless games

---

## Repository Structure

```text
PoorStar_Zerg_RL_OpenSource/
├── rl_v1/
│   ├── agent.py
│   ├── rl_controller.py
│   ├── rl_bot.py
│   ├── macro_actions.py
│   ├── state_features.py
│   ├── reward.py
│   ├── hard_scaffold_manager.py
│   ├── economy_support.py
│   ├── advanced_unit_control.py
│   ├── combat_coordinator.py
│   ├── tactical_targeting.py
│   ├── tech_intent.py
│   ├── strategic_stage.py
│   ├── map_hunt_manager.py
│   └── resign_detector.py
│
├── scripts/
│   ├── run_eval_current.ps1
│   ├── run_train_3eps_current.ps1
│   └── run_train_20eps_current.ps1
│
├── train_rl_v2.py
├── play_rl_v2.py
├── analyze_rl_runs.py
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Requirements

Recommended environment:

- Windows 10 / Windows 11
- StarCraft II installed
- Python 3.10
- `python-sc2`
- PyTorch
- NumPy
- pandas
- matplotlib
- tqdm

Install dependencies:

```powershell
pip install -r requirements.txt
```

A Conda environment is recommended:

```powershell
conda create -n pysc2 python=3.10
conda activate pysc2
pip install -r requirements.txt
```

---

## Run Evaluation

From the project root:

```powershell
.\scripts\run_eval_current.ps1
```

Or run directly:

```powershell
python play_rl_v2.py
```

---

## Run a Small Training Test

```powershell
.\scripts\run_train_3eps_current.ps1
```

For a longer run:

```powershell
.\scripts\run_train_20eps_current.ps1
```

Training outputs are intentionally ignored by Git and should not be committed.

---

## Not Included

This repository does not include:

- private replay datasets
- `.SC2Replay` files
- trained model checkpoints
- local training logs
- API keys
- StarCraft II game files
- large generated outputs

These files should stay local and are excluded through `.gitignore`.

---

## Development Roadmap

The main design principle is:

```text
Rule baseline first.
Macro RL second.
Specialized micro controllers later.
```

Future work may include:

- better reward shaping
- cleaner curriculum learning
- replay-inspired opening policies
- dedicated micro-control environments
- specialized controllers for ravagers, vipers, infestors, lurkers, and brood lord compositions
- improved scouting and opponent strategy recognition
- more robust evaluation across maps and enemy races

---

## Disclaimer

This is an independent research and engineering project. It is not affiliated with Blizzard Entertainment.

StarCraft II is a trademark of Blizzard Entertainment. This repository only contains user-written bot code and does not redistribute any StarCraft II game files.

---

<a id="中文"></a>

## 中文

PoorStar Zerg RL 是一个基于 `python-sc2` 的《星际争霸 II》虫族 Bot 框架。

这个项目结合了规则式宏观运营、安全兜底逻辑、战术决策模块和宏观层强化学习，目标是用一条更工程化、更可调试的路线，逐步构建一个可运行、可扩展的虫族智能体。

当前仓库主要关注**宏观决策和 Bot 工程框架**，不包含私人录像数据集、训练好的模型权重、API Key、本地日志或 StarCraft II 游戏文件。

---

## 项目动机

《星际争霸 II》是一个复杂的即时战略环境，涉及长期规划、不完全信息、资源管理、科技路线、战斗控制和多阶段策略切换。

相比直接从零训练端到端智能体，本项目采用更现实的工程路线：

1. 先构建稳定的规则式宏观运营基线。
2. 再加入宏观层强化学习，让模型学习战略意图选择。
3. 使用硬规则兜底，避免明显错误的行为。
4. 将经济、侦察、防守、科技、战斗和高级兵控制拆成独立模块。
5. 为后续接入专门的微操控制器预留接口。

本项目的目标**不是复刻 AlphaStar**。  
目标是构建一个能跑、能调试、能逐步迭代的虫族 Bot 工程管线。

---

## 主要功能

### 宏观层强化学习

RL Agent 不直接控制每一只单位，而是选择高层战略动作，例如：

- 经济运营
- 侦察优先
- 防守稳固
- 小狗压制
- 蟑螂压制
- 蟑螂刺蛇 Timing
- 快速二本
- 快速三本
- 攻防升级优先
- 满人口进攻

这样可以降低动作空间复杂度，让规则模块负责底层执行。

### 规则式安全兜底

Bot 包含硬规则安全逻辑，用于减少明显不稳定的行为，例如：

- 卡人口
- 资源花不出去
- 关键科技缺失
- 矿气比例失衡
- 扩张过慢
- 缺少防守反应
- 工人流不稳定

### 经济与科技支持

项目包含以下模块：

- 工蜂生产
- 王虫生产
- 采气管理
- 扩张逻辑
- 二本 / 三本科技推进
- 攻防升级规划
- 资源消耗压力控制
- 基础兵种组合支持

### 战术与战斗逻辑

Bot 包含以下战术支持：

- 目标选择
- 高地相关位置修复
- 部队协调
- 战斗命令所有权管理
- 高级兵控制接口
- 绝望局自动认输判断

---

## 仓库结构

```text
PoorStar_Zerg_RL_OpenSource/
├── rl_v1/
│   ├── agent.py                    # RL 网络与策略模块
│   ├── rl_controller.py            # RL 决策控制器
│   ├── rl_bot.py                   # python-sc2 Bot 主体
│   ├── macro_actions.py            # 宏观动作执行
│   ├── state_features.py           # 状态特征提取
│   ├── reward.py                   # 奖励函数
│   ├── hard_scaffold_manager.py    # 硬规则兜底
│   ├── economy_support.py          # 经济修复与资源平衡
│   ├── advanced_unit_control.py    # 高级兵控制接口
│   ├── combat_coordinator.py       # 战斗命令协调
│   ├── tactical_targeting.py       # 战术目标选择
│   ├── tech_intent.py              # 科技意图
│   ├── strategic_stage.py          # 战略阶段判断
│   ├── map_hunt_manager.py         # 地图搜索/残局处理
│   └── resign_detector.py          # 认输检测
│
├── scripts/
│   ├── run_eval_current.ps1
│   ├── run_train_3eps_current.ps1
│   └── run_train_20eps_current.ps1
│
├── train_rl_v2.py                  # 训练入口
├── play_rl_v2.py                   # 评估/运行入口
├── analyze_rl_runs.py              # 训练日志分析
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 环境要求

推荐环境：

- Windows 10 / Windows 11
- 已安装 StarCraft II
- Python 3.10
- `python-sc2`
- PyTorch
- NumPy
- pandas
- matplotlib
- tqdm

安装依赖：

```powershell
pip install -r requirements.txt
```

推荐使用 Conda 环境：

```powershell
conda create -n pysc2 python=3.10
conda activate pysc2
pip install -r requirements.txt
```

---

## 运行评估

在项目根目录下运行：

```powershell
.\scripts\run_eval_current.ps1
```

也可以直接运行：

```powershell
python play_rl_v2.py
```

---

## 运行小规模训练测试

```powershell
.\scripts\run_train_3eps_current.ps1
```

更长的训练：

```powershell
.\scripts\run_train_20eps_current.ps1
```

训练输出会被 `.gitignore` 忽略，不应该提交到仓库。

---

## 仓库不包含的内容

本仓库不包含：

- 私人 Replay 数据集
- `.SC2Replay` 文件
- 训练好的模型权重
- 本地训练日志
- API Key
- StarCraft II 游戏文件
- 大型生成输出

这些文件应保留在本地，并通过 `.gitignore` 排除。

---

## 开发路线

核心原则：

```text
先规则基线。
再宏观 RL。
后续接入专门微操控制器。
```

未来可能继续加入：

- 更合理的奖励函数设计
- 更清晰的课程学习
- 基于 Replay 的开局策略
- 独立微操训练环境
- 火蟑螂、飞蛇、感染、地刺、大龙等专门控制器
- 更强的侦察与敌方策略识别
- 跨地图、跨种族的稳定评估

---

## 免责声明

本项目是独立研究与工程实践项目，与 Blizzard Entertainment 无关。

StarCraft II 是 Blizzard Entertainment 的商标。本仓库只包含用户自行编写的 Bot 代码，不分发任何 StarCraft II 游戏文件。
'@ | Set-Content "README.md" -Encoding UTF8