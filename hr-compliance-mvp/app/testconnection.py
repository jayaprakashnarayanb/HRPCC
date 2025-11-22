import os
import sys

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception as e:
    print(
        "Missing dependency: install 'langchain-google-genai' and 'google-generativeai'.",
        e,
    )
    sys.exit(1)


def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY environment variable is not set.")
        sys.exit(1)

    # Keep in sync with app/ai.py behavior
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
    if model.endswith("-latest"):
        model = model[: -len("-latest")]

    print(f"Using model: {model}")
    try:
        # Prefer explicit api_key param to avoid ADC/OAuth confusion
        llm = ChatGoogleGenerativeAI(model=model, temperature=0, api_key=api_key)
        res = llm.invoke("Say 'Gemini model working' in one short sentence.")
        print(getattr(res, "content", str(res)))
    except Exception as e:
        msg = str(e)
        print("LLM test failed:", msg)
        if "404" in msg or "Not Found" in msg:
            print(
                "Hint: 404 often means the model name is invalid or unavailable for your API key.\n"
                " - Ensure packages are up to date: pip install -U langchain-google-genai google-generativeai\n"
                " - Try GEMINI_MODEL=gemini-1.5-flash (without -latest)\n"
                " - If you intend to use Vertex AI, use the Vertex integration (langchain-google-vertexai) instead."
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
