# Easy-Podcast 服务 API（基于 [SoulX-Podcast](https://github.com/Soul-AILab/SoulX-Podcast)）

ComfyUI 风格的任务式 API：`POST /prompt` 提交 → `GET /prompt/{task_id}` 轮询 → `/view` 取音频。
**生成完成后显存按策略自动释放**（默认空闲 120 秒卸载全部模型权重）。

## 启动服务

```bash
python run_server.py                          # 默认 0.0.0.0:8000
python run_server.py --port 8000 --vram_idle_seconds 0   # 每次生成完立即释放
python run_server.py --vram_idle_seconds -1   # 模型常驻不释放
```

| 参数 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `--host` / `--port` | `SOULX_API_HOST` / `SOULX_API_PORT` | 0.0.0.0 / 8000 | 监听地址 |
| `--model_path` | `SOULX_MODEL_PATH` | `pretrained_models/SoulX-Podcast-1.7B` | 基础模型 |
| `--model_path_dialect` | `SOULX_MODEL_PATH_DIALECT` | `pretrained_models/SoulX-Podcast-1.7B-dialect` | 方言模型 |
| `--vram_idle_seconds` | `SOULX_VRAM_IDLE_SECONDS` | 120 | 空闲 N 秒后自动卸载；0=生成完立即卸载；-1=常驻 |
| `--llm_engine` | `SOULX_LLM_ENGINE` | hf | hf / vllm（Windows 仅 hf） |
| `--fp16_flow` | `SOULX_FP16_FLOW` | 0 | flow 用 fp16（省显存） |

## 交互式文档

- Web UI: `http://localhost:8000/`
- Swagger: `http://localhost:8000/docs`

---

## 核心端点

### `POST /prompt` — 提交合成任务

请求体（JSON）：

```jsonc
{
  "mode": "podcast",              // podcast | tts（tts = 单说话人朗读，text 无需 [S1] 标记）
  "text": "[S1]你好！<|laughter|>[S2]大家好，今天聊聊AI。",
  "speakers": [                   // 顺序即 S1、S2…（最多 4 个）；也支持 {"S1": {...}} 字典
    {
      "audio_path": "example/audios/female_mandarin.wav",  // 服务器本地路径（相对服务根目录或绝对路径）
      "audio_b64": null,            // 或 base64 音频（二选一，跨机器调用用这个）
      "prompt_text": "参考音频的逐字转录文本（必填）",
      "dialect_prompt": ""          // 可选：<|Sichuan|>… / <|Yue|>… / <|Henan|>… 开头，触发方言克隆
    }
  ],
  "seed": 1988,                   // 可选
  "temperature": 0.6, "top_k": 100, "top_p": 0.9, "repetition_penalty": 1.25,  // 可选
  "unload": "auto",               // auto=按空闲策略 | immediate=生成完立即释放 | keep=常驻
  "model": "auto"                 // auto=按需自动选择/切换 | base | dialect（方言提示必须 dialect）
}
```

响应：

```json
{"task_id": "a1b2c3d4e5f6", "status_url": "/prompt/a1b2c3d4e5f6", "audio_url": "/view?filename=a1b2c3d4e5f6.wav"}
```

副语言标签（写在 text 里）：`<|laughter|>` `<|sigh|>` `<|breathing|>` `<|coughing|>` `<|throat_clearing|>`

### `GET /prompt/{task_id}` — 任务状态

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "queued | running | done | error",
  "output_filename": "a1b2c3d4e5f6.wav",
  "audio_duration_sec": 47.3,
  "model_used": "SoulX-Podcast-1.7B-dialect",
  "elapsed_sec": 32.1,
  "error": null,
  "audio_url": "/view?filename=a1b2c3d4e5f6.wav"
}
```

### `GET /view?filename=a1b2c3d4e5f6.wav` — 下载/播放生成的 WAV（24kHz）

### `POST /upload` — 上传参考音频（multipart，字段名 `file`）→ `{"filename": "...", "audio_path": "..."}`

### 显存控制

| 端点 | 说明 |
|---|---|
| `GET /vram` | 模型状态 + 显存占用（allocated/reserved/free/total）+ 空闲倒计时 |
| `POST /vram/load` | 立即加载 `{"model": "base"}` 或 `{"model": "dialect"}` |
| `POST /vram/unload` | 立即卸载，释放全部显存 |

### 其他

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `GET /history` | 最近任务 |
| `GET /examples` | 官方播客脚本示例（普通话/英语/川/粤/豫） |
| `GET /dialect_prompts` | 三地方言提示文本示例 |
| `GET /sample_audios` | 内置参考音频（female_mandarin.wav / male_mandarin.wav） |
| `GET /paralanguage` | 支持的副语言标签列表 |

---

## Agent 调用方式

### 方式一：自带客户端脚本（零依赖，推荐）

```bash
# 播客对话（等待完成并下载）
python agent_client.py generate \
  --speakers-json "[{\"audio_path\":\"example/audios/female_mandarin.wav\",\"prompt_text\":\"...\"},{\"audio_path\":\"example/audios/male_mandarin.wav\",\"prompt_text\":\"...\"}]" \
  --text "[S1]哈喽，欢迎收听！<|laughter|>[S2]大家好呀！" \
  --wait --output out.wav

# 单人 TTS
python agent_client.py tts --audio example/audios/female_mandarin.wav \
  --prompt-text "参考音频的转录文本" --text "要合成的文本" --wait --output out.wav

# 显存管理
python agent_client.py vram          # 查看状态
python agent_client.py unload        # 立即释放显存
python agent_client.py load --model dialect

# 异步：提交后拿 task_id，稍后查询
python agent_client.py generate --payload-file request.json
python agent_client.py status --task-id <id>
```

远程服务：设置环境变量 `SOULX_API_BASE=http://192.168.x.x:8000`。
音频在另一台机器时，`audio_path` 指向本地文件，客户端自动转成 `audio_b64` 上传。

### 方式二：curl

```bash
# 提交
curl -X POST http://127.0.0.1:8000/prompt -H "Content-Type: application/json" -d '{
  "mode":"tts",
  "text":"你好，世界。",
  "speakers":[{"audio_path":"example/audios/female_mandarin.wav","prompt_text":"参考文本"}],
  "unload":"immediate"}'
# → {"task_id":"..."}

# 轮询
curl http://127.0.0.1:8000/prompt/<task_id>

# 取音频
curl -o out.wav "http://127.0.0.1:8000/view?filename=<task_id>.wav"

# 释放显存
curl -X POST http://127.0.0.1:8000/vram/unload
```

### 方式三：Python

```python
import requests, base64, time

BASE = "http://127.0.0.1:8000"
audio_b64 = base64.b64encode(open("ref.wav", "rb").read()).decode()

r = requests.post(f"{BASE}/prompt", json={
    "mode": "tts",
    "text": "你好，这是一段测试。",
    "speakers": [{"audio_b64": audio_b64, "prompt_text": "参考文本"}],
    "unload": "auto",
}).json()

while True:
    st = requests.get(f"{BASE}/prompt/{r['task_id']}").json()
    if st["status"] in ("done", "error"):
        break
    time.sleep(2)

wav = requests.get(f"{BASE}/view?filename={st['output_filename']}").content
open("out.wav", "wb").write(wav)
```

## 显存释放机制

1. **默认策略（auto）**：生成结束 N 秒无新任务（N=`--vram_idle_seconds`，默认 120）→ 自动卸载 LLM/Flow/HiFi-GAN/音频分词器并 `empty_cache`，显存归零。
2. **`unload: "immediate"`**：该次任务一结束立刻卸载。
3. **`unload: "keep"`**：本次任务不触发卸载计时（下个 auto 任务恢复计时）。
4. **手动**：任意时刻 `POST /vram/unload`。
5. 方言提示请求自动切换到 dialect 模型（若当前是 base 会先卸载再加载）；普通话请求优先复用已加载模型，避免来回切换。

## 常见问题

- **模型未下载**：先运行 `python download_models.py`（自动走 hf-mirror.com）。
- **409/串行**：同一时间只跑一个生成任务，多请求自动排队。
- **方言请求报错**：确认已下载 dialect 模型并重启服务。
