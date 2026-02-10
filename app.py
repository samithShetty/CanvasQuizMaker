import json

import streamlit as st
from canvasapi import Canvas

from utils import evaluate_expression, generate_sample, render_with_sample

# Minimal single-page app
st.set_page_config(page_title="Canvas Quiz Maker", layout="wide")
st.title("Canvas Quiz Maker")

# init
st.session_state.setdefault("variables", {})
st.session_state.setdefault("question_template", "")
st.session_state.setdefault("question_type", "Multiple Choice")
st.session_state.setdefault("last_sample", {})

c1, c2 = st.columns([1.1, 2])

with c1:
    st.header("Variables")
    st.write("Add variables used in templates.")

    name = st.text_input("Name", key="v_name")
    typ = st.selectbox(
        "Type",
        ["Random Number", "Random Choice", "Math Expression", "Custom"],
        key="v_type",
    )

    if typ == "Random Number":
        mn = st.number_input("Min", value=1, key="v_min")
        mx = st.number_input("Max", value=10, key="v_max")
        step = st.number_input("Step", value=1, min_value=1, key="v_step")
        rule_data = {"type": "random_number", "min": mn, "max": mx, "step": step}
        desc = f"{mn}..{mx} step {step}"
    elif typ == "Random Choice":
        choices = st.text_area("Choices (one per line)", key="v_choices")
        opts = [s.strip() for s in choices.splitlines() if s.strip()]
        rule_data = {"type": "random_choice", "choices": opts}
        desc = f"{len(opts)} choices"
    elif typ == "Math Expression":
        expr = st.text_input(
            "Expression", placeholder="e.g., {{a}} * 2 + 5", key="v_expr"
        )
        rule_data = {"type": "math_expression", "expression": expr}
        desc = expr
    else:
        desc = st.text_area("Description", key="v_desc")
        rule_data = {"type": "custom", "description": desc}

    if st.button("Add"):
        if not name:
            st.error("Enter a variable name")
        elif name in st.session_state.variables:
            st.error("Already exists")
        else:
            st.session_state.variables[name] = {
                "rule_type": typ,
                "rule_description": desc,
                "rule_data": rule_data,
            }
            st.success("Added")

    st.markdown("---")
    st.write("Existing")
    for n, v in st.session_state.variables.items():
        st.write(f"- **{n}**: {v['rule_description']}")
        if st.button(f"Del {n}", key=f"del_{n}"):
            del st.session_state.variables[n]

with c2:
    st.header("Editor")
    st.session_state.question_type = st.selectbox(
        "Type",
        ["Multiple Choice", "Short Answer", "Essay", "Fill in the Blank", "True/False"],
        index=0,
    )
    st.session_state.question_template = st.text_area(
        "Template (use {{var}})", value=st.session_state.question_template, height=200
    )

    # Question-specific inputs
    if st.session_state.question_type == "Multiple Choice":
        num_options = st.number_input(
            "Options", min_value=2, max_value=6, value=4, step=1, key="opt_count"
        )
        options = []
        for i in range(int(num_options)):
            options.append(st.text_input(f"Option {i+1}", key=f"opt_{i}"))
        correct = st.selectbox(
            "Correct Option",
            range(int(num_options)),
            format_func=lambda x: f"Option {x+1}",
            key="correct_opt",
        )
        st.session_state.template_data = {
            "type": "mc",
            "options": options,
            "correct": correct,
        }
    elif st.session_state.question_type == "True/False":
        correct = st.radio("Correct", ["True", "False"])
        st.session_state.template_data = {"type": "tf", "correct": correct}
    else:
        answer_key = st.text_area("Answer Key", height=80)
        st.session_state.template_data = {"type": "open", "answer_key": answer_key}

    # General comment (applies to any question type)
    general_comment = st.text_area(
        "General Comment (optional)",
        value=st.session_state.get("template_data", {}).get("general_comment", ""),
        height=80,
        key="general_comment",
    )
    include_general = st.checkbox(
        "Include General Comment in preview",
        value=st.session_state.get("template_data", {}).get("include_general", False),
        key="include_general",
    )

    # Store/merge into template_data so it persists and is exported
    td = st.session_state.get("template_data", {})
    td["general_comment"] = general_comment
    td["include_general"] = include_general
    st.session_state.template_data = td

    # Generate controls
    st.markdown("**Generate Samples**")
    sample_count = st.number_input(
        "How many samples?",
        min_value=1,
        max_value=50,
        value=3,
        key="sample_count",
    )
    gen_col1, gen_col2 = st.columns([1, 1])
    if gen_col1.button("Generate Now"):
        st.session_state.last_sample = generate_sample(st.session_state.variables)
        st.session_state.multiple_samples = [st.session_state.last_sample]
    if gen_col2.button("Generate Samples"):
        samples = [
            generate_sample(st.session_state.variables)
            for _ in range(int(sample_count))
        ]
        st.session_state.multiple_samples = samples
        st.session_state.last_sample = samples[0]

    st.divider()
    st.markdown("**Rendered (single)**")
    st.write(
        render_with_sample(
            st.session_state.question_template or "", st.session_state.last_sample
        )
    )

# ---------------- Preview Section (full width) ----------------
st.divider()
st.header("👁️ Live Preview")
st.markdown("Rendered samples appear below in a compact grid")

samples = st.session_state.get("multiple_samples", [])

st.subheader("Variables")
if st.session_state.variables:
    for name, v in st.session_state.variables.items():
        st.markdown(f"- **{name}** — {v['rule_description']}")
else:
    st.info("No variables defined yet")

st.divider()
st.subheader("Samples")

if samples:
    cols_per_row = 4
    for i in range(0, len(samples), cols_per_row):
        row = samples[i : i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, sample in enumerate(row):
            with cols[j]:
                sample_idx = i // cols_per_row + j
                bg_color = "#04070f" if (sample_idx + (i % 2)) % 2 else "#10192f"
                q = render_with_sample(st.session_state.question_template or "", sample)

                td = st.session_state.get("template_data", {})
                cell_html = f"<div style='background-color:{bg_color}; padding:12px; border-radius:6px;'>"
                cell_html += f"<div style='padding:8px;'>{q}</div>"

                if td.get("type") == "mc":
                    cell_html += f"<div style='background-color:{bg_color}; padding:8px; border:1px dotted #888; border-radius:4px; margin-top:8px;'><sub>**Options**</sub>"
                    for k, opt in enumerate(td.get("options", [])):
                        rendered_opt = render_with_sample(opt or "", sample)
                        if k == td.get("correct"):
                            cell_html += f"<br/><sub>- ✅ {rendered_opt}</sub>"
                        else:
                            cell_html += f"<br/><sub>- {rendered_opt}</sub>"
                    cell_html += "</div>"
                elif td.get("type") == "tf":
                    cell_html += f"<div style='background-color:{bg_color}; padding:8px; border:1px dotted #888; border-radius:4px; margin-top:8px;'><sub>**Answer:** {td.get('correct')}</sub></div>"
                elif td.get("type") == "open":
                    ak = td.get("answer_key", "") or ""
                    if ak:
                        rendered_answer = ""
                        if "{{" in ak and "}}" in ak:
                            rendered_answer = render_with_sample(ak, sample)
                        else:
                            rendered_answer = evaluate_expression(ak, sample)
                        cell_html += f"<div style='background-color:{bg_color}; padding:8px; border:1px dotted #888; border-radius:4px; margin-top:8px; white-space: pre-wrap;'><sub>**Answer:**</sub><br/><sub>{rendered_answer}</sub></div>"
                    else:
                        cell_html += f"<div style='background-color:{bg_color}; padding:8px; border:1px dotted #888; border-radius:4px; margin-top:8px;'><sub>**Answer:** (none)</sub></div>"

                cell_html += "</div>"

                # Optionally show the general comment block
                gc = td.get("general_comment", "") or ""
                if td.get("include_general") and gc:
                    rendered_gc = render_with_sample(gc, sample)
                    cell_html += f"<div style='background-color:{bg_color}; padding:8px; border:1px dotted #888; border-radius:4px; margin-top:8px; white-space: pre-wrap;'><sub>**Comment:**</sub><br/><sub>{rendered_gc}</sub></div>"

                cell_html += "</div>"
                st.markdown(cell_html, unsafe_allow_html=True)
    st.download_button(
        "Export Samples JSON",
        data=json.dumps(samples, indent=2),
        file_name="samples.json",
    )
else:
    st.info("No samples generated yet. Use the Editor to generate samples.")

st.markdown("---")
st.download_button(
    "Export Template JSON",
    data=json.dumps(
        {
            "variables": st.session_state.variables,
            "template": st.session_state.question_template,
            "template_data": st.session_state.get("template_data", {}),
        },
        indent=2,
    ),
    file_name="template.json",
    mime="application/json",
)

# Canvas Integration
st.divider()
st.header("🎓 Upload to Canvas")


st.subheader("Question Bank")
bank_id = st.number_input(
    "Question Bank ID",
    value=0,
    step=1,
    help="Enter the Canvas question bank ID to upload samples to",
)

if st.button("Upload Samples to Canvas", key="upload_canvas"):
    samples = st.session_state.get("multiple_samples", [])
    if not samples:
        st.error("Generate samples first before uploading")
    elif bank_id == 0:
        st.error("Enter a valid question bank ID")
    else:
        try:
            from canvas_integration import upload_samples_to_canvas

            result = upload_samples_to_canvas(
                int(bank_id),
                samples,
                st.session_state.question_template,
                st.session_state.get("template_data", {}),
                st.session_state.variables,
            )

            if result["success"] > 0:
                st.success(f"✅ Uploaded {result['success']} questions to Canvas")
            if result["failed"] > 0:
                st.warning(f"⚠️ {result['failed']} questions failed")
                if result["errors"]:
                    with st.expander("View errors"):
                        for err in result["errors"][:10]:
                            st.text(err)
        except Exception as e:
            st.error(f"Upload failed: {str(e)}")

st.caption("Minimal single-file UI backed by utils.py")
