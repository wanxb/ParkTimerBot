# ParkTimerBot

轻量的 Telegram 停车计时与提醒机器人。

快速开始

1. 复制示例配置：

```ini
#  config.ini
[DEFAULT]
TOKEN = your-telegram-bot-token-here
```

2. 创建虚拟环境并安装依赖：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

3. 运行机器人（当前布局：源文件位于 `src/` 根）：

```bash
python src\bot.py
```

说明：也可以把 `src` 目录加入 `PYTHONPATH` 并使用模块方式运行。

Git / 上传到 GitHub（自动化准备）

1. 初始化本地仓库并提交：

```powershell
git init
git config user.email "you@example.com"
git config user.name "Your Name"
git add .
git commit -m "Initial commit: project scaffold"
```

2. 在 GitHub 上创建仓库后，添加远程并推送（示例）：

```powershell
git remote add origin https://github.com/<your-username>/<repo>.git
git branch -M main
git push -u origin main
```

注意事项：
- 请先将 `config.example.ini` 复制为 `config.ini` 并填写 `TOKEN`，不要将 `config.ini` 提交到远程仓库。
- `.gitignore` 中已包含 `config.ini` 和其他敏感/依赖文件。

说明

- 请勿将真实 `config.ini` 提交到仓库；仓库中保留 `config.example.ini` 作为示例。
- 若要打包或安装为可执行命令，可添加 `pyproject.toml` 或 `setup.cfg`。

许可证：MIT
