import os
import re
import sys
import argparse
import time
import io
import contextlib
import subprocess
import traceback
from typing import List, Optional, Tuple

# 第三方库
import r2pipe
from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.status import Status
from rich.style import Style
from rich.text import Text
from rich.theme import Theme
from rich.syntax import Syntax
from rich.live import Live
from rich.spinner import Spinner

# 加载环境变量
load_dotenv()

# 配置 Rich 终端
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "success": "green",
    "cmd": "bold yellow",
    "py": "bold blue",
    "thinking": "italic blue"
})
console = Console(theme=custom_theme)

class R2AutoAgent:
    def __init__(self, target_file: str):
        self.target_file = target_file
        self.client = self._init_openai()
        self.r2 = self._init_r2()
        self.history = []
        self.system_prompt = self._get_system_prompt()
        
    def _init_openai(self):
        """初始化 OpenAI 客户端"""
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        if not base_url or not api_key:
            console.print("[danger]Error: .env file missing OPENAI_BASE_URL or OPENAI_API_KEY[/danger]")
            sys.exit(1)
        return OpenAI(base_url=base_url, api_key=api_key)

    def _init_r2(self):
        """初始化 r2pipe"""
        try:
            console.print(f"[info]Loading {self.target_file} into Radare2...[/info]")
            r2 = r2pipe.open(self.target_file)
            return r2
        except Exception as e:
            console.print(f"[danger]Failed to open file with r2: {e}[/danger]")
            sys.exit(1)

    def _get_system_prompt(self):
        return """
You are an expert Reverse Engineering Agent named 'r2auto'. You are operating inside a Radare2 environment via r2pipe.
Your goal is to analyze the binary provided based on the user's request.

**Capabilities:**
1. **Execute R2 Commands**: Wrap standard r2 commands in double brackets. 
   - Syntax: `[[cmd]]`
   - Example: `[[aaa]]`, `[[pdf @ main]]`, `[[iI]]`

2. **Execute Python Code**: You can write Python scripts to process data or handle complex logic.
   - Syntax: Wrap code in `<py>` and `</py>` tags.
   - **Context**: The variable `r2` is available (r2pipe instance). Use `r2.cmd('cmd')` to run commands inside Python.
   - Example: 
     <py>
     funcs = r2.cmd('afl').splitlines()
     print(f"Found {len(funcs)} functions")
     </py>

**Protocol:**
1. **Think**: Analyze the current state.
2. **Execute**: Output r2 commands or Python blocks. You can mix them. They will be executed in order.
3. **Wait**: After outputting commands, stop your response. The system will execute them and give you the output.
4. **Interact**: If you need the user's input, clarification, or confirmation to proceed, output `[[ask]]` at the end.
5. **Format**: Use Markdown for your explanations. Be concise but professional.

**Important:**
- respond [end] after you finish your all command and python code calls.
- Use `pdf~HEAD` for large functions to avoid huge output.
- Only use Python when r2 commands alone are insufficient for data parsing or logic.
- Rely solely on tool outputs.
"""

    def run_r2_command(self, cmd: str) -> str:
        try:
            cmd = cmd.strip()
            result = self.r2.cmd(cmd)
            return result if result else "(No Output)"
        except Exception as e:
            return f"R2 Error executing '{cmd}': {str(e)}"

    def run_python_code(self, code: str) -> str:
        buffer = io.StringIO()
        try:
            exec_globals = {
                "r2": self.r2,
                "os": os,
                "sys": sys,
                "re": re,
                "json": __import__('json')
            }
            with contextlib.redirect_stdout(buffer):
                exec(code, exec_globals)
            output = buffer.getvalue()
            return output if output else "(Python executed successfully, no output)"
        except Exception:
            return f"Python Execution Error:\n{traceback.format_exc()}"

    def parse_response(self, text: str) -> Tuple[List[dict], bool]:
        actions = []
        has_ask = "[[ask]]" in text
        pattern = re.compile(r"(\[\[(.*?)\]\]|<py>(.*?)</py>)", re.DOTALL)
        matches = pattern.finditer(text)
        
        for match in matches:
            r2_cmd = match.group(2)
            py_code = match.group(3)
            if r2_cmd:
                cmd_content = r2_cmd.strip()
                if cmd_content != "ask":
                    actions.append({"type": "r2", "content": cmd_content})
            elif py_code:
                actions.append({"type": "python", "content": py_code.strip()})
        
        return actions, has_ask

    def format_display_content(self, content: str) -> str:
        """辅助函数：处理显示时的文本替换，增加高亮"""
        return content.replace("[[", "`[[").replace("]]", "]]`") \
                      .replace("<py>", "\n```python\n").replace("</py>", "\n```\n")

    def chat_loop(self, initial_prompt: str):
        """主循环"""
        self.history = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Target: {self.target_file}\nRequest: {initial_prompt}"}
        ]
        
        console.rule("[bold cyan]r2auto Session Started")

        while True:
            # 1. LLM 思考并流式生成回复
            full_content = ""
            
            # 准备参数
            model_name = os.getenv("OPENAI_MODEL", "gpt-4")
            req_kwargs = {
                "model": model_name,
                "messages": self.history,
                "stream": True,
            }
            # 启用 Thinking (默认使用 8192 token 额度)
            req_kwargs["extra_body"] = {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 8192
                }
            }
            
            # 状态与动画字符
            is_thinking = False
            spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            
            # 设置超时和重试
            req_kwargs['timeout'] = 60.0
            max_retries = 3

            try:
                # 使用 transient=True 让 Live 结束后自动清除状态栏，避免残留
                with Live(console=console, refresh_per_second=10, transient=True) as live:
                    for attempt in range(max_retries):
                        full_content = "" # 重置缓冲区
                        thinking_content = "" # 重置 thinking 缓冲区
                        
                        # 流式输出状态变量
                        printed_len = 0
                        in_code_block = False
                        code_line_count = 1
                        
                        try:
                            # Initial waiting state or Retrying state
                            if attempt > 0:
                                live.update(Group(
                                    Panel(f"Request timeout or failed. Retrying ({attempt+1}/{max_retries})...", title="r2auto", border_style="yellow"),
                                    Spinner("dots", text=" Retrying...", style="italic yellow")
                                ))
                            else:
                                live.update(Group(
                                    Panel("Requesting...", title="r2auto", border_style="cyan"),
                                    Spinner("dots", text=" Waiting...", style="italic blue")
                                ))
                            
                            # 发起流式请求，如果不支持 thinking 则回退
                            try:
                                stream = self.client.chat.completions.create(**req_kwargs)
                            except Exception as e:
                                if "thinking" in str(e).lower() or "parameter" in str(e).lower() or "400" in str(e):
                                    # console.print("[dim]Thinking parameter not supported, disabling...[/dim]")
                                    req_kwargs.pop("extra_body", None)
                                    stream = self.client.chat.completions.create(**req_kwargs)
                                else:
                                    raise e

                            for chunk in stream:
                                if not chunk.choices:
                                    continue
                                
                                delta = chunk.choices[0].delta
                                delta_content = getattr(delta, 'content', '') or ""
                                # 检测 reasoning 
                                delta_reasoning = getattr(delta, 'reasoning_content', '') or ""
                                if not delta_reasoning and hasattr(delta, 'model_extra'):
                                    delta_reasoning = (delta.model_extra or {}).get('reasoning_text', '') or ""
                                
                                # 如果有 reasoning 内容，标记为 thinking 状态
                                if delta_reasoning:
                                    is_thinking = True
                                    thinking_content += delta_reasoning
                                elif delta_content:
                                    is_thinking = False # 开始输出内容 (或混合输出时视为 Outputing)
                                    
                                if delta_content:
                                    full_content += delta_content

                                # --- 流式增量输出逻辑 (修复长文本闪烁问题) ---
                                if full_content:
                                    formatted_text = self.format_display_content(full_content)
                                    # 检查是否有新的完整行
                                    if '\n' in formatted_text[printed_len:]:
                                        available_text = formatted_text[printed_len:]
                                        last_newline_idx = available_text.rfind('\n')
                                        
                                        if last_newline_idx != -1:
                                            chunk_to_print = available_text[:last_newline_idx + 1]
                                            lines = chunk_to_print.split('\n')
                                            # split('a\n') -> ['a', ''] 所以忽略最后一个空元素
                                            lines_to_process = lines[:-1]
                                            
                                            for line in lines_to_process:
                                                stripped = line.strip()
                                                
                                                if stripped == "```python":
                                                    in_code_block = True
                                                    code_line_count = 1
                                                    # 打印一个小标题区分代码块
                                                    console.print(Text("  Python Code:", style="dim cyan"))
                                                    continue
                                                if stripped == "```" and in_code_block:
                                                    in_code_block = False
                                                    console.print() # 代码块结束空一行
                                                    continue

                                                if in_code_block:
                                                    # 使用 Syntax 高亮代码行
                                                    console.print(
                                                        Syntax(line, "python", theme="monokai", 
                                                               line_numbers=True, start_line=code_line_count,
                                                               word_wrap=True, padding=(0, 1))
                                                    )
                                                    code_line_count += 1
                                                else:
                                                    # 普通 Markdown 文本
                                                    if line:
                                                         console.print(Markdown(line))
                                                    else:
                                                         console.print("")

                                            printed_len += (last_newline_idx + 1)

                                # --- 底部状态栏更新 ---
                                spinner_idx = int(time.time() * 12) % len(spinner_chars)
                                spinner_char = spinner_chars[spinner_idx]
                                
                                if is_thinking:
                                    # 显示最后5行思考过程
                                    lines = [l for l in thinking_content.split('\n') if l.strip()]
                                    tail = "\n".join(lines[-5:]) if lines else ""
                                    
                                    status_header = Text(f"{spinner_char} Thinking...", style="italic blue")
                                    if tail:
                                        status_bar = Group(
                                            status_header, 
                                            Text(tail, style="dim white")
                                        )
                                    else:
                                        status_bar = status_header
                                else:
                                    status_bar = Text(f"{spinner_char} Generating Response...", style="green")

                                live.update(Panel(status_bar, title="r2auto Info", border_style="dim blue"))
                                    
                                if "[end]" in full_content and not is_thinking:
                                    break
                            
                            # 成功跳出内层循环
                            break
                        
                        except Exception as e:
                            # 如果是循环中的异常（超时等）
                            if attempt < max_retries - 1:
                                continue
                            else:
                                raise e # 抛出给外层捕获

            except Exception as e:
                console.print(Panel(f"API Error after {max_retries} attempts: {e}", title="Error", style="danger"))
                sys.exit(1)

            # 流结束后，full_content 即为完整回复
            self.history.append({"role": "assistant", "content": full_content})

            # 2. 解析动作序列 (逻辑不变)
            actions, has_ask = self.parse_response(full_content)

            # 3. 执行动作 (逻辑不变)
            if actions:
                execution_results = []
                for action in actions:
                    act_type = action["type"]
                    act_content = action["content"]

                    if act_type == "r2":
                        console.print(f"[cmd]➜ R2 Command: {act_content}[/cmd]")
                        with Status(f"Running r2 '{act_content}'...", spinner="bouncingBall", spinner_style="yellow"):
                            output = self.run_r2_command(act_content)
                        execution_results.append(f"R2 Command: [[{act_content}]]\nOutput:\n{output}")
                    
                    elif act_type == "python":
                        console.print(f"[py]➜ Executing Python Code...[/py]")
                        console.print(Syntax(act_content, "python", theme="monokai", line_numbers=False))
                        with Status(f"Running Python logic...", spinner="aesthetic", spinner_style="blue"):
                            output = self.run_python_code(act_content)
                        
                        if len(output) < 5000:
                            console.print(Panel(output, title="Python Output", border_style="dim blue"))
                        else:
                            console.print(f"[dim]Python output length: {len(output)} chars[/dim]")
                        execution_results.append(f"Python Code Execution:\nOutput:\n{output}")

                result_text = "\n".join(execution_results)
                if len(result_text) > 30000:
                    result_text = result_text[:30000] + "\n... [Output Truncated] ..."

                self.history.append({
                    "role": "user", 
                    "content": f"Execution Results:\n{result_text}"
                })
                
                if not has_ask:
                    continue

            # 4. 处理询问 ([[ask]])
            if has_ask:
                user_input = Prompt.ask("[bold green]User Input[/bold green]")
                if user_input.lower() in ['exit', 'quit', 'q']:
                    console.print("[info]Exiting r2auto.[/info]")
                    break
                self.history.append({"role": "user", "content": user_input})
                continue
            
            # 5. 无动作且无询问
            if not actions and not has_ask:
                console.print("[warning]Agent paused. Waiting for input...[/warning]")
                user_input = Prompt.ask("[bold green]User Input[/bold green]")
                if user_input.lower() in ['exit', 'quit', 'q']:
                    break
                self.history.append({"role": "user", "content": user_input})

def main():
    parser = argparse.ArgumentParser(description="r2auto: AI-powered automated reverse engineering with Radare2 & Python")
    parser.add_argument("file", help="Path to the binary file to analyze")
    parser.add_argument("prompt", help="Initial analysis instruction", nargs='?', default="Analyze the main function logic.")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        console.print(f"[danger]File not found: {args.file}[/danger]")
        sys.exit(1)
        
    agent = R2AutoAgent(args.file)
    agent.chat_loop(args.prompt)

if __name__ == "__main__":
    main()