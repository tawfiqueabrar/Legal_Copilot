"""Check the configured Gemini models using the application's shared wrapper."""
import asyncio
import argparse
from typing import Literal

from pydantic import BaseModel

from app.config import settings
from app.services.gemini import GeminiCallWrapper, build_gemini_client, gemini_error_details


class ModelProbe(BaseModel):
    status: Literal["ok"]


async def main(requested_models: list[str] | None = None) -> int:
    if not settings.gemini_api_key:
        print("Gemini unavailable: GEMINI_API_KEY is not configured.")
        return 1

    models = list(dict.fromkeys(requested_models or (
        model for model in (settings.gemini_model, settings.support_check_model, *settings.gemini_fallback_models)
        if model
    )))
    wrapper = GeminiCallWrapper(
        build_gemini_client(settings.gemini_api_key),
        fallback_models=settings.gemini_fallback_models,
    )
    for requested in models:
        try:
            result, actual = await wrapper.generate(
                'Return JSON with status "ok".', ModelProbe, requested
            )
            print(f"{requested} -> {result.status} (served by {actual})", flush=True)
        except Exception as exc:
            error = gemini_error_details(exc, api_key=settings.gemini_api_key)
            print(
                f"{requested} -> {error['category']}; {error['exception_class']}; "
                f"HTTP {error['http_status']}; {error['message']}"
            , flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="*", help="optional model IDs to probe in the supplied order")
    raise SystemExit(asyncio.run(main(parser.parse_args().models)))
