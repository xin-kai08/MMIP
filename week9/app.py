"""Run from project root: python -m streamlit run app.py --server.address 127.0.0.1"""
import io
import base64
import html
import zipfile
from pathlib import Path

import streamlit as st

from other_code import quiz3 as q3

st.set_page_config(page_title="3C 售後客服｜Quiz 3", page_icon="💬", layout="wide")
st.markdown("""
<style>
.conversation-row {display:flex; width:100%; margin:0 0 1.1rem;}
.conversation-row.user {justify-content:flex-end;}
.conversation-row.assistant {justify-content:flex-start;}
.conversation-bubble {max-width:85%; min-width:0; padding:1rem 1.2rem;
    border-radius:1rem; background:var(--secondary-background-color,#f1f3f6);
    color:var(--text-color,#20242c); overflow-wrap:anywhere;}
.user .conversation-bubble {background:#e8efff; color:#17294b; border-bottom-right-radius:.2rem;}
.assistant .conversation-bubble {border-bottom-left-radius:.2rem;}
.conversation-author {font-size:.8rem; opacity:.7; margin-bottom:.4rem;}
.conversation-text {white-space:pre-wrap; line-height:1.7;}
.conversation-image {display:block; max-width:100%; width:320px; height:auto;
    border-radius:.6rem; margin-bottom:.7rem;}
@media (max-width:640px) {.conversation-bubble {max-width:95%; padding:.8rem;}}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="正在載入實驗B模型，首次載入需要較久…")
def real_engine(adapter):
    model, processor = q3.load_model(adapter)
    return q3.QwenEngine(model, processor, q3.InferenceSettings(decoding="prompt"))


def render_message(message, session_dir):
    role = "user" if message["role"] == "user" else "assistant"
    author = "你" if role == "user" else "客服"
    picture = ""
    if message.get("image"):
        data = (Path(session_dir) / message["image"]).read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        picture = f'<img class="conversation-image" alt="使用者提供的商品或問題圖片" src="data:image/png;base64,{encoded}">'
    text = html.escape(message["text"] or "（已上傳圖片）")
    st.markdown(
        f'<div class="conversation-row {role}" role="group" aria-label="{author}訊息">'
        f'<div class="conversation-bubble"><div class="conversation-author">{author}</div>'
        f'{picture}<div class="conversation-text">{text}</div></div></div>',
        unsafe_allow_html=True,
    )


def archive_session(session):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(session.session_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in (".json", ".png"):
                archive.write(path, arcname=path.name)
    return data.getvalue()


with st.sidebar:
    st.header("案件設定")
    options = [str(path) for path in q3.list_adapters()]
    selection = st.selectbox("選擇實驗B使用的LoRA", ["手動輸入路徑", *options], key="adapter_selection")
    adapter = st.text_input("adapter完整路徑", key="adapter_path") if selection == "手動輸入路徑" else selection
    if st.button("開始新案件", key="new_session", type="primary", use_container_width=True):
        try:
            if not adapter:
                raise ValueError("請選擇或填寫adapter路徑。")
            schema = q3.load_schema()
            engine = real_engine(str(Path(adapter).expanduser().resolve()))
            st.session_state.chat_session = q3.ChatSession(
                engine=engine, schema=schema, adapter_dir=adapter)
            st.session_state.upload_version = st.session_state.get("upload_version", 0) + 1
        except Exception as exc:
            st.error(f"無法建立案件：{exc}")
    session = st.session_state.get("chat_session")
    if session:
        st.caption(f"目前案件：{session.session_dir.name}")
        st.caption("變更上方設定後，按「開始新案件」才會套用。")
        upload = st.file_uploader("附加一張圖片（下次傳送時送出）", type=["png", "jpg", "jpeg", "webp"],
                                  key=f"image_{st.session_state.get('upload_version', 0)}",
                                  disabled=session.routed)
        st.caption("已送出的圖片保留於對話中，後續文字回合不必重傳。")
    else:
        upload = None

st.title("3C 售後客服")
st.caption("說明商品與問題 → 補充資訊 → 確認案件摘要 → 展示分流")
if session is None:
    st.info("請先在左側選擇模型，按「開始新案件」。")
    st.stop()

chat_col, state_col = st.columns([2, 1])
with chat_col:
    for message in session.messages:
        render_message(message, session.session_dir)
    if session.pending:
        st.info("待確認摘要\n\n" + session.pending["summary"])
        # Widget key and call both bind to the currently displayed summary version.
        summary_id = session.pending["id"]
        if st.button("確認摘要", key=f"confirm_{summary_id}", type="primary"):
            try:
                session.confirm_summary(summary_id)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if (not session.routed and session._missing(session.facts) == ["clarification"]
            and session.records and not session.records[-1].get("error")):
        st.warning("仍待釐清的問題：" + session.facts["clarification_question"])
        st.write("請核對目前資料：" + session._summary(session.facts))
        st.caption("若資料有誤或仍有疑點，請在下方補充或更正。"
                   "若已回答追問且資料正確，可結束追問，接著確認完整案件摘要。")
        revision = session.revision
        if st.button("資料正確，結束追問並整理摘要", key=f"resolve_question_{revision}"):
            try:
                session.resolve_clarification(revision)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if session.routed:
        st.success("已產生展示分流結果。尚未建立實際工單；其他問題請開始新案件。")

with state_col:
    st.subheader("案件資訊")
    labels = {"product": "商品", "problem": "問題", "requested_action": "處理需求", "order_id": "訂單編號"}
    for key, label in labels.items():
        st.write(f"**{label}**：{session.facts[key] or '待補充'}")
    dept = session.facts["department"]
    st.write("**建議部門**：" + q3.DEPARTMENTS.get(dept, "待判斷"))
    st.write("**流程狀態**：" + ("已展示分流" if session.routed else "等待摘要確認" if session.pending else "釐清中"))
    if session.records:
        elapsed = session.records[-1].get("elapsed_seconds")
        if elapsed is not None:
            st.caption(f"最近一輪處理時間：{elapsed:.2f} 秒")
    st.download_button("下載完整對話與圖片", archive_session(session),
                       file_name=f"{session.session_dir.name}.zip", mime="application/zip",
                       key="download_session")

text = st.chat_input("請描述售後問題，或補充／修改案件資訊", disabled=session.routed,
                     max_chars=6000, key="message_input")
if text is not None:
    try:
        if upload is not None and upload.size > 10 * 1024 * 1024:
            raise ValueError("圖片請小於10 MiB。")
        with st.spinner("正在處理訊息…"):
            session.send(text, image_path=upload.getvalue() if upload is not None else None)
        st.session_state.upload_version = st.session_state.get("upload_version", 0) + 1
        st.rerun()
    except Exception as exc:
        st.error(str(exc))

if upload is not None and not session.routed:
    if st.button("只傳送這張圖片", key="image_only"):
        try:
            if upload.size > 10 * 1024 * 1024:
                raise ValueError("圖片請小於10 MiB。")
            with st.spinner("正在處理圖片…"):
                session.send("", image_path=upload.getvalue())
            st.session_state.upload_version = st.session_state.get("upload_version", 0) + 1
            st.rerun()
        except Exception as exc:
            st.error(str(exc))