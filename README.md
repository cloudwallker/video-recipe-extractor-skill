<a id="readme-top"></a>

<div align="center">
  <h1>视频菜谱长图</h1>
  <p><strong>把做菜视频，整理成一张能照着做的菜谱</strong><br>
  <sub>一张真实主图 · 逐条文字步骤 · 沿用视频用量</sub></p>
  <p><code>video-recipe-extractor</code></p>
  <p>中文 · <a href="README_EN.md">English</a></p>
  <p>
    <a href="#能做什么">了解能力</a> &nbsp;·&nbsp;
    <a href="#成品案例">成品案例</a> &nbsp;·&nbsp;
    <a href="#快速开始"><strong>快速开始</strong></a> &nbsp;·&nbsp;
    <a href="#用一句话调用">一句话调用</a> &nbsp;·&nbsp;
    <a href="#命令行">命令行</a>
  </p>
</div>

## 项目简介

从做菜视频、字幕和真实画面提取食材与做法，制作“顶部一张视频主图＋下方逐条文字步骤”的字幕风格菜谱长图。沿用原视频量词，不强制换算克数，不在成品中显示缺失用量，也不额外生成步骤配图。

## 能做什么

- **从做菜视频整理菜谱**：给出本地视频或公开链接，结合字幕、讲解和真实画面，提取食材、下料顺序、火候与关键时间。
- **一张主图，下面写步骤**：顶部保留一张真实视频画面，主图底部写菜名，下方逐条排做法。白字黑描边，条带之间没有空隙，背景复用同一张主图的裁片。
- **沿用原视频的用量**：视频说“2个”“一勺”“少许”，就保留这些表达；明确给出克数时照录。没有依据的数值直接省略，不补造克数，也不在成品里标记“未知”。
- **保留能照着做的细节**：记录先后顺序、小火或大火、煎煮时长、出锅状态；每条步骤关联字幕片段或视频帧，方便回看核对。
- **用一句话交给 Agent**：在 Codex 中调用 Skill，由 Agent 理解视频，脚本负责素材准备和排版。无需额外配置模型 API 密钥。

默认宽度为 **1440 像素**，主图等比缩放，图片高度随步骤数量自然增长。长句可以换行，不强制裁成固定比例，也不额外搭配步骤照片。

## 成品案例

**番茄炒鸡蛋｜一张成品主图，8条做法步骤**

<div align="center">
  <a href="examples/tomato-eggs/recipe.jpg">
    <img src="examples/tomato-eggs/recipe.jpg" alt="番茄炒鸡蛋菜谱长图：顶部是一张真实视频成品图，下方8条白字黑描边的文字步骤" width="600">
  </a>
</div>

来源：[美食作家王刚R的《番茄炒鸡蛋》](https://www.bilibili.com/video/BV13p411d7oQ/)。主图取自视频 **02:08**，成品尺寸为 **1440 × 1770**。本例使用1080p原视频，逐帧核对画面中的字幕后整理步骤，保留作者水印。

图中文字是根据视频整理后绘制的菜谱。食材用量、调味顺序以及“先勾薄芡，再回蛋”等操作均经过真实画面核对。

[查看原图](examples/tomato-eggs/recipe.jpg) · [查看食材清单、做法与核对时间点](examples/tomato-eggs/recipe.md)

## 快速开始

### 1. 安装 Skill

先克隆仓库，并显式保留技能安装目录名：

```bash
git clone https://github.com/cloudwallker/video-recipe-extractor-skill.git video-recipe-extractor
```

下载本项目，把整个 `video-recipe-extractor` 文件夹复制到 Codex 的 Skills 目录。以下命令在该文件夹的**上一级目录**运行。

**Windows / PowerShell：**

```powershell
$skillsDir = Join-Path $HOME ".codex/skills"
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
Copy-Item -LiteralPath ".\video-recipe-extractor" -Destination $skillsDir -Recurse
```

**macOS / Linux：**

```bash
mkdir -p ~/.codex/skills
cp -R video-recipe-extractor ~/.codex/skills/
```

安装后，确认目录中存在 `~/.codex/skills/video-recipe-extractor/SKILL.md`。配置了自定义 `CODEX_HOME` 时，复制到该目录下的 `skills` 文件夹。使用其他支持 Agent Skills 格式的工具时，安装位置以对应工具的文档为准。

### 2. 准备依赖并自检

进入项目文件夹，安装 Python 依赖，然后检查环境：

```bash
python -m pip install -r requirements.txt
python scripts/prepare_video.py check
```

需要 **Python 3.9+、Pillow、FFmpeg、FFprobe 和中文字体**。FFmpeg 与 FFprobe 需能在终端直接调用；字体默认尝试系统常用中文字体，也可以在渲染时通过 `--font` 指定。

处理在线视频链接时，另装 `yt-dlp`：

```bash
python -m pip install yt-dlp
```

macOS / Linux 如果没有 `python` 命令，可以把文中的 `python` 换成 `python3`。自检只报告可用组件，不自动安装软件。

### 3. 新开一个会话，说一句话

```text
使用 $video-recipe-extractor，把这个做菜视频整理成一张菜谱长图：
顶部一张原视频成品图，下方逐条写步骤，食材用量按视频保留。
```

随后给出视频链接或本地文件路径。Agent 会准备素材、核对食材与做法、选择主图，再生成长图和文字菜谱。

## 用一句话调用

| 场景 | 对 Agent 说 |
| --- | --- |
| 给一个视频链接 | 使用 $video-recipe-extractor，把这个做菜视频整理成一张主图加逐条步骤的菜谱长图。 |
| 用本地视频 | 使用 $video-recipe-extractor，读取这个本地视频，整理食材、火候和做法，生成字幕风格菜谱长图。 |
| 只要文字菜谱 | 使用 $video-recipe-extractor，先从这个视频提取食材清单和做法，暂时只交付文字版。 |
| 有视频和字幕 | 使用 $video-recipe-extractor，结合这段视频和带时间轴的字幕，核对用量后制作菜谱长图。 |
| 调整现有排版 | 使用 $video-recipe-extractor，用这份 recipe.json 和视频帧重新排版，保留一张主图，下方逐条写步骤。 |

一个视频包含多道菜时，按菜拆分整理，一张图对应一道菜。只有字幕、没有真实视频画面时，先交付文字菜谱。

## 工作流程

```mermaid
flowchart LR
  A[本地视频或公开链接] --> B[准备视频、字幕与音频]
  B --> C[检查真实帧与时间轴]
  C --> D[核对食材、用量和做法]
  D --> E[选一张主图并编排步骤]
  E --> F[生成长图与文字菜谱]
  F --> G[检查原图和手机缩略图]
```

`prepare_video.py` 负责下载、取帧和整理时间轴；Agent 负责理解视频、核对内容并写出 `recipe.json`；`render_recipe.py` 根据这份菜谱排版出图。脚本之间的内容理解需要 Agent 参与。

## 命令行

以下命令在项目文件夹中执行，视频、字幕和输出路径按实际素材替换。也可以用绝对路径运行脚本。

### 获取在线视频

```bash
python scripts/prepare_video.py fetch "视频链接" --out-dir work/source
```

视频和字幕分别获取，来源信息写入 `metadata.json`。后续使用该文件 `video_path` 指向的视频；字幕是否可用由 `subtitle_paths` 和 `subtitle_status` 记录。

### 准备本地素材

```bash
python scripts/prepare_video.py prepare "video.mp4" --subtitles "video.srt" --out-dir work/evidence
```

支持 SRT / VTT 字幕。没有独立字幕文件时，省略 `--subtitles`，检查视频里的烧录字幕或结合语音转写继续整理。

默认每隔10秒取帧，最多24张；视频较长时会在这组时间点中均匀抽取。短暂出现的用量或转场可在新目录补帧：

```bash
python scripts/prepare_video.py prepare "video.mp4" --out-dir work/focused --at 90.5 --at 93 --at 128
```

准备阶段生成真实帧、候选帧总览、`evidence.json` 和 `transcript.md`；视频有音轨时还会导出 `audio.wav`。这些是核对素材，最终长图只使用选定的一张主图。

### 写菜谱并渲染

由 Agent 阅读素材，按 [菜谱与证据格式](references/recipe-format.md) 写出 `work/recipe.json`，再执行：

```bash
python scripts/render_recipe.py work/recipe.json --evidence work/evidence/evidence.json --out work/菜谱长图.jpg
```

常用排版参数：

| 参数 | 用途 | 默认值 |
| --- | --- | --- |
| `--width` | 图片宽度，主图等比缩放 | `1440` |
| `--font` | 指定中文字体文件 | 自动查找系统字体 |
| `--font-size` | 调整文字字号 | 随图片宽度缩放 |
| `--hero-bottom` | 主图保留到原高度的哪个位置 | `1.0`，保留全帧 |
| `--band-center` | 下方条带从主图哪个高度取背景 | `0.85` |

示例图使用 `--band-center 0.45`。裁切主图前应先检查画面，保留菜品主体和作者水印。完整参数可用 `--help` 查看。

素材输出目录需为空，渲染器也不会覆盖已有图片或同名附带文件。再次调整时使用新目录或新文件名。

<details>
<summary><strong>可选：没有字幕时进行语音转写</strong></summary>

安装可选组件：

```bash
python -m pip install faster-whisper
```

明确启用转写：

```bash
python scripts/prepare_video.py prepare "video.mp4" --out-dir work/asr --transcribe --model base
```

模型未缓存时会下载；`--model` 也可以指定本地模型目录。转写结果用于定位内容，食材用量和关键操作仍需结合真实画面核对。

</details>

## 输出文件

| 文件 | 用途 |
| --- | --- |
| 菜谱长图 `.jpg` / `.png` | 一张视频主图，下方逐条文字步骤 |
| 同名 `.md` | 食材清单、做法及证据时间点 |
| `recipe.json` | Agent 编写的菜名、主图引用、食材与步骤，可编辑后重新渲染 |
| 同名 `.layout.json` | 图片尺寸、字号、条带位置和换行记录 |
| `evidence.json` 与真实帧 | 回看原视频，核对内容或重新选主图 |

默认把食材准备写进前一两步，长图中不额外加入食材大表格。单独的食材清单保存在文字版里。

## 常见问题

<details>
<summary><strong>视频没有独立字幕文件，还能做吗？</strong></summary>

可以先检查画面中是否有烧录字幕。番茄炒鸡蛋案例就是逐帧读取画面字幕完成的。只有语音讲解时，可使用可选转写；只有部分内容能确认时，先整理已有信息。

</details>

<details>
<summary><strong>食材为什么没有全部换成克数？</strong></summary>

菜谱沿用视频的表达。原视频给出克数就保留，使用“一勺”“适量”“少许”就照录，没有用量依据时只列食材名。若要额外补全用量，可以明确提出，补充建议会与视频事实分开标注。

</details>

<details>
<summary><strong>B站或其他平台的链接都能下载吗？</strong></summary>

本页展示了一条B站视频的实际处理结果。其他链接能否获取，取决于 `yt-dlp` 支持、平台访问状态和本机网络环境。下载失败时会说明失败环节，也可以换成本地视频继续。默认不读取浏览器 Cookies 或登录凭据。

</details>

## 项目目录

```text
video-recipe-extractor/
├── SKILL.md                      技能入口与工作流程
├── README.md                     中文使用说明
├── README_EN.md                  英文使用说明
├── requirements.txt              核心 Python 依赖
├── agents/openai.yaml            Codex 界面元数据
├── scripts/
│   ├── prepare_video.py          获取素材、字幕索引与取帧
│   └── render_recipe.py          菜谱校验与长图排版
├── references/recipe-format.md   菜谱与证据格式
├── examples/tomato-eggs/         番茄炒鸡蛋实测案例
└── tests/                        自动验证用例
```

## 开发验证

```bash
python -m unittest discover -s tests -v
```

现有34项自动测试覆盖字幕量词保留、滚动字幕去重、取帧时间、有声与无声视频、证据引用、长句换行、文件覆盖保护等行为。番茄炒鸡蛋案例还经过真实帧核对和原图、手机缩略图检查。


## 许可证与素材来源

原创代码和技能文档采用 [MIT 许可证](LICENSE)，© 2026 [cloudwallker](https://github.com/cloudwallker)。示例中的视频画面及作者水印归原作者所有，保留[原视频来源](https://www.bilibili.com/video/BV13p411d7oQ/)，不纳入本项目的 MIT 授权。第三方依赖及用户提供的素材仍遵循各自的权利与许可。

<div align="right"><a href="#readme-top">↑ 回到顶部</a></div>
