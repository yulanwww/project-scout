import json
import streamlit as st
from collector import ToolRepository, FIELDS

st.set_page_config(page_title="Project Scout", page_icon="📚", layout="wide")
repo = ToolRepository()
st.title("📚 Project Scout · AI 工具收藏库")
st.caption("本地 SQLite · 项目研究与收藏")
if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))
labels = dict(zip(FIELDS, ["工具名称", "介绍", "用途", "使用方法", "官网", "GitHub", "来源链接", "价格", "分类", "标签（逗号分隔）", "收藏日期（YYYY-MM-DD，留空为今天）"]))

def editor(key, existing=None):
    existing = existing or {}
    with st.form(key):
        values = {}
        for field in FIELDS:
            widget = st.text_area if field in ("description", "purpose", "usage") else st.text_input
            values[field] = widget(labels[field], value=existing.get(field, ""))
        submit = st.form_submit_button("保存工具")
    if submit:
        try:
            if existing:
                repo.update(existing["id"], values)
            else:
                repo.add(values)
            st.session_state["notice"] = "工具已保存"
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

browse, add, upload = st.tabs(["浏览与管理", "新增工具", "JSON 导入"])
with browse:
    query = st.text_input("搜索名称、介绍、用途、分类、标签等")
    categories = sorted({t["category"] for t in repo.search() if t["category"]})
    category = st.selectbox("分类筛选", [""] + categories, format_func=lambda x: x or "全部")
    rows = repo.search(query, category)
    st.write(f"找到 {len(rows)} 个工具")
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        selected = st.selectbox("选择工具查看或编辑", [r["id"] for r in rows], format_func=lambda i: next(r["name"] for r in rows if r["id"] == i))
        tool = repo.get(selected)
        with st.expander("查看详细信息", expanded=True):
            for f in FIELDS:
                st.text(f"{labels[f]}：{tool[f]}")
        with st.expander("编辑工具"):
            editor(f"edit_{selected}", tool)
        confirm = st.checkbox("确认永久删除此工具", key=f"confirm_{selected}")
        if st.button("删除工具", disabled=not confirm):
            repo.delete(selected)
            st.session_state["notice"] = "工具已删除"
            st.rerun()
    else:
        st.info("暂无匹配工具，可以手动新增或导入 JSON。")
with add:
    editor("add_tool")
with upload:
    st.write("支持单个工具对象或对象数组。仅 name 必填，其余字段可省略。重复工具将跳过；存在格式错误时整批不写入。")
    st.download_button("下载 JSON 示例", data=json.dumps([{"name": "示例工具", "description": "工具介绍", "tags": ["Agent", "效率"]}], ensure_ascii=False, indent=2), file_name="tools-example.json", mime="application/json")
    file = st.file_uploader("选择 JSON 文件", type=["json"])
    if file and st.button("导入收藏库"):
        try:
            result = repo.import_json(file.getvalue().decode("utf-8-sig"))
            st.session_state["notice"] = f"导入完成：新增 {result['added']} 条，跳过重复 {result['duplicates']} 条"
            st.rerun()
        except (ValueError, UnicodeError) as exc:
            st.error(str(exc))
