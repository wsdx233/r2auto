# r2auto

`r2auto` 是一个基于 Radare2 和 OpenAI 模型的自动化逆向工程代理工具。它结合了强大的二进制分析框架 Radare2 与大语言模型的推理能力，能够自动执行分析任务、编写处理脚本，并以对话形式辅助逆向工程。

## ✨ 功能特点

- **智能代理**: 集成 LLM ，智能规划分析步骤。
- **Radare2 集成**: 通过 `r2pipe` 直接控制 Radare2 核心执行命令。
- **Python 代码执行**: Agent 可以动态编写并执行 Python 脚本，用于复杂的数据解析和逻辑处理。
- **富文本终端**: 使用 `rich` 库构建，提供代码高亮、Markdown 渲染和流式输出体验。
- **交互式分析**: 支持连续对话，用户可以随时介入指导分析方向。

## 🛠️ 环境要求

- Python 3.8+
- [Radare2](https://github.com/radareorg/radare2) (确保 `r2` 命令在系统 PATH 中可用)
- OpenAI API Key (或兼容 OpenAI 格式的 API，如 DeepSeek, LocalAI 等)

## 📦 安装与配置

1. **安装依赖**

   ```bash
   pip install r2pipe python-dotenv openai rich
   # 推荐使用 uv
   uv sync
   ```

2. **配置环境变量**

   在项目根目录下创建一个 `.env` 文件，填入你的模型服务配置：

   ```ini
   #.env
   OPENAI_BASE_URL=https://api.openai.com/v1
   OPENAI_API_KEY=sk-your-api-key
   OPENAI_MODEL=gpt-5.2
   # http_proxy=http://127.0.0.1:7890 (可选)
   # https_proxy=http://127.0.0.1:7890 (可选)
   ```

## 🚀 使用方法

```bash
uv run main.py <target_binary> [prompt]
```

### 参数说明
- `target_binary`: 目标二进制文件的路径 (exe, elf, mach-o 等)。
- `prompt`: (可选) 初始分析指令，默认为 "Analyze the main function logic."。

### 示例

**1. 基础启动**
```bash
uv run main.py ./crackme.exe
```

**2. 指定分析任务**
```bash
uv run main.py ./crackme.exe "找出验证 License Key 的核心逻辑并尝试通过 r2 模拟或分析算法"
```

## 🤖 交互指南

工具启动后会自动加载文件并初始化分析：

1. **Observe**: Agent 会“思考”并输出即将执行的 Radare2 命令或 Python 代码。
2. **Execute**: 自动执行命令并展示结果。
3. **Loop**: Agent 根据结果决定下一步操作，直到完成任务或需要用户输入。
4. **Input**: 当出现 `User Input` 提示时，你可以输入新的指令，或者输入 `q` / `exit` 退出。

## 📝 License

MIT
