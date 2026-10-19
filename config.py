from dotenv import load_dotenv
from pydantic_ai.models.fallback import FallbackModel

load_dotenv()  # must run before the models below are created

MODEL = FallbackModel(
    "google:gemini-3.8-flash",
    "google:gemini-3.7-flash",
    "google:gemini-3.5-flash",
    "google:gemini-3.1-flash-lite",
)