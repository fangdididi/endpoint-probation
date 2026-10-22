# Endpoint Probation · 端点试用期

[English](README.md) · **简体中文**

> 每个 AI 端点都从试用期开始。信任要靠你自己跑出来的证据挣——不靠价目表、不靠截图，也不靠模型自报家门。

**Endpoint Probation** 是一个给 Claude Code、Codex、Cursor 等编码智能体用的技能。它判断一个 AI API 端点——便宜的中转站、代理商、团队网关、聚合平台、自建代理，或者是突然“手感不对”的官方模型别名——配不配承担真实工作；并且只在有备份、有一行回滚命令的前提下，才把你的工具切过去。

配套的 `probation.py` 是一个零依赖的 Python 辅助脚本：对候选端点和可信参照端点跑同一组固定探针、标出问题、核对账单、检查试用期卡片、备份智能体配置。内置的 `selftest` 会对着两个本地假端点完整演练一遍，让你在花一分钱之前就看清每种猫腻长什么样。

## 为什么需要它

从外面看，每个端点都一样：一个 base URL、一个 key、一个模型名。背后可能正在发生：

- HTTP `200`，流里却夹着限流错误，客户端把它当成模型的回答显示出来；
- 标签上是旗舰型号，背后是便宜模型——尤其在长请求、贵请求上；
- 长上下文的开头被悄悄裁掉，智能体忘了刚读过的文件；
- 隐藏倍率、虚增 token，或者缓存优惠被中转吃掉；
- 上午十点好好的，晚高峰没法用；下周连同余额一起消失；
- 你的 prompt、代码和 key 经过一个你一无所知的运营方。

大多数人判断这一切的方式是“它回了我一句 hello”。这个技能用一张卡片、六项考核、一个判决来代替它。

## 功能特点

- **冻结标准**：通过门槛在测试前根据用途（工具、敏感度、最长 prompt、工作时段）写好；出结果后修改，就算一次新的试用期。
- **六项考核**：管道 · 身份 · 保真 · 计量 · 天气 · 托管，每项都有明确的问题和明确的判定信号。
- **基于参照的身份核验**：用固定的英文、中文、代码、混合符号文本，对比与官方端点的 prompt token 数；未知模型名和超限报错也一并对比。“问它是谁”明确不算证据。
- **诚实的统计**：带 Wilson 区间的成功率、候选与参照之间的 Fisher 精确检验、首字时间 p50/p95、流内最长停顿。
- **证据标签**：每条结果都标 `[ran]`、`[seen]`、`[said]` 或 `[gap]`；卡片检查器会拒绝靠 `[gap]` 放行，或身份、计费只有 `[said]` 的放行。
- **五种判决**：CLEARED · CLEARED-WITH-LIMITS · EXTENDED · REJECTED · INCONCLUSIVE，附写明的限制条件和重新试用触发条件。
- **安全切换**：备份 Claude Code、Codex、Gemini CLI、OpenCode、Aider、Continue、Cursor 的配置文件并生成 `RESTORE.sh`，并建议用最小范围切换（项目级设置、Codex profile）。
- **考察期**：可重复的“是不是变笨了”流程：固定任务、相同尝试预算、保留全部样本、比较区间。
- **中英双语**：技能正文中英文完整版本；`report`、`bill`、`card` 都支持中文（`--lang zh`）。

## 安装

技能就是包含 `SKILL.md`（英文）和 `SKILL.zh-CN.md`（中文）的整个文件夹。请克隆整个仓库，这样 `scripts/` 和 `examples/` 会一起带上。

**Claude Code**

```bash
git clone https://github.com/fangdididi/endpoint-probation.git ~/.claude/skills/endpoint-probation
```

**Codex / 读取 `~/.agents/skills` 的智能体**

```bash
git clone https://github.com/fangdididi/endpoint-probation.git ~/.agents/skills/endpoint-probation
```

**Cursor**（项目技能目录）

```bash
git clone https://github.com/fangdididi/endpoint-probation.git .cursor/skills/endpoint-probation
```

**其他智能体**（Gemini CLI、OpenCode、Windsurf、Cline、Kimi、各类聊天应用）：把 `SKILL.zh-CN.md`（中文对话）或 `SKILL.md` 粘贴到它的指令或项目规则里，或者直接让它从本仓库地址安装。

辅助脚本只需要 Python 3.8+，没有其他依赖。

## 使用方法

直接对智能体说：

- “帮我给这个中转站做一次试用期考核，我想配进 Claude Code。”
- “这三家网关给我们的 Codex 用，比一比哪家能通过。”
- “余额掉得比用量快，帮我查一下计量。”
- “群里都说这周模型变笨了，是真的还是噪声？”
- "Put this relay on probation before I use it."

或者直接用脚本：

```bash
# 0. 免费看一遍所有失败形态
python3 scripts/probation.py selftest

# 1. 开卡，测试前把标准填好
python3 scripts/probation.py card new --name "青柚中转" --lang zh

# 2. 在官方端点跑参照（几分钱）
export REF_KEY=...
python3 scripts/probation.py probe --base https://api.openai.com/v1 --protocol openai \
  --model <模型 ID> --key-env REF_KEY --label official --out runs/official.jsonl

# 3. 用一次性 key 跑候选（每个时间段各跑一次）
export CANDIDATE_KEY=...
python3 scripts/probation.py probe --base https://api.relay.example/v1 --protocol openai \
  --model <声称的模型> --key-env CANDIDATE_KEY --label qingyou --out runs/qingyou.jsonl

# 4. 看旗标、对账单
python3 scripts/probation.py report runs/qingyou.jsonl --ref runs/official.jsonl --lang zh
python3 scripts/probation.py bill runs/qingyou.jsonl --in-price 2.5 --out-price 10 \
  --multiplier 0.3 --charged 0.05 --ref runs/official.jsonl --lang zh

# 5. 写判决、检查卡片、备份配置、小范围切换
python3 scripts/probation.py card lint --path PROBATION.md
python3 scripts/probation.py backup
```

key 只从你指定的环境变量读取，从不打印、从不落盘。证据文件里只有截断的回答、用量数字、耗时和响应头名称。

## 输出示例

耍滑端点对比老实参照（来自 `selftest`）：

```text
## 旗标
- [FAIL] plumbing: 2 call(s) showed 'error-in-200' - a failure dressed up as success
- [FAIL] identity: an unknown model name was accepted with 200 - the router answers with something else
- [FAIL] fidelity: long-document recall 0/2 - the start of long prompts may be cut
- [FAIL] identity: pin-zh: 72.0 prompt tokens vs 48.0 on the reference (x1.50) - different tokenizer or padded billing
- [FAIL] fidelity: long prompt counted as 2706.0 tokens vs 3731.0 on the reference - prompt likely trimmed
- [WARN] weather: median time-to-first-token 351ms vs 51ms on the reference

机器结论（仅供参考，最终判决写在卡片里）: FAIL
```

完整示例卡片：

- [`examples/miniprogram-relay.zh-CN.md`](examples/miniprogram-relay.zh-CN.md)：给小程序客服机器人用的“官方价 0.3 倍”中转——流里藏错误、token 数 1.5 倍、长 prompt 被裁，**REJECTED**。
- [`examples/claude-code-gateway.en.md`](examples/claude-code-gateway.en.md)：给公开文档仓库的 Claude Code 用的网关——**CLEARED-WITH-LIMITS**（仅限公开仓库、prompt 小于 10 万 token、21 点后切回官方、余额设上限）。

## 六项考核一览

| 考核 | 问题 | 判定信号 |
|---|---|---|
| 管道 | 请求能否变成完整、如实标注的回答？ | 成功率区间、结束标记、200 里有没有错误 |
| 身份 | 是不是标签上的模型？ | 固定文本 token 数对比参照、未知模型与超限报错、结束原因词表 |
| 保真 | 请求是否完整送达？ | 长文档第一行能否召回、上报的 prompt 大小 |
| 计量 | 扣费是否合理？ | 余额减少 vs 用量 × 价格 × 倍率、缓存优惠 |
| 天气 | 你干活的时段能不能用？ | 首字时间 p50/p95、停顿、分时段成功率 |
| 托管 | 你的数据和钱会怎样？ | 运营主体、条款、保留期、key 权限、余额敞口 |

## 文件结构

```text
endpoint-probation/
├── SKILL.md                         # 技能正文（英文）
├── SKILL.zh-CN.md                   # 技能正文（中文）
├── README.md / README.zh-CN.md
├── LICENSE
├── scripts/
│   ├── probation.py                 # probe · report · bill · card · backup · selftest
│   └── mock_endpoint.py             # 老实 / 耍滑两种假端点，用于演练和测试
├── examples/
│   ├── claude-code-gateway.en.md    # 有条件通过的卡片
│   └── miniprogram-relay.zh-CN.md   # 不通过的卡片
└── tests/
    └── test_probation.py            # 离线测试：python3 -m unittest discover -s tests -v
```

## 局限

- 支持 OpenAI 风格的 chat completions 和 Anthropic 风格的 messages。其他协议（比如只支持 Responses 的端点）需要按同样思路手工测。
- 身份证据对粗暴的换模型和计费灌水很有效，对同家族、同分词器的替身较弱。身份考核干净，应理解为“没有发现替换的证据”，而不是一张证书。
- 脚本从不评判托管，这一项永远需要人来做。
- 试用期检验的是行为。某个中转是否符合模型厂商的条款，是另一个问题。

## 许可证

[MIT](LICENSE) © fangdididi
