import json

from pydantic import BaseModel
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3" #"phi3:medium"

def call_ollama(prompt : str)-> str:
    print("call ollama")
    response = requests.post(
        OLLAMA_URL, 
        json = {
            "model" : MODEL,
            "prompt" : prompt,
            "stream" : False
            }
        )
    return response.json()['response']

def parse_structured_output(raw_output : str, model : type[BaseModel]):
    try : 
        start = raw_output.find("{")
        end = raw_output.rfind("}") + 1
        clean_json = raw_output[start:end]
        
        # Remove accidental model markers
        final_json = clean_json.replace("[Response]:", "")
        
        data = json.loads(final_json)

        return model(**data)

    except Exception as e:
        raise ValueError(
             f"Failed to parse structured output.\n"
             f"Raw output:\n{raw_output}\n\n"
             f"Error: {e}"
        )