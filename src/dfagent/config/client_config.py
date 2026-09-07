import os
from dotenv import load_dotenv
from openai import OpenAI
from anthropic import Anthropic

load_dotenv()

api_key = os.environ.get("APIKEY")
base_url = os.environ.get("BASEURL")
model = os.environ.get("MODEL")
choice = os.environ.get("CHOICE_API")


def get_client(choice: str | None = None):
    if choice == "openai":
        return OpenAI(api_key=api_key, base_url=base_url)
    elif choice == "anthropic":
        return Anthropic(api_key=api_key, base_url=base_url)
    raise ValueError(f"Unknown CHOICE_API: {choice!r}")

client = get_client(choice)



