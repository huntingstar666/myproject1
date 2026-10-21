<div align="center">
    <h1>
    🎙️ Easy-Podcast
    </h1>
    <p>
    <b>开箱即用的播客级语音合成服务</b><br>
    一行命令启动 Web 服务 · 多说话人播客生成 · 方言克隆 · 副语言控制<br>
    <sub>基于 <a href="https://github.com/Soul-AILab/SoulX-Podcast">SoulX-Podcast</a> 构建的二次开发项目</sub>
    </p>
    <p>
    <a href="https://github.com/huntingstar666/easy-podcast"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
    <a href="https://github.com/Soul-AILab/SoulX-Podcast"><img src="https://img.shields.io/badge/Powered%20by-SoulX--Podcast-7c5cff" alt="Powered by"></a>
    <img src="https://img.shields.io/badge/Python-3.11+-green" alt="Python">
    <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey" alt="Platform">
    </p>
</div>

**English** | [简体中文](#-easy-podcast-1)

Easy-Podcast is an out-of-the-box podcast-grade speech synthesis service built on top of [SoulX-Podcast](https://github.com/Soul-AILab/SoulX-Podcast). It wraps the powerful SoulX-Podcast engine with a task-style HTTP API, a built-in web workbench, a Gradio WebUI and CLI tools, so you can deploy podcast generation in minutes.

---

## ✨ 项目简介

Easy-Podcast 让 [SoulX-Podcast](https://github.com/Soul-AILab/SoulX-Podcast) 的播客语音生成能力更容易用：

- **Web 工作台**：浏览器里管理说话人、编辑多轮对话脚本、试听与下载，无需写代码
- **任务式 HTTP API**：`POST /prompt` 提交 → `GET /prompt/{task_id}` 轮询 → `/view` 取音频，ComfyUI 风格，方便脚本与 Agent 调用
- **显存自动管理**：空闲 N 秒后自动卸载模型权重（策略可配），单卡也能稳跑
- **零依赖客户端**：`agent_client.py` 仅用 Python 标准库，任何环境都能直接调服务
- **一键下载模型**：`download_models.py` 自动从 Hugging Face（含镜像加速）拉取基础/方言模型

底层模型能力（来自 SoulX-Podcast）：

- 长篇、多轮、多说话人对话式语音生成，同时支持单说话人朗读（TTS）
- 跨方言零样本音色克隆：普通话、四川话、河南话、粤语、英语
- 副语言控制：`<|laughter|>`、`<|sigh|>`、`<|breathing|>`、`<|coughing|>`、`<|throat_clearing|>`

## 🚀 快速开始

### 1. 安装环境

```bash
git clone https://github.com/huntingstar666/easy-podcast.git
cd easy-podcast

conda create -n easy-podcast -y python=3.11
conda activate easy-podcast
pip install -r requirements.txt
# 中国大陆可使用镜像加速：
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com
```

### 2. 下载模型

```bash
python download_models.py          # 自动下载基础模型与方言模型
```

或手动下载（需要 [huggingface_hub](https://huggingface.co/docs/huggingface_hub)）：

```bash
huggingface-cli download --resume-download Soul-AILab/SoulX-Podcast-1.7B --local-dir pretrained_models/SoulX-Podcast-1.7B
huggingface-cli download --resume-download Soul-AILab/SoulX-Podcast-1.7B-dialect --local-dir pretrained_models/SoulX-Podcast-1.7B-dialect
```

### 3. 启动服务（推荐）

```bash
python run_server.py                        # Web 工作台 + API，默认 http://localhost:8000
python run_server.py --vram_idle_seconds 0  # 每次生成完立即释放显存
python run_server.py --vram_idle_seconds -1 # 模型常驻不释放
```

启动后：

- **Web 工作台**：`http://localhost:8000/`
- **Swagger 文档**：`http://localhost:8000/docs`
- **API 详细说明**：见 [docs/API.md](docs/API.md)

### 4. 其他使用方式

```bash
# Gradio WebUI
python webui.py --model_path pretrained_models/SoulX-Podcast-1.7B

# 命令行播客推理
bash example/infer_dialogue.sh

# 命令行单句 TTS
python cli/tts.py --help

# 让 Agent / 脚本调用服务（仅标准库）
python agent_client.py generate --text "[S1]你好[S2]大家好" --wait --help
```

完整 API 参数（说话人配置、方言克隆、采样参数、显存策略等）请看 [docs/API.md](docs/API.md)。

## 🙏 致谢

本项目站在巨人的肩膀上，衷心感谢：

- **[Soul-AILab/SoulX-Podcast](https://github.com/Soul-AILab/SoulX-Podcast)** —— 本项目的核心引擎与模型完全来自 SoulX-Podcast，是其官方推理代码的二次开发发行版。没有原项目的杰出工作（论文：[SoulX-Podcast: Towards Realistic Long-form Podcasts with Dialectal and Paralinguistic Diversity](https://arxiv.org/abs/2510.23541)），就没有 Easy-Podcast。所有模型能力的荣誉属于原作者团队，使用中遇到模型本身的问题请优先到[原项目](https://github.com/Soul-AILab/SoulX-Podcast/issues)反馈。
- **[FlashCosyVoice](https://github.com/xingchensong/FlashCosyVoice)** —— SoulX-Podcast 上游受益的项目，同样致敬。

## 📄 开源协议

本项目基于 [Apache License 2.0](LICENSE) 开源。

- Easy-Podcast 是 SoulX-Podcast（Apache 2.0）的衍生项目，依据 Apache 2.0 协议第 4 条，本项目完整保留了原始许可证与版权声明；
- 相对上游的主要改动：新增 Web 服务与工作台（`server/`、`run_server.py`）、任务式 API 与显存管理、Agent 客户端（`agent_client.py`）、模型下载脚本（`download_models.py`）及文档；
- 模型权重与核心推理引擎版权归 **Soul-AILab** 所有，Easy-Podcast 自身新增代码同样以 Apache 2.0 发布。

## 📚 引用

如果你使用了本项目，请务必引用原始工作：

```bibtex
@misc{SoulXPodcast,
  title        = {SoulX-Podcast: Towards Realistic Long-form Podcasts with Dialectal and Paralinguistic Diversity},
  author       = {Hanke Xie and Haopeng Lin and Wenxiao Cao and Dake Guo and Wenjie Tian and Jun Wu and Hanlin Wen and Ruixuan Shang and Hongmei Liu and Zhiqi Jiang and Yuepeng Jiang and Wenxi Chen and Ruiqi Yan and Jiale Qian and Yichao Yan and Shunshun Yin and Ming Tao and Xie Chen and Lei Xie and Xinsheng Wang},
  year         = {2025},
  archivePrefix={arXiv},
  url          = {https://arxiv.org/abs/2510.23541}
}
```

## ⚠️ 使用声明

本项目提供具备零样本音色克隆能力的语音合成模型，旨在用于学术研究、教育目的及合法应用（如个性化语音合成、辅助技术、语言学研究）。

请注意：

- 禁止将本模型用于未经授权的音色克隆、冒充他人、欺诈、诈骗、深度伪造或任何违法活动；
- 使用本模型时请遵守当地法律法规，恪守道德标准；
- 开发者不对本模型的任何滥用承担责任；
- 我们倡导负责任的 AI 开发与使用，鼓励社区在 AI 研究和应用中坚持安全与伦理原则。

## 🔗 相关链接

- 原项目主页：https://github.com/Soul-AILab/SoulX-Podcast
- 在线 Demo：https://huggingface.co/Soul-AILab/spaces
- 技术报告：https://arxiv.org/abs/2510.23541
