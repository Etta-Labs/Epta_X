import requests
import json

response = requests.post('http://localhost:11434/api/generate', json={
    "model": "qwen2.5-coder:7b",
    "prompt": "Write a Python hello world function",
    "stream": False
})

print(response.json()['response'])
