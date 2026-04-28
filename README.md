# gemma4-vastai-ocr

通过 [vast.ai](https://vast.ai) 临时租 GPU，运行 **Gemma 4** (Google 2026/04 发布的多模态开源模型) 当 OCR 后端。本仓库的 `install.sh` + `serve.sh` 会被远端实例 `git clone` 后自动执行 —— 你本地不用 SSH 也不用 scp。

```
本地浏览器 ──▶ 本地 Flask :5000 ──▶ vast.ai 实例上的 vLLM :8000 ──▶ Gemma 4
```

## 仓库布局
```
.
├── install.sh              # 远端：装 vLLM + 预下载权重 (~60GB)
├── serve.sh                # 远端：启动 vLLM OpenAI 兼容服务
├── client/
│   ├── app.py              # 本地：Flask + 拖拽上传 UI
│   └── templates/index.html
├── scripts/
│   ├── create_instance.py  # 本地：调 vast.ai API 找 GPU 并把上面的 onstart 注入
│   ├── status.sh           # 本地：tail onstart 日志 + 探测服务
│   └── destroy_instance.py # 本地：销毁实例
├── .env.example
└── Makefile
```

## 工作流

```bash
# 1) 配置
cp .env.example .env       # 填 VAST_API_KEY、REPO_URL（你 fork 后的 https URL）
pip install -r scripts/requirements.txt -r client/requirements.txt

# 2) 租机器（这一步会把 git-clone+install+serve 注入到 vast.ai onstart）
make dry-run               # 先看价
make up                    # 真的租，输出 .instance.json

# 3) 等远端跑完装机（5–20 分钟，看下载速度）
make status                # 反复跑直到 /v1/models 有响应

# 4) 跑客户端
make client                # 浏览器 → http://127.0.0.1:5000

# 5) 用完务必销毁，否则按秒计费
make down
```

## 关键设计

- **远端只跑 `git clone + bash install.sh + bash serve.sh`** — 全部安装/启动逻辑在仓库里，方便你改完 push 后下次实例直接拿到新版本。
- **install.sh 幂等**：重复跑安全；预下载权重避免首次推理超时。
- **serve.sh 自动检测 GPU 数**：`tensor-parallel-size` = `nvidia-smi` 出来的卡数。31B fp16 需 ≥80GB 总 VRAM (1×H100 / 2×A100-40 / 4×4090)。
- **Gemma 4 = Apache 2.0**：HF token 不强制，但配上能避免大文件下载被限速。

## 模型选择（改 `.env` 里的 `MODEL_ID`）

| 模型 | VRAM | vast.ai 大约价 | OCR 适用性 |
| --- | --- | --- | --- |
| `google/gemma-4-e4b-it` | 16GB | $0.15/h | 票据 / 截图够用 |
| `google/gemma-4-26b-a4b` | 40GB | $0.6/h | 文档 / 表格识别佳 |
| `google/gemma-4-31b-it` (默认) | 80GB+ | $2-3/h | 最高精度，复杂版面/手写 |

## 排错

| 现象 | 原因 / 修法 |
| --- | --- |
| `make status` 一直没 `/v1/models` 响应 | 模型还在下载，看 onstart.log；首次拉权重正常 5-15 分钟 |
| `out of memory` | 改更小模型，或在 serve.sh 调 `--gpu-memory-utilization 0.85` |
| `connection refused` | 实例端口未映射 —— 检查 `.instance.json` 里的 `serve_port` |
| 客户端 502 | `make status` 看 vllm.log；通常是模型还没起完 |

## 成本

vast.ai 按秒计费。31B 默认配置每小时 ~$2-3，**用完一定 `make down`**。
