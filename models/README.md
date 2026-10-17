# models/ —— 音色模型目录

本目录**不包含**任何模型文件（体积约 230 MB 且涉及第三方声音素材版权），
`.gitignore` 已排除 `*.pth` / `*.ckpt` / `*.wav`。

## 需要的文件

| 文件 | 作用 | 参考体积 |
| --- | --- | --- |
| `manbo_e8_s168.pth` | SoVITS 声学模型 | ~81 MB |
| `manbo-e10.ckpt` | GPT 模型 | ~148 MB |
| `refer.wav` | 参考音频（3–10 秒干净人声） | < 1 MB |

三者放进本目录后重启软件，音色下拉框会自动出现「曼波」。

## 从哪来

- 曼波音色模型与参考音频：[Tsukimisaka/MamboTTS](https://github.com/Tsukimisaka/MamboTTS)（MIT）
  - 具体位置在它的 [Releases](https://github.com/Tsukimisaka/MamboTTS/releases)：下载 `MamboTTS-v1.2.x-full.zip`，
    解压后取 `models/` 目录下的这三个文件放进本目录
- 也可以用自己的数据训练：参见 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 的训练流程

## 自动获取

运行 `python tools/agent_install.py --dest <安装目录>` 会自动下载上述发布包，
只提取这三个文件放进本目录，不会把整个 223MB 的客户端包塞进来。
详见 [AGENT_INSTALL.md](../AGENT_INSTALL.md)。

## 只放 refer.wav 也能用

没有微调模型时，软件会退化为**零样本克隆**：用官方 v2Pro 预训练模型 + `refer.wav`
直接克隆音色，音色名显示为「曼波（零样本）」。想快速试听可以只放参考音频。

## 命名约定（换成别的音色照此办理）

```
<音色名>_e<epoch>_s<step>.pth    # SoVITS
<音色名>-e<epoch>.ckpt           # GPT
<音色名>.wav 或 refer.wav        # 参考音频
```

`core/config.py` 的 `discover_voices()` 按前缀匹配这三个文件，前缀一致即被识别为一个音色。

## 版权提醒

「曼波」音源出自《赛马娘 Pretty Derby》相关角色，声音权利归原权利方所有。
模型与生成音频仅限个人学习、技术研究与创作使用。
