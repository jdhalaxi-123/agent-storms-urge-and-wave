"""网页对话入口（Gradio Blocks：文字 + 微信式麦克风，豆包式单界面）。

语音经 asr.transcribe() 转文字后，与文字一起走 llm.chat()（DeepSeek）。
预报类问题由 LLM 调用工具跑编排引擎，返回文字简报 + 预报图。
预报图直接内嵌在对话流中（与文字混排，不分块）；聊天里的图片可点击
放大（点击图片打开 Gradio 缓存的原图 URL，即"点小图弹大图"）。
"""
from __future__ import annotations

import os

import gradio as gr

from orchestrator import asr, llm

THINKING = "🔍 正在思考中，请稍候…"


def _file_msg(img_path: str) -> dict:
    """图片消息：gr.Image 组件嵌入（ComponentMessage），聊天流内显示；
    点击由注入的 LIGHTBOX JS 拦截 -> 全屏大图模态框。"""
    return {
        "role": "assistant",
        "content": gr.Image(
            value=os.path.abspath(str(img_path)),
            show_label=False,
            container=False,
            interactive=False,
            render=False,
            type="filepath",
            show_fullscreen_button=False,  # 我们自己用 JS 做点击放大
            show_download_button=True,
            format="png",
        ),
    }


def _to_messages(history):
    """把 [[用户, (助手文本, 图片)], ...] 变成 gradio type='messages' 所需格式。

    图片以 gr.Image 组件嵌入聊天流（与文字混排，豆包式），
    点击图片由 LIGHTBOX JS 弹出大图。
    """
    msgs = []
    for user, bot in history:
        msgs.append({"role": "user", "content": user or ""})
        if isinstance(bot, tuple):
            text = bot[0] or ""
            msgs.append({"role": "assistant", "content": text})
            for img in bot[1] or []:
                msgs.append(_file_msg(img))
        else:
            msgs.append({"role": "assistant", "content": bot or ""})
    return msgs


def _respond(text, audio_path, history):
    """处理一轮输入：文字/语音 -> 先回显「思考中」 -> llm.chat -> 完整回答。"""
    text = (text or "").strip()
    if audio_path:
        spoken = asr.transcribe(audio_path)
        text = (text + " " + spoken).strip() if text else spoken
    if not text:
        return _to_messages(history), "", None, history

    # ① 立即回显：用户消息 + 「思考中」占位（给即时反馈）
    interim_history = history + [[text, (THINKING, [])]]
    yield _to_messages(interim_history), "", None, interim_history

    # ② 真实处理（可能较慢：LLM 两次调用 + 编排引擎）
    try:
        bot_text, images = llm.chat(text, [[u, b] for u, b in history])
    except Exception as exc:
        bot_text, images = f"（处理出错：{exc}）", []

    # ③ 替换占位为完整回答
    new_history = history + [[text, (bot_text, images or [])]]
    yield _to_messages(new_history), "", None, new_history


# ===== 点击图片弹大图（模态框 JS，参考教程方案） =====
# 经 Blocks(head=...) 注入 <head>，浏览器必定执行。
# Gradio 5 的 Chatbot 渲染在 Shadow DOM 内，document 级事件捕获不到，
# 因此递归遍历所有 shadow roots 为 img 绑定点击 -> 全屏大图。
LIGHTBOX_HEAD = """
<script>
(function(){
  var box = null;
  var im = null;
  function buildBox(){
    if (box && document.body.contains(box)) return box;
    if (!document.body) return null;  // body 未就绪
    box = document.createElement('div');
    box.id = 'storm-lightbox';
    box.style.cssText = 'display:none;position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,0.93);cursor:zoom-out;align-items:center;justify-content:center;';
    im = document.createElement('img');
    im.style.cssText = 'max-width:96vw;max-height:96vh;object-fit:contain;border-radius:6px;';
    box.appendChild(im);
    document.body.appendChild(box);
    box.addEventListener('click', function(){ box.style.display='none'; });
    return box;
  }
  function show(src){
    if (!buildBox()) return;  // body 未就绪则跳过
    im.src = src;
    box.style.display = 'flex';
  }
  function bindAll(root){
    if (!root) return;
    var imgs = root.querySelectorAll ? root.querySelectorAll('img') : [];
    for (var i=0;i<imgs.length;i++){
      (function(img){
        if (img.__lbBound) return;
        img.__lbBound = true;
        img.style.cursor = 'zoom-in';
        img.addEventListener('click', function(e){
          e.preventDefault();
          e.stopPropagation();
          show(img.getAttribute('src') || img.src);
        });
      })(imgs[i]);
    }
    var all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (var j=0;j<all.length;j++){
      if (all[j].shadowRoot) bindAll(all[j].shadowRoot);
    }
    if (root.shadowRoot) bindAll(root.shadowRoot);
  }
  function tick(){
    if (!document.body) return;
    bindAll(document);
    var app = document.querySelector('gradio-app');
    if (app) bindAll(app);
  }
  setInterval(tick, 800);
  document.addEventListener('DOMContentLoaded', tick);
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && box) box.style.display = 'none';
  });
})();
</script>
"""

with gr.Blocks(
    title="风暴潮与海浪智能预报助手",
    analytics_enabled=False,
    head=LIGHTBOX_HEAD,
    theme=gr.themes.Base(
        font=["Microsoft YaHei", "system-ui", "sans-serif"],
        text_size=gr.themes.sizes.text_lg,
    ),
    css="""
    /* ===== 全局容器：撑满浏览器 ===== */
    .gradio-container { max-width: none !important; width: 100vw !important; padding: 8px 12px !important; }
    .gradio-container > .main, .gradio-container > .main > .wrap { max-width: none !important; width: 100% !important; }
    /* ===== 全局字体放大 ===== */
    .gradio-container, .gradio-container * { font-family: "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif !important; }
    .gradio-container { font-size: 17px !important; }
    /* ===== 聊天区：占满高度和宽度 ===== */
    #chatbot { height: 80vh !important; min-height: 700px !important; width: 100% !important; }
    #chatbot .message { font-size: 17px !important; line-height: 1.7 !important; max-width: 96% !important; }
    #chatbot .bot, #chatbot .message-row { max-width: 100% !important; }
    /* ===== 聊天中的图片：更大 + 可点击(悬停提示) ===== */
    #chatbot img {
        max-width: 92% !important;
        max-height: 520px !important;
        border-radius: 10px !important;
        border: 1px solid #e5e5e5;
        cursor: zoom-in !important;
        margin-top: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,.08);
        transition: transform .15s, box-shadow .15s;
    }
    #chatbot img:hover { transform: scale(1.01); box-shadow: 0 6px 18px rgba(0,0,0,.18); }
    /* ===== 输入框 ===== */
    textarea, input[type="text"], .wrap textarea, .g-textbox textarea,
    [class*="textbox"] textarea, #chat-input textarea {
        font-size: 18px !important; line-height: 1.6 !important;
    }
    .gradio-container h2 { font-size: 24px !important; }
    .gradio-container h1 { font-size: 28px !important; }
    """,
) as demo:
    gr.Markdown("## 🌊 风暴潮与海浪智能预报助手\n可以打字，也可以点输入框右侧的麦克风图标录音。")

    # 豆包式：单个聊天界面，文字与预报图混排（无独立图板）
    chatbot = gr.Chatbot(
        type="messages",
        label="对话",
        elem_id="chatbot",
        elem_classes=["chatbot-area"],
    )
    history = gr.State([])

    with gr.Row():
        txt = gr.Textbox(
            placeholder="输入问题，如：厦门站5天后海浪情况…",
            show_label=False,
            container=False,
            scale=8,
            lines=1,
            max_lines=4,
            elem_id="chat-input",
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
    outputs = [chatbot, txt, mic, history]
    txt.submit(_respond, inputs, outputs)
    send.click(_respond, inputs, outputs)
    mic.stop_recording(_respond, inputs, outputs)


if __name__ == "__main__":
    demo.launch()
