from pathlib import Path
from langchain_core.prompts import PromptTemplate
import os

class PromptLoader:

    BASE_PATH = Path(__file__).resolve().parent.parent.parent
    FULL_PATH = BASE_PATH/"prompts"
    
    @classmethod
    def load_prompts(cls, filename : str, input_variables : list[str]) -> PromptTemplate:
        
        file_path = cls.FULL_PATH/filename

        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found : {file_path}")
        
        template_text = file_path.read_text(encoding="utf-8")

        return PromptTemplate(
            input_variables= input_variables,
            template= template_text
        )