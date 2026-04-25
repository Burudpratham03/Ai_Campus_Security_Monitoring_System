import os
import traceback

from dotenv import load_dotenv
import google.generativeai as genai


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing in .env/environment")

    genai.configure(api_key=api_key)

    try:
        print("[GEMINI] Models supporting generateContent:")
        count = 0
        for model in genai.list_models():
            methods = set(
                getattr(model, "supported_generation_methods", []) or [])
            if "generateContent" in methods:
                print(getattr(model, "name", ""))
                count += 1

        if count == 0:
            print("[GEMINI] No generateContent models found for this API key/project.")
    except Exception as exc:
        print(f"[GEMINI][ERROR] {exc}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
