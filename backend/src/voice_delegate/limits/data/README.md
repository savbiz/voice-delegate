# Offline tokenizer assets

`o200k_base.tiktoken` contains the OpenAI o200k_base merge ranks, serialized from the public tiktoken 0.14.0 package; `tokenizer.json` records its regex. The upstream MIT license is included as LICENSE.tiktoken. Source: https://github.com/openai/tiktoken (tiktoken_ext/openai_public.py).

These assets are bundled to make first-use token accounting offline. They contain no session data. o200k is the application's accounting convention, not a claim about GPT-Live's exact tokenizer. A separate conservative 500 UTF-8 byte bound protects the Live append limit.
