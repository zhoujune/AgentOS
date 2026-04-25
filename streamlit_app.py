from __future__ import annotations

from pathlib import Path

import streamlit as st

from host_ui.app_support import (
    DEFAULT_API_KEY_FILE,
    TASK_DIR_PRESETS,
    build_custom_task_payload,
    create_custom_task_file,
    list_task_cases,
    latest_reports,
    read_json,
    read_text,
    report_rows,
    run_eval,
    slugify,
    task_case_rows,
    test_llm_connection,
)


GUIDE_MD = """
### What This UI Does

This host UI runs the same AgentOS evaluation path used in the paper:

- QEMU boots the AgentOS guest image
- the guest agent issues LLM requests through the bridge
- `llm_proxy.py` calls the configured model API
- VTRM mediates tool actions inside the guest
- the World Effect Judge checks post-run outcomes

### Before You Start

1. Make sure the built images exist under `artifacts/images/`.
2. Put your API key in a readable file such as `~/.config/agentos/api_key`.
3. Confirm the sidebar settings:
   - API style
   - API endpoint
   - model
   - temperature
   - API key file
4. Click `Test LLM Connection`.

If you only want to run the supplied artefacts, no rebuild is needed. A separate Buildroot checkout is only required if you want to rebuild or modify the guest image.

### Recommended Workflow

#### Quick Demo

1. Open `Custom Task`.
2. Keep `agentos` mode selected.
3. Run a simple one-off task.
4. Inspect the final answer and, if needed, the report logs.

#### Benchmark Run

1. Open `Benchmark`.
2. Choose a suite such as `Should Pass` or `Should Fail / All`.
3. Select one or more modes.
4. Run all cases or a selected subset.
5. Review the summary table and failed-case table.

#### Report Inspection

1. Open `Reports`.
2. Select a recent run directory.
3. Inspect `summary.json`, `summary.md`, and case-level details.

### Notes

- `AgentOS-Eval` is the reproducible research profile.
- `AgentOS-Prod` is the deployment-oriented image derived from the same runtime.
- The default benchmark model is `kimi-k2-0905-preview` with temperature `0.0`.
"""


def completion_label(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "PASS" if value else "FAIL"


st.set_page_config(page_title="AgentOS Host UI", page_icon="🛡️", layout="wide")

st.title("AgentOS Host UI")
st.caption("Host-side demo and benchmark console for AgentOS, VTRM, and the World Effect Judge.")

with st.sidebar:
    st.header("Run Settings")
    api_style = st.selectbox("API style", options=["openai", "anthropic"], index=0)
    default_endpoint_value = (
        "https://api.moonshot.cn/v1/chat/completions"
        if api_style == "openai"
        else "https://api.anthropic.com/v1/messages"
    )
    api_endpoint = st.text_input("Custom API endpoint (optional)", value=default_endpoint_value)
    default_model = st.text_input("Model", value="kimi-k2-0905-preview")
    temperature = st.slider("Temperature", min_value=0.0, max_value=1.5, value=0.0, step=0.1)
    api_key_path = Path(st.text_input("API key file", value=str(DEFAULT_API_KEY_FILE)))
    task_timeout = st.number_input("Task timeout (seconds)", min_value=30, max_value=900, value=180, step=10)
    vm_boot_timeout = st.number_input("VM boot timeout (seconds)", min_value=30, max_value=300, value=90, step=10)
    st.markdown("This UI reuses `judge/run_vtrm_eval.py`, so demo runs and paper benchmarks stay aligned.")
    st.caption("Use `openai` for OpenAI-compatible endpoints. Use `anthropic` for Claude's native Messages API.")
    with st.expander("Usage Guide"):
        st.markdown(GUIDE_MD)
    if st.button("Test LLM Connection"):
        try:
            with st.spinner("Testing LLM connection..."):
                test_result = test_llm_connection(
                    model=default_model,
                    api_style=api_style,
                    api_endpoint=api_endpoint.strip(),
                    temperature=float(temperature),
                    api_key_file=api_key_path,
                )
            if "error" in test_result:
                st.error(f"LLM test failed: {test_result['error']}")
            else:
                st.success("LLM test succeeded.")
                st.code(str(test_result.get("content", "")))
        except Exception as exc:
            st.error(f"LLM test failed: {exc}")

tab_custom, tab_bench, tab_reports, tab_guide = st.tabs(["Custom Task", "Benchmark", "Reports", "Guide"])

with tab_custom:
    st.subheader("Run a One-Off Task")
    st.write("Enter a task and get the agent's final answer through the full QEMU + bridge + WEJ harness.")

    col1, col2 = st.columns(2)
    with col1:
        custom_name = st.text_input("Task name", value="UI Custom Task")
        custom_mode = st.selectbox("Agent mode", options=["agentos", "cot", "naive"], index=0)
        custom_reset = st.checkbox("Reset after case", value=False)
    with col2:
        show_debug_logs = st.checkbox("Show debug logs", value=False)

    default_task = (
        "Use fs.write to write the text hello from streamlit to /workspace/ui_result.txt. "
        "Do not write any other file. Then return final."
    )
    custom_task_text = st.text_area("Task text", value=default_task, height=180)

    if st.button("Run Custom Task", type="primary"):
        task_id = slugify(custom_name)
        payload = build_custom_task_payload(
            task_id=task_id,
            name=custom_name,
            task_text=custom_task_text,
            required_path="",
            required_substring="",
        )
        task_dir, task_path = create_custom_task_file(payload)
        try:
            with st.spinner("Running custom task through AgentOS harness..."):
                result = run_eval(
                    tasks_dir=task_dir,
                    task_id=task_id,
                    agent_mode=custom_mode,
                    reset_between_cases=custom_reset,
                    model=default_model,
                    api_style=api_style,
                    api_endpoint=api_endpoint.strip(),
                    temperature=float(temperature),
                    api_key_file=api_key_path,
                    task_timeout=int(task_timeout),
                    vm_boot_timeout=int(vm_boot_timeout),
                )
            st.success(f"Finished run: {result.run_dir}")

            if result.summary:
                case = result.summary.get("case_results", [{}])[0]
                st.markdown("**Final Output**")
                st.code(str(case.get("task_answer", "")))
                if show_debug_logs:
                    for label, rel in [
                        ("Case Report", "case_report.json"),
                        ("QEMU Log", "qemu.log"),
                        ("LLM Proxy Log", "llm_proxy.log"),
                    ]:
                        candidate = result.run_dir / task_id / rel
                        if candidate.exists():
                            with st.expander(label):
                                if candidate.suffix == ".json":
                                    st.json(read_json(candidate))
                                else:
                                    st.text(read_text(candidate))
                    with st.expander("Evaluator stdout"):
                        st.text(result.stdout)
                    if result.stderr.strip():
                        with st.expander("Evaluator stderr"):
                            st.text(result.stderr)
        except Exception as exc:
            st.error(f"Failed to run custom task: {exc}")
            if show_debug_logs:
                with st.expander("Generated task JSON"):
                    st.code(task_path.read_text(encoding="utf-8"), language="json")

with tab_bench:
    st.subheader("Run Benchmarks")
    st.write("Choose an existing benchmark suite, run all cases or a selected subset, and inspect per-mode benchmark summaries.")

    preset_name = st.selectbox("Task suite", list(TASK_DIR_PRESETS.keys()), index=0)
    available_cases = list_task_cases(preset_name)
    selected_modes = st.multiselect("Modes", options=["agentos", "cot", "naive"], default=["agentos"])
    bench_reset = st.checkbox("Reset between cases", value=True)
    case_selection_mode = st.radio("Cases", options=["All cases", "Select cases"], horizontal=True)
    selected_case_ids: list[str]
    if case_selection_mode == "Select cases":
        selected_case_ids = st.multiselect(
            "Select task IDs",
            options=[case.task_id for case in available_cases],
            default=[],
        )
    else:
        selected_case_ids = [case.task_id for case in available_cases]

    if available_cases:
        st.caption(f"{len(available_cases)} cases available in this suite.")
    else:
        st.caption("No cases found in this suite.")

    if st.button("Run Benchmark"):
        if not selected_modes:
            st.warning("Select at least one mode.")
            st.stop()
        if not selected_case_ids:
            st.warning("Select at least one case.")
            st.stop()

        selected_cases = [case for case in available_cases if case.task_id in set(selected_case_ids)]
        selected_cases.sort(key=lambda case: case.task_id)
        total_jobs = len(selected_modes) * len(selected_cases)
        include_completion = not all(case.outcome_kind == "should_fail" for case in selected_cases)

        progress_text = st.empty()
        progress_bar = st.progress(0.0)
        summary_rows: list[dict[str, object]] = []
        failed_rows: list[dict[str, object]] = []

        completed_jobs = 0
        for mode in selected_modes:
            mode_results: list[dict[str, object]] = []
            for case in selected_cases:
                completed_jobs += 1
                progress_text.info(
                    f"Now processing {completed_jobs}/{total_jobs} cases: {case.task_id} ({mode})"
                )
                progress_bar.progress(completed_jobs / total_jobs)
                try:
                    result = run_eval(
                        tasks_dir=case.tasks_dir,
                        task_id=case.task_id,
                        agent_mode=mode,
                        reset_between_cases=bench_reset,
                        model=default_model,
                        api_style=api_style,
                        api_endpoint=api_endpoint.strip(),
                        temperature=float(temperature),
                        api_key_file=api_key_path,
                        task_timeout=int(task_timeout),
                        vm_boot_timeout=int(vm_boot_timeout),
                    )
                    case_result = (result.summary or {}).get("case_results", [{}])[0]
                    completion_ok = case_result.get("task_completion_ok", result.task_completion_ok)
                    mode_results.append(
                        {
                            "task_id": case.task_id,
                            "task_name": case.name,
                            "outcome_kind": case.outcome_kind,
                            "mode": mode,
                            "run_id": result.run_dir.name,
                            "report_dir": str(result.run_dir),
                            "task_completion_ok": completion_ok,
                            "safety_ok": bool(case_result.get("safety_ok", result.safety_ok)),
                            "task_answer": str(case_result.get("task_answer", "")),
                        }
                    )
                except Exception as exc:
                    mode_results.append(
                        {
                            "task_id": case.task_id,
                            "task_name": case.name,
                            "outcome_kind": case.outcome_kind,
                            "mode": mode,
                            "run_id": "error",
                            "report_dir": str(exc),
                            "task_completion_ok": False,
                            "safety_ok": False,
                            "task_answer": str(exc),
                        }
                    )

            safety_pass = sum(1 for row in mode_results if bool(row["safety_ok"]))
            summary_row: dict[str, object] = {
                "suite": preset_name,
                "mode": mode,
                "case_count": len(mode_results),
                "safety_pass": safety_pass,
                "safety_rate": f"{(100.0 * safety_pass / len(mode_results)):.1f}%" if mode_results else "0.0%",
            }
            if include_completion:
                completion_checked = [row for row in mode_results if row["task_completion_ok"] is not None]
                completion_pass = sum(1 for row in completion_checked if row["task_completion_ok"] is True)
                summary_row["completion_pass"] = completion_pass
                summary_row["completion_rate"] = (
                    f"{(100.0 * completion_pass / len(completion_checked)):.1f}%" if completion_checked else "N/A"
                )
            summary_rows.append(summary_row)

            for row in mode_results:
                completion_failed = include_completion and row["task_completion_ok"] is False
                failed = (not bool(row["safety_ok"])) or completion_failed
                if failed:
                    failed_row: dict[str, object] = {
                        "mode": row["mode"],
                        "task_id": row["task_id"],
                        "run_id": row["run_id"],
                        "safety": "PASS" if row["safety_ok"] else "FAIL",
                        "report_dir": row["report_dir"],
                    }
                    if include_completion:
                        failed_row["completion"] = completion_label(row["task_completion_ok"])
                    failed_rows.append(failed_row)

        progress_text.success(f"Finished {total_jobs}/{total_jobs} case runs.")
        progress_bar.progress(1.0)

        st.markdown("**Benchmark Summary**")
        st.dataframe(summary_rows, use_container_width=True)

        st.markdown("**Failed Cases**")
        if failed_rows:
            st.dataframe(failed_rows, use_container_width=True)
        else:
            st.success("No failed cases in this run.")

        st.info("Use the Reports tab to inspect individual case details after a run.")

with tab_reports:
    st.subheader("Recent Reports")
    rows = report_rows()
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.write("No reports found yet.")

    report_dirs = latest_reports()
    selected_report = st.selectbox("Open report", options=report_dirs, format_func=lambda p: p.name if isinstance(p, Path) else str(p))
    if selected_report:
        summary_path = selected_report / "summary.json"
        if summary_path.exists():
            summary = read_json(summary_path)
            top = st.columns(4)
            top[0].metric("Cases", summary.get("case_count", 0))
            top[1].metric("Task Completion", completion_label(summary.get("task_completion_ok")))
            top[2].metric("Safety", "PASS" if summary.get("safety_ok") else "FAIL")
            top[3].metric("Overall", "PASS" if summary.get("all_ok") else "FAIL")
            st.dataframe(task_case_rows(summary), use_container_width=True)
            with st.expander("summary.json"):
                st.json(summary)
        summary_md = selected_report / "summary.md"
        if summary_md.exists():
            with st.expander("summary.md"):
                st.text(read_text(summary_md))

with tab_guide:
    st.subheader("Usage Guide")
    st.markdown(GUIDE_MD)
    st.info("For the full operator guide, see `README.md` in the repository root.")
