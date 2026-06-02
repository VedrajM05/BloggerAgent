from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import PromptTemplate


def validate_prompt_template(prompt_text: str) -> list[str]:
    template = PromptTemplate.from_template(prompt_text)
    input_vars = list(template.input_variables)
    print(f"Detected input variables: {input_vars}")
    return input_vars


def validate_all_prompt_files(prompts_dir: str | Path = "prompts") -> dict[str, list[str]]:
    prompts_path = Path(prompts_dir)
    results: dict[str, list[str]] = {}

    for prompt_file in sorted(prompts_path.glob("*.md")):
        text = prompt_file.read_text(encoding="utf-8")
        vars_ = PromptTemplate.from_template(text).input_variables
        results[str(prompt_file)] = list(vars_)
        print(f"{prompt_file}: {list(vars_)}")

    return results

