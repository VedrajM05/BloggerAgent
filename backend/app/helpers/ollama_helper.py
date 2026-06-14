import json

from pydantic import BaseModel
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "deepseek-r1:8b" #"phi3:medium" "llama3"  "deepseek-r1:8b"

def call_ollama_structured(prompt: str, model_name : str) -> str:
    """
    Use Ollama in JSON mode for structured outputs that are parsed by Pydantic.
    """
    print("call ollama (structured)")
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
    )
    # print("OLLAMA RAW RESPONSE:")
    # print(response.json())

    return response.json()["response"]


def call_ollama_text(prompt: str, model_name : str) -> str:
    """
    Use Ollama in plain-text mode for free-form generation (e.g., Markdown sections).
    IMPORTANT: Do NOT use JSON mode here.
    """
    print("call ollama (text)")
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        },
    )
    return response.json()["response"]


# Backwards-compatible alias used across the codebase.
# Prefer call_ollama_structured() or call_ollama_text() in new code.
def call_ollama(prompt: str, model_name : str) -> str:
    return call_ollama_structured(prompt, model_name)

def normalize_for_pydantic(data):
    """
    Normalize parsed JSON payloads for Pydantic models that expect list[str] fields.

    Local LLMs sometimes return richer nested objects inside arrays. We keep the
    information by stringifying non-string list items rather than failing validation.
    """
    if not isinstance(data, dict):
        return data

    normalized_root = dict(data)
    for key, value in list(normalized_root.items()):
        if not isinstance(value, list):
            continue

        normalized_list: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                normalized_list.append(item)
            elif isinstance(item, (dict, list)):
                normalized_list.append(json.dumps(item, ensure_ascii=False))
            else:
                # numbers/bools/etc -> string
                normalized_list.append(str(item))

        normalized_root[key] = normalized_list

    return normalized_root

def parse_structured_output(raw_output : str, model : type[BaseModel]):
    try:
        # 1) Extract JSON from raw LLM response
        start = raw_output.find("{")
        end = raw_output.rfind("}") + 1
        extracted_json = raw_output[start:end]

        # Remove accidental model markers
        extracted_json = extracted_json.replace("[Response]:", "")

        # 2) json.loads()
        data = json.loads(extracted_json)

        # 3) normalize (only for schemas that expect list[str] fields)
        if getattr(model, "__name__", "") == "ResearchSummary":
            data = normalize_for_pydantic(data)
        
        # 4) model(**data)
        return model(**data)

    except Exception as e:
        raise ValueError(
             f"Failed to parse structured output.\n"
             f"Raw output:\n{raw_output}\n\n"
             f"Error:\n{repr(e)}"
        )
