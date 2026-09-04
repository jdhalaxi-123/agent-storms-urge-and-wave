"""语音识别：语音输入 → 文字。

两种后端，按配置自动选择：
- 腾讯云「一句话识别」（默认，联网、免费额度内省钱、中文效果好）。
  需要 .env 里配置 TENCENT_SECRET_ID / TENCENT_SECRET_KEY（一对都要有）。
- 本地 faster-whisper（离线兜底：没配腾讯 Key，或识别报错时回退）。
  首次使用会下载模型（base 约 145MB，缓存在 ~/.cache/huggingface）。
"""
from __future__ import annotations

import base64
import io
import json
import os
import uuid
import wave
from pathlib import Path


def _env(name: str) -> str:
    """从环境变量或项目根目录 .env 读取配置。"""
    val = os.environ.get(name)
    if val:
        return val.strip()
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    return ""


def transcribe(audio_path: str) -> str:
    """把音频文件转成文字，自动选择后端。"""
    sid = _env("TENCENT_SECRET_ID")
    skey = _env("TENCENT_SECRET_KEY")
    if sid and skey:
        return _tencent(audio_path, sid, skey)
    return _local_whisper(audio_path)


def _to_16k_mono_wav(audio_path: str) -> bytes:
    """把任意格式音频转成 16kHz 单声道 16bit WAV 字节（腾讯 16k_zh 要求）。"""
    import av
    from av import AudioResampler

    with av.open(audio_path) as inp:
        stream = inp.streams.audio[0]
        resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        for frame in inp.decode(stream):
            chunks.extend(resampler.resample(frame))
        chunks.extend(resampler.resample(None))
        raw = b"".join(c.to_ndarray().tobytes() for c in chunks)

    duration = len(raw) / 32000  # 16k mono 16bit → 32000 B/s
    if duration > 60:
        raise RuntimeError(
            f"音频 {duration:.0f} 秒超过腾讯一句话识别上限（60 秒），请录短一些"
        )

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(raw)
    return buf.getvalue()


def _tencent(audio_path: str, secret_id: str, secret_key: str) -> str:
    """腾讯云一句话识别 SentenceRecognition。"""
    from tencentcloud.asr.v20190614 import asr_client, models
    from tencentcloud.common import credential
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
        TencentCloudSDKException,
    )

    region = _env("TENCENT_ASR_REGION") or "ap-guangzhou"
    wav = _to_16k_mono_wav(audio_path)
    b64 = base64.b64encode(wav).decode("ascii")

    cred = credential.Credential(secret_id, secret_key)
    client = asr_client.AsrClient(cred, region)
    req = models.SentenceRecognitionRequest()
    req.from_json_string(
        json.dumps(
            {
                "ProjectId": 0,
                "SubServiceType": 2,
                "EngSerViceType": "16k_zh",
                "SourceType": 1,
                "VoiceFormat": "wav",
                "UsrAudioKey": "mic_" + uuid.uuid4().hex[:20],
                "Data": b64,
                "DataLen": len(wav),
            }
        )
    )
    try:
        resp = client.SentenceRecognition(req)
    except TencentCloudSDKException as err:
        hint = (
            "请检查：① SecretId/SecretKey 是否配对正确；"
            "② 腾讯云控制台是否已「开通」语音识别服务；"
            f"③ 服务是否开通在 region={region}。"
        )
        raise RuntimeError(f"腾讯云识别失败：{err} {hint}") from err
    return (resp.Result or "").strip()


_model = None
MODEL_NAME = "base"  # 可改为 "small" / "medium" 提升识别率


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def _local_whisper(audio_path: str) -> str:
    """本地 faster-whisper 离线识别。"""
    model = _get_model()
    segments, _info = model.transcribe(audio_path, language=None)
    return "".join(seg.text for seg in segments).strip()
