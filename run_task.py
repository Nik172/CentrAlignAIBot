"""
CLI entry point. Usage:
    python run_task.py tasks/configs/invoice_entry.json
"""
import json
import sys
from pathlib import Path

from core.llm_client import get_llm_client
from core.orchestrator import Orchestrator
from core.human_interface import CLIHumanInterface
from core.tools.file_reader_tool import FileReaderTool
from core.tools.api_tool import ApiTool


def load_task_config(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_tools(task_config: dict) -> dict:
    tools = {}
    if "file_reader" in task_config["enabled_tools"]:
        tools["file_reader"] = FileReaderTool(base_dir=task_config["data_dir"])
    if "internal_api" in task_config["enabled_tools"]:
        tools["internal_api"] = ApiTool(base_url=task_config["env_base_url"])
    return tools


def main():
    task_path = sys.argv[1] if len(sys.argv) > 1 else "tasks/configs/invoice_entry.json"
    task_config = load_task_config(task_path)

    tools = build_tools(task_config)
    llm = get_llm_client()
    human = CLIHumanInterface()

    company_context = ""
    if task_config.get("company_memory_doc"):
        company_context = Path(task_config["company_memory_doc"]).read_text(encoding="utf-8")

    verification_api_tool = ApiTool(base_url=task_config["env_base_url"])

    orchestrator = Orchestrator(
        task_config=task_config, tools=tools, api_tool_for_verification=verification_api_tool,
        llm=llm, human_interface=human, company_context=company_context,
    )

    summary = orchestrator.run()

    print("\n" + "#" * 60)
    print("FINAL SUMMARY")
    print("#" * 60)
    print(summary.summary_text)
    print(f"\nFull audit log: {summary.evidence[0]}")


if __name__ == "__main__":
    main()