#!/usr/bin/env python3
"""
vLLM-Omni Qwen3-TTS 音频生成脚本（支持断点续作）

特性：
- 检测已存在的音频文件，自动跳过
- 实时显示生成进度
- 生成失败时保留已完成的部分
- 自动更新 Remotion 配置文件
- 支持本地部署的 vLLM-Omni 服务器

用法：
    python generate_audio_qwen.py

环境变量：
    VLLM_BASE_URL: vLLM-Ommi 服务器地址（默认: http://localhost:8000/v1）
    VLLM_MODEL_NAME: 模型名称（默认: Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice）
    VLLM_VOICE: 预设语音名称（默认: Vivian）

依赖：
    pip install openai>=1.0.0
"""

import os
import subprocess
from pathlib import Path
from openai import OpenAI

# 从环境变量读取配置
VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL_NAME = os.environ.get(
    "VLLM_MODEL_NAME", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
)
VLLM_VOICE = os.environ.get("VLLM_VOICE", "Vivian")

# 初始化 OpenAI 客户端
client = OpenAI(api_key="EMPTY", base_url=VLLM_BASE_URL)

# 场景配置 - 每个场景包含 id、title、text
SCENES = [
    {"id": "01-intro", "title": "开场", "text": "欢迎观看本期视频..."},
    {"id": "02-concept", "title": "核心概念", "text": "今天我们来讲..."},
    {"id": "03-demo", "title": "演示", "text": "让我们看一个例子..."},
    {"id": "04-summary", "title": "总结", "text": "感谢观看，下期见！"},
]

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "audio"
CONFIG_FILE = Path(__file__).parent.parent / "src" / "audioConfig.ts"


def get_audio_duration(file_path: Path) -> float:
    """用 ffprobe 获取音频时长"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip()) if result.stdout.strip() else 0


def generate_audio(scene: dict) -> dict:
    """使用 vLLM-Ommi API 生成音频"""
    output_file = OUTPUT_DIR / f"{scene['id']}.mp3"

    try:
        # 调用 OpenAI 兼容 API
        response = client.audio.speech.create(
            model=VLLM_MODEL_NAME,
            voice=VLLM_VOICE,
            input=scene["text"],
            response_format="mp3",
        )

        # 保存音频文件
        with open(output_file, "wb") as f:
            f.write(response.content)

        # 获取音频时长
        duration = get_audio_duration(output_file)

        return {
            "id": scene["id"],
            "title": scene["title"],
            "file": f"{scene['id']}.mp3",
            "duration": duration,
            "frames": round(duration * 30),
        }

    except Exception as e:
        # 如果 OpenAI 客户端不支持音频输出，尝试 REST API
        print(f"注意: OpenAI 客户端调用失败，尝试 REST API: {e}")
        return generate_audio_rest_api(scene)


def generate_audio_rest_api(scene: dict) -> dict:
    """使用 REST API 生成音频（备用方案）"""
    import requests

    url = f"{VLLM_BASE_URL.rstrip('/v1')}/v1/audio/speech"

    headers = {
        "Authorization": "Bearer EMPTY",
        "Content-Type": "application/json",
    }

    payload = {
        "model": VLLM_MODEL_NAME,
        "voice": VLLM_VOICE,
        "input": scene["text"],
        "response_format": "mp3",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)

    if response.status_code == 200:
        output_file = OUTPUT_DIR / f"{scene['id']}.mp3"

        # vLLM-Omni 可能返回 WAV 格式，需要检查
        content_type = response.headers.get("content-type", "")

        if "audio/wav" in content_type or output_file.suffix == ".wav":
            # 保存 WAV 文件
            wav_file = OUTPUT_DIR / f"{scene['id']}.wav"
            wav_file.write_bytes(response.content)

            # 转换为 MP3
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(wav_file),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(output_file),
                ],
                capture_output=True,
            )

            # 删除临时 WAV 文件
            wav_file.unlink()
        else:
            # 直接保存音频
            output_file.write_bytes(response.content)

        duration = get_audio_duration(output_file)

        return {
            "id": scene["id"],
            "title": scene["title"],
            "file": f"{scene['id']}.mp3",
            "duration": duration,
            "frames": round(duration * 30),
        }
    else:
        raise Exception(f"REST API 错误: {response.status_code} - {response.text}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"🎙️  vLLM-Omni Qwen3-TTS (Model: {VLLM_MODEL_NAME})")
    print(f"📡 服务器: {VLLM_BASE_URL}")
    print(f"🎭 语音: {VLLM_VOICE}")
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    results = []
    skipped = 0
    generated = 0

    for i, scene in enumerate(SCENES, 1):
        output_file = OUTPUT_DIR / f"{scene['id']}.mp3"
        prefix = f"[{i}/{len(SCENES)}] {scene['id']}"

        # 断点续作：检查文件是否已存在
        if output_file.exists() and output_file.stat().st_size > 0:
            duration = get_audio_duration(output_file)
            frames = round(duration * 30)
            results.append(
                {
                    "id": scene["id"],
                    "title": scene["title"],
                    "file": f"{scene['id']}.mp3",
                    "duration": duration,
                    "frames": frames,
                }
            )
            print(f"{prefix}: ⏭️  已存在，跳过 ({duration:.2f}s)")
            skipped += 1
            continue

        # 生成新音频
        print(f"{prefix}: 生成中...", end=" ", flush=True)
        try:
            result = generate_audio(scene)
            results.append(result)
            print(f"✅ {result['duration']:.2f}s ({result['frames']} frames)")
            generated += 1
        except Exception as e:
            print(f"❌ {e}")
            print("\n⚠️  生成中断，已完成的音频已保存，可重新运行继续")
            return

    print("=" * 60)
    print(f"✅ 完成: {generated} 新生成, {skipped} 跳过")

    # 更新 audioConfig.ts
    update_config(results)
    print(f"📝 audioConfig.ts 已更新")


def update_config(results):
    """更新 audioConfig.ts - 注意：必须用真正的换行符，不能用字符串 \\n"""
    scenes_lines = []
    for r in results:
        # 使用多行字符串确保正确的换行
        scene_block = f"""  {{
    id: "{r['id']}",
    title: "{r['title']}",
    durationInFrames: {r['frames']},
    audioFile: "{r['file']}",
  }}"""
        scenes_lines.append(scene_block)

    # 用真正的换行符连接，不要用 ",\\n".join()
    scenes_content = ",\n".join(scenes_lines)

    content = f"""// 场景配置（vLLM-Omni Qwen3-TTS 生成）
// 自动生成，请勿手动修改

export interface SceneConfig {{
  id: string;
  title: string;
  durationInFrames: number;
  audioFile: string;
}}

export const SCENES: SceneConfig[] = [
{scenes_content},
];

// 计算场景起始帧
export function getSceneStart(sceneIndex: number): number {{
  return SCENES.slice(0, sceneIndex).reduce((sum, s) => sum + s.durationInFrames, 0);
}}

// 总帧数（加上片头片尾缓冲）
export const TOTAL_FRAMES = SCENES.reduce((sum, s) => sum + s.durationInFrames, 0) + 60;

// 帧率
export const FPS = 30;
"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(content)


if __name__ == "__main__":
    main()
