"""Print a composed voice prompt, e.g. to paste into the ElevenLabs agent dashboard.

python -m voice_delegate.prompts --mode intent --web-search
"""

import argparse

from voice_delegate.prompts import voice_prompt


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m voice_delegate.prompts")
    parser.add_argument("--mode", choices=["classic", "intent", "semantic"], default="intent")
    parser.add_argument("--web-search", action="store_true")
    args = parser.parse_args(argv)
    print(
        voice_prompt(
            web_search=args.web_search,
            intent_cancellation=args.mode != "classic",
            decisions_cancel=args.mode == "semantic",
        )
    )


if __name__ == "__main__":
    main()
