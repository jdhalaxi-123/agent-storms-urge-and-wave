"""网页对话入口（Gradio 自定义 Blocks：文字 + 微信式麦克风）。

语音经 asr.transcribe() 转文字后，与文字一起走 llm.chat()（DeepSeek）。
预报类问题由 LLM 调用工具跑编排引擎，返回文字简报 + 预报图（显示在下方图板）。
"""
from __future__ import annotations

import gradio as gr

from orchestrator import asr, llm


def _to_messages(history):
    """把 [[用户, 助手], ...] 变成 gradio type='messages' 所需格式。"""
    msgs = []
    for user, bot in history:
        msgs.append({"role": "user", "content": user or ""})
        msgs.append({"role": "assistant", "content": bot or ""})
    return msgs


def _respond(text, audio_path, history):
    """处理一轮输入：文字/语音 -> llm.chat -> 更新对话与预报图。"""
    text = (text or "").strip()
    if audio_path:
        spoken = asr.transcribe(audio_path)
        text = (text + " " + spoken).strip() if text else spoken
    if not text:
        return _to_messages(history), None, "", None, history

    bot_text, images = llm.chat(text, [[u, b] for u, b in history])
    new_history = history + [[text, bot_text]]
    return _to_messages(new_history), (images or None), "", None, new_history


with gr.Blocks(title="风暴潮与海浪智能预报助手") as demo:
    gr.Markdown("## 风暴潮与海浪智能预报助手\n可以打字，也可以点输入框右侧的麦克风图标录音。")

    chatbot = gr.Chatbot(type="messages", label="对话", height=420)
    gallery = gr.Gallery(label="预报图", columns=1, height=240)
    history = gr.State([])

    with gr.Row():
        txt = gr.Textbox(
            placeholder="输入文字，或点麦克风录音…",
            show_label=False,
            container=False,
            scale=8,
        )
        mic = gr.Audio(
            sources=["microphone"],
            type="filepath",
            show_label=False,
            container=False,
            scale=1,
        )
        send = gr.Button("发送", variant="primary", scale=1)

    inputs = [txt, mic, history]
    outputs = [chatbot, gallery, txt, mic, history]
    txt.submit(_respond, inputs, outputs)
    send.click(_respond, inputs, outputs)
    mic.stop_recording(_respond, inputs, outputs)


if __name__ == "__main__":
    demo.launch()
