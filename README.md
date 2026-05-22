cd "C:\Users\DELL\Desktop\PoorStar_Zerg_RL_OpenSource"

@'
# PoorStar Zerg RL / 铏棌瀹忚寮哄寲瀛︿範 Bot

[English](#english) | [涓枃](#涓枃)

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
鈹溾攢鈹€ rl_v1/
鈹?  鈹溾攢鈹€ agent.py
鈹?  鈹溾攢鈹€ rl_controller.py
鈹?  鈹溾攢鈹€ rl_bot.py
鈹?  鈹溾攢鈹€ macro_actions.py
鈹?  鈹溾攢鈹€ state_features.py
鈹?  鈹溾攢鈹€ reward.py
鈹?  鈹溾攢鈹€ hard_scaffold_manager.py
鈹?  鈹溾攢鈹€ economy_support.py
鈹?  鈹溾攢鈹€ advanced_unit_control.py
鈹?  鈹溾攢鈹€ combat_coordinator.py
鈹?  鈹溾攢鈹€ tactical_targeting.py
鈹?  鈹溾攢鈹€ tech_intent.py
鈹?  鈹溾攢鈹€ strategic_stage.py
鈹?  鈹溾攢鈹€ map_hunt_manager.py
鈹?  鈹斺攢鈹€ resign_detector.py
鈹?鈹溾攢鈹€ scripts/
鈹?  鈹溾攢鈹€ run_eval_current.ps1
鈹?  鈹溾攢鈹€ run_train_3eps_current.ps1
鈹?  鈹斺攢鈹€ run_train_20eps_current.ps1
鈹?鈹溾攢鈹€ train_rl_v2.py
鈹溾攢鈹€ play_rl_v2.py
鈹溾攢鈹€ analyze_rl_runs.py
鈹溾攢鈹€ requirements.txt
鈹溾攢鈹€ .gitignore
鈹斺攢鈹€ README.md
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

<a id="涓枃"></a>

## 涓枃

PoorStar Zerg RL 鏄竴涓熀浜?`python-sc2` 鐨勩€婃槦闄呬簤闇?II銆嬭櫕鏃?Bot 妗嗘灦銆?
杩欎釜椤圭洰缁撳悎浜嗚鍒欏紡瀹忚杩愯惀銆佸畨鍏ㄥ厹搴曢€昏緫銆佹垬鏈喅绛栨ā鍧楀拰瀹忚灞傚己鍖栧涔狅紝鐩爣鏄敤涓€鏉℃洿宸ョ▼鍖栥€佹洿鍙皟璇曠殑璺嚎锛岄€愭鏋勫缓涓€涓彲杩愯銆佸彲鎵╁睍鐨勮櫕鏃忔櫤鑳戒綋銆?
褰撳墠浠撳簱涓昏鍏虫敞**瀹忚鍐崇瓥鍜?Bot 宸ョ▼妗嗘灦**锛屼笉鍖呭惈绉佷汉褰曞儚鏁版嵁闆嗐€佽缁冨ソ鐨勬ā鍨嬫潈閲嶃€丄PI Key銆佹湰鍦版棩蹇楁垨 StarCraft II 娓告垙鏂囦欢銆?
---

## 椤圭洰鍔ㄦ満

銆婃槦闄呬簤闇?II銆嬫槸涓€涓鏉傜殑鍗虫椂鎴樼暐鐜锛屾秹鍙婇暱鏈熻鍒掋€佷笉瀹屽叏淇℃伅銆佽祫婧愮鐞嗐€佺鎶€璺嚎銆佹垬鏂楁帶鍒跺拰澶氶樁娈电瓥鐣ュ垏鎹€?
鐩告瘮鐩存帴浠庨浂璁粌绔埌绔櫤鑳戒綋锛屾湰椤圭洰閲囩敤鏇寸幇瀹炵殑宸ョ▼璺嚎锛?
1. 鍏堟瀯寤虹ǔ瀹氱殑瑙勫垯寮忓畯瑙傝繍钀ュ熀绾裤€?2. 鍐嶅姞鍏ュ畯瑙傚眰寮哄寲瀛︿範锛岃妯″瀷瀛︿範鎴樼暐鎰忓浘閫夋嫨銆?3. 浣跨敤纭鍒欏厹搴曪紝閬垮厤鏄庢樉閿欒鐨勮涓恒€?4. 灏嗙粡娴庛€佷睛瀵熴€侀槻瀹堛€佺鎶€銆佹垬鏂楀拰楂樼骇鍏垫帶鍒舵媶鎴愮嫭绔嬫ā鍧椼€?5. 涓哄悗缁帴鍏ヤ笓闂ㄧ殑寰搷鎺у埗鍣ㄩ鐣欐帴鍙ｃ€?
鏈」鐩殑鐩爣**涓嶆槸澶嶅埢 AlphaStar**銆? 
鐩爣鏄瀯寤轰竴涓兘璺戙€佽兘璋冭瘯銆佽兘閫愭杩唬鐨勮櫕鏃?Bot 宸ョ▼绠＄嚎銆?
---

## 涓昏鍔熻兘

### 瀹忚灞傚己鍖栧涔?
RL Agent 涓嶇洿鎺ユ帶鍒舵瘡涓€鍙崟浣嶏紝鑰屾槸閫夋嫨楂樺眰鎴樼暐鍔ㄤ綔锛屼緥濡傦細

- 缁忔祹杩愯惀
- 渚﹀療浼樺厛
- 闃插畧绋冲浐
- 灏忕嫍鍘嬪埗
- 锜戣瀭鍘嬪埗
- 锜戣瀭鍒鸿泧 Timing
- 蹇€熶簩鏈?- 蹇€熶笁鏈?- 鏀婚槻鍗囩骇浼樺厛
- 婊′汉鍙ｈ繘鏀?
杩欐牱鍙互闄嶄綆鍔ㄤ綔绌洪棿澶嶆潅搴︼紝璁╄鍒欐ā鍧楄礋璐ｅ簳灞傛墽琛屻€?
### 瑙勫垯寮忓畨鍏ㄥ厹搴?
Bot 鍖呭惈纭鍒欏畨鍏ㄩ€昏緫锛岀敤浜庡噺灏戞槑鏄句笉绋冲畾鐨勮涓猴紝渚嬪锛?
- 鍗′汉鍙?- 璧勬簮鑺变笉鍑哄幓
- 鍏抽敭绉戞妧缂哄け
- 鐭挎皵姣斾緥澶辫　
- 鎵╁紶杩囨參
- 缂哄皯闃插畧鍙嶅簲
- 宸ヤ汉娴佷笉绋冲畾

### 缁忔祹涓庣鎶€鏀寔

椤圭洰鍖呭惈浠ヤ笅妯″潡锛?
- 宸ヨ渹鐢熶骇
- 鐜嬭櫕鐢熶骇
- 閲囨皵绠＄悊
- 鎵╁紶閫昏緫
- 浜屾湰 / 涓夋湰绉戞妧鎺ㄨ繘
- 鏀婚槻鍗囩骇瑙勫垝
- 璧勬簮娑堣€楀帇鍔涙帶鍒?- 鍩虹鍏电缁勫悎鏀寔

### 鎴樻湳涓庢垬鏂楅€昏緫

Bot 鍖呭惈浠ヤ笅鎴樻湳鏀寔锛?
- 鐩爣閫夋嫨
- 楂樺湴鐩稿叧浣嶇疆淇
- 閮ㄩ槦鍗忚皟
- 鎴樻枟鍛戒护鎵€鏈夋潈绠＄悊
- 楂樼骇鍏垫帶鍒舵帴鍙?- 缁濇湜灞€鑷姩璁よ緭鍒ゆ柇

---

## 浠撳簱缁撴瀯

```text
PoorStar_Zerg_RL_OpenSource/
鈹溾攢鈹€ rl_v1/
鈹?  鈹溾攢鈹€ agent.py                    # RL 缃戠粶涓庣瓥鐣ユā鍧?鈹?  鈹溾攢鈹€ rl_controller.py            # RL 鍐崇瓥鎺у埗鍣?鈹?  鈹溾攢鈹€ rl_bot.py                   # python-sc2 Bot 涓讳綋
鈹?  鈹溾攢鈹€ macro_actions.py            # 瀹忚鍔ㄤ綔鎵ц
鈹?  鈹溾攢鈹€ state_features.py           # 鐘舵€佺壒寰佹彁鍙?鈹?  鈹溾攢鈹€ reward.py                   # 濂栧姳鍑芥暟
鈹?  鈹溾攢鈹€ hard_scaffold_manager.py    # 纭鍒欏厹搴?鈹?  鈹溾攢鈹€ economy_support.py          # 缁忔祹淇涓庤祫婧愬钩琛?鈹?  鈹溾攢鈹€ advanced_unit_control.py    # 楂樼骇鍏垫帶鍒舵帴鍙?鈹?  鈹溾攢鈹€ combat_coordinator.py       # 鎴樻枟鍛戒护鍗忚皟
鈹?  鈹溾攢鈹€ tactical_targeting.py       # 鎴樻湳鐩爣閫夋嫨
鈹?  鈹溾攢鈹€ tech_intent.py              # 绉戞妧鎰忓浘
鈹?  鈹溾攢鈹€ strategic_stage.py          # 鎴樼暐闃舵鍒ゆ柇
鈹?  鈹溾攢鈹€ map_hunt_manager.py         # 鍦板浘鎼滅储/娈嬪眬澶勭悊
鈹?  鈹斺攢鈹€ resign_detector.py          # 璁よ緭妫€娴?鈹?鈹溾攢鈹€ scripts/
鈹?  鈹溾攢鈹€ run_eval_current.ps1
鈹?  鈹溾攢鈹€ run_train_3eps_current.ps1
鈹?  鈹斺攢鈹€ run_train_20eps_current.ps1
鈹?鈹溾攢鈹€ train_rl_v2.py                  # 璁粌鍏ュ彛
鈹溾攢鈹€ play_rl_v2.py                   # 璇勪及/杩愯鍏ュ彛
鈹溾攢鈹€ analyze_rl_runs.py              # 璁粌鏃ュ織鍒嗘瀽
鈹溾攢鈹€ requirements.txt
鈹溾攢鈹€ .gitignore
鈹斺攢鈹€ README.md
```

---

## 鐜瑕佹眰

鎺ㄨ崘鐜锛?
- Windows 10 / Windows 11
- 宸插畨瑁?StarCraft II
- Python 3.10
- `python-sc2`
- PyTorch
- NumPy
- pandas
- matplotlib
- tqdm

瀹夎渚濊禆锛?
```powershell
pip install -r requirements.txt
```

鎺ㄨ崘浣跨敤 Conda 鐜锛?
```powershell
conda create -n pysc2 python=3.10
conda activate pysc2
pip install -r requirements.txt
```

---

## 杩愯璇勪及

鍦ㄩ」鐩牴鐩綍涓嬭繍琛岋細

```powershell
.\scripts\run_eval_current.ps1
```

涔熷彲浠ョ洿鎺ヨ繍琛岋細

```powershell
python play_rl_v2.py
```

---

## 杩愯灏忚妯¤缁冩祴璇?
```powershell
.\scripts\run_train_3eps_current.ps1
```

鏇撮暱鐨勮缁冿細

```powershell
.\scripts\run_train_20eps_current.ps1
```

璁粌杈撳嚭浼氳 `.gitignore` 蹇界暐锛屼笉搴旇鎻愪氦鍒颁粨搴撱€?
---

## 浠撳簱涓嶅寘鍚殑鍐呭

鏈粨搴撲笉鍖呭惈锛?
- 绉佷汉 Replay 鏁版嵁闆?- `.SC2Replay` 鏂囦欢
- 璁粌濂界殑妯″瀷鏉冮噸
- 鏈湴璁粌鏃ュ織
- API Key
- StarCraft II 娓告垙鏂囦欢
- 澶у瀷鐢熸垚杈撳嚭

杩欎簺鏂囦欢搴斾繚鐣欏湪鏈湴锛屽苟閫氳繃 `.gitignore` 鎺掗櫎銆?
---

## 寮€鍙戣矾绾?
鏍稿績鍘熷垯锛?
```text
鍏堣鍒欏熀绾裤€?鍐嶅畯瑙?RL銆?鍚庣画鎺ュ叆涓撻棬寰搷鎺у埗鍣ㄣ€?```

鏈潵鍙兘缁х画鍔犲叆锛?
- 鏇村悎鐞嗙殑濂栧姳鍑芥暟璁捐
- 鏇存竻鏅扮殑璇剧▼瀛︿範
- 鍩轰簬 Replay 鐨勫紑灞€绛栫暐
- 鐙珛寰搷璁粌鐜
- 鐏煈铻傘€侀铔囥€佹劅鏌撱€佸湴鍒恒€佸ぇ榫欑瓑涓撻棬鎺у埗鍣?- 鏇村己鐨勪睛瀵熶笌鏁屾柟绛栫暐璇嗗埆
- 璺ㄥ湴鍥俱€佽法绉嶆棌鐨勭ǔ瀹氳瘎浼?
---

## 鍏嶈矗澹版槑

鏈」鐩槸鐙珛鐮旂┒涓庡伐绋嬪疄璺甸」鐩紝涓?Blizzard Entertainment 鏃犲叧銆?
StarCraft II 鏄?Blizzard Entertainment 鐨勫晢鏍囥€傛湰浠撳簱鍙寘鍚敤鎴疯嚜琛岀紪鍐欑殑 Bot 浠ｇ爜锛屼笉鍒嗗彂浠讳綍 StarCraft II 娓告垙鏂囦欢銆?
