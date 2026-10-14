# VideoToText

将 YouTube / Bilibili 视频转换为带时间戳和说话人标签的文字，输出 TXT、JSON、SRT、VTT。语音识别、文字对齐和说话人区分都使用本地模型；下载视频、依赖和模型需要联网。

当前自动安装脚本支持 **Windows 10/11 x64 + PowerShell 5.1 或更新版本**。可使用 NVIDIA GPU，也可仅使用 CPU。暂不提供 macOS / Linux 的自动安装流程。

## 三步使用

先安装 Git，以便 clone 项目。首次模型准备前，在 [Hugging Face](https://huggingface.co/) 登录，接受 [community-1 模型访问条件](https://huggingface.co/pyannote/speaker-diarization-community-1)，并创建自己的 [READ Token](https://huggingface.co/settings/tokens)。这个模型要求用户在网页完成授权，脚本不能替代这一步。

在 PowerShell 执行：

```powershell
git clone https://github.com/ubermenzch/VideoToText.git
cd VideoToText

# 默认：虚拟环境，自动检测 NVIDIA GPU，否则使用 CPU
.\setup.cmd

# 单个视频；请用引号包住整个链接
powershell -NoProfile -ExecutionPolicy Bypass -File .\transcribe-video.ps1 -Url "https://www.youtube.com/watch?v=VIDEO_ID"
```

安装过程中提示 Token 时，输入你自己的 READ Token，输入内容不会显示。首次运行会下载依赖和模型，耗时取决于网络和硬件。再次运行安装命令可重试并复用已下载的大文件。

不含额外查询参数的链接也可用更短的 `.\transcribe.cmd "视频链接"`。Windows PowerShell 5.1 调用 CMD 时可能不保留链接中的 `&` 引号；带查询参数的链接请使用上面的 PowerShell 入口。

安装脚本会检查 Python 3.11 x64、VC++ 运行库，并在缺少时下载官方安装程序。Python 默认安装到项目的 `.tools/python`，不主动修改持久 PATH；已有合适版本则复用。FFmpeg shared、Deno、模型和缓存都放在项目目录。VC++ 是 Windows 共享运行库，缺少时其安装程序可能要求管理员授权。NVIDIA 显卡驱动由用户维护；无需额外安装完整 CUDA Toolkit。

## 安装选择

```powershell
# 推荐：所有 Python 依赖放在项目 .venv
.\setup.cmd -InstallMode venv

# 直接安装到选定的本机 Python 3.11（会改变该解释器已有依赖）
.\setup.cmd -InstallMode system -Python "C:\Path\To\Python311\python.exe"

# 无 NVIDIA GPU，或希望较小的模型
.\setup.cmd -Device cpu -Model small

# NVIDIA GPU，使用 large-v3
.\setup.cmd -Device cuda -Model large-v3

# 仅安装并检查依赖，不下载模型、不要求 Token
.\setup.cmd -SkipModels

# 提前准备四种常见语言的对齐模型（PowerShell 原生脚本支持数组）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& './setup.ps1' -AlignmentLanguages zh,en,fr,de"
```

CUDA 模式使用 PyTorch 2.8.0 / CUDA 12.8 的官方预编译运行库。GPU 模式默认 large-v3，CPU 模式默认 small；tiny、base、small、medium、large-v3 均为多语言模型。更大的模型通常更准确，也更占内存。CPU 可以运行完整流程，但长视频可能很慢。6 GB 显存的 NVIDIA GPU 已完成 large-v3 约 107 分钟英文访谈的本地测试；其他硬件并未全部验证。安装期间需要数 GB 下载空间，GPU 完整环境建议预留至少 20 GB 磁盘空间和 16 GB 系统内存，实际消耗还取决于视频长度。

默认只提前下载识别和说话人模型；对齐模型在第一次遇到对应语言时下载，避免一次安装所有语言模型。中文、英文、法语、德语均可用。模型支持多语言不意味着一个文件中的频繁语言切换一定能正确自动识别；当前对齐流程按文件的主要语言处理，混合语言材料建议按语言分段。

## 转写命令

```powershell
# 自动判断主要语言与说话人数
powershell -NoProfile -ExecutionPolicy Bypass -File .\transcribe-video.ps1 -Url "https://www.bilibili.com/video/BV.../"

# 明确指定主要语言：zh / en / fr / de
powershell -NoProfile -ExecutionPolicy Bypass -File .\transcribe-video.ps1 -Url "https://www.youtube.com/watch?v=VIDEO_ID" -Language en

# 已知有两名说话人
powershell -NoProfile -ExecutionPolicy Bypass -File .\transcribe-video.ps1 -Url "https://www.youtube.com/watch?v=VIDEO_ID" -Language en -Speakers 2

# 只下载并提取音频
powershell -NoProfile -ExecutionPolicy Bypass -File .\transcribe-video.ps1 -Url "https://www.youtube.com/watch?v=VIDEO_ID" -DownloadOnly

# 使用 CPU 或更小的模型（首次使用该模型时下载）
powershell -NoProfile -ExecutionPolicy Bypass -File .\transcribe-video.ps1 -Url "https://www.youtube.com/watch?v=VIDEO_ID" -Device cpu -Model small
```

无需手动激活虚拟环境。安装选择保存在本机 `.videototext.json`，启动器会调用对应 Python。所有项目资源均根据脚本所在目录定位，clone 到任意目录（包含空格或中文）都可重新安装使用；已创建的 Python 虚拟环境本身不保证可搬迁，移动现有项目后应重建 `.venv`。

输出位于 `results/<视频 ID>/`：

| 文件 | 内容 |
| --- | --- |
| `transcript.txt` | 时间戳、说话人、正文 |
| `plain.txt` | 纯正文，适合复制给语言模型 |
| `transcript.json` | 结构化文字、单词时间戳和说话人 |
| `transcript.srt` / `transcript.vtt` | 字幕 |
| `audio.wav` | 16 kHz 单声道音频 |
| `status.json` | 执行状态 |

说话人按音频特征区分，再按时间对应到文字；标签是 `SPEAKER_00` 等匿名编号，不能自动确定真实身份。重叠发言、很短的插话、噪声和背景音乐会影响结果。自动转写可能出现漏词、错词或幻觉，关键引用应听原音复核。

## 隐私与凭据

- 本项目不调用云端转写 API，不把音频上传到 Hugging Face 或其他识别服务。
- Token 只用于取得模型访问权限，不写入脚本、命令参数或 Git 提交。优先使用进程环境变量 `HF_TOKEN`；交互输入时尝试用 Windows DPAPI 加密保存到 `.secrets/`，绑定当前 Windows 用户/电脑。DPAPI 不可用时仅在安装进程中使用，下一次需重新提供 Token。
- `.gitignore` 排除 Token、密钥、环境配置、缓存、模型、下载、转写结果和日志。日志可能包含链接、视频标题、转写正文及本地路径，不要把日志直接公开。
- `.gitignore` 不是加密或访问控制。不要手动强制提交这些目录，分享文件前请检查内容。
- 删除本机 `.secrets/` 可清除本项目保存的 HF 凭据；要撤销 Token，应到 Hugging Face 设置中操作。
- GPU/CPU 软件依赖和模型都有各自的许可证及访问条件；本仓库不分发模型权重、视频或第三方二进制。

## 常见问题

- **模型提示 401/403**：确认 READ Token 有效，且同一 HF 账号已接受 community-1 条件。如果设置 `HF_TOKEN`，它会优先于保存的凭据。
- **CUDA 无法使用或显存不足**：更新适配显卡的 NVIDIA 驱动，或使用 `-Device cpu` / 较小的 `-Model`；本项目不会自动更改显卡驱动。
- **更改模型、语言或说话人数后提示缓存冲突**：先将对应 `results/<视频 ID>` 文件夹改名，再重新运行。重试相同设置会复用已完成的识别、对齐和说话人阶段。
- **YouTube/Bilibili 下载失败**：站点限制、登录要求、网络与平台变化可能导致失败。本项目默认下载单个公开视频，不自动读取浏览器 Cookie。确认链接和网络；若 yt-dlp 已有修复，可用所选 Python 执行 `python -m pip install --upgrade "yt-dlp[default]"`，再重试。安装脚本固定已验证版本，重新安装会恢复该版本。
- **PowerShell 显示乱码**：用支持 UTF-8 的编辑器打开输出，或执行 `Get-Content -Encoding UTF8 .\results\<视频 ID>\transcript.txt`。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试包含中文/空格路径、从项目目录之外启动、虚拟环境/本机解释器选择、含 `&` 的视频链接与参数传递，以及导出文本的保留检查。GitHub Actions 运行不下载模型的启动器测试和语法检查；不把 CI 通过等同于真实模型识别准确率。

模型与底层工具：[WhisperX](https://github.com/m-bain/whisperX)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)、[yt-dlp](https://github.com/yt-dlp/yt-dlp)、[PyTorch](https://pytorch.org/)、[FFmpeg](https://ffmpeg.org/)、[Deno](https://deno.com/)。
