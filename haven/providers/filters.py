"""Which models are chat models, which can see images, which can think. One place, unit-tested.

Provider metadata always wins (Anthropic capabilities, Gemini `thinking`, Ollama/LM Studio capabilities,
Mistral `capabilities`, OpenRouter/DeepSeek modalities). The name heuristics below are the fallback for
providers whose /models only returns ids (OpenAI, Groq, xAI, Cerebras, Fireworks, custom servers).
"""
import re

# ---- not chat models (matched on whole tokens of the id, case-insensitive) ----
_NOT_CHAT = [
    r"embed\w*", r"embedding", r"tts", r"whisper", r"transcribe", r"speech", r"audio", r"realtime", r"voice",
    r"dall-e", r"dalle", r"gpt-image", r"imagen", r"image-generation", r"imagine", r"veo", r"sora", r"video",
    r"moderation", r"omni-moderation", r"rerank\w*", r"guard", r"prompt-guard", r"safeguard", r"orpheus", r"playai",
    r"stable-diffusion", r"sdxl", r"flux", r"kokoro", r"lyria", r"chirp", r"ocr", r"bge", r"e5", r"minilm", r"nomic",
    r"clip", r"davinci", r"babbage", r"turbo-instruct", r"aqa", r"native-audio", r"live", r"computer-use", r"robotics",
    r"tts", r"music", r"diffusion", r"text-to-image", r"image-preview",
]
_NOT_CHAT_RE = re.compile(r"(^|[-_/.:@ ])(" + "|".join(_NOT_CHAT) + r")($|[-_/.:@ \d])", re.I)
# image *output* models named "<family>-image" (e.g. gemini-2.5-flash-image, grok-imagine-image)
_IMAGE_OUT_RE = re.compile(r"-image(-\d+(\.\d+)?)?($|-preview|-exp)", re.I)


def is_chat_model(model_id: str) -> bool:
    mid = model_id.strip()
    if not mid:
        return False
    if _NOT_CHAT_RE.search(mid) or _IMAGE_OUT_RE.search(mid):
        return False
    return True


# ---- vision (images in) by name ----
_VISION_RE = re.compile(
    r"vision|(^|[-_/.:])vl($|[-_/.:\d])|-vl-|llava|bakllava|pixtral|moondream|minicpm-v|qwen\d?(\.\d)?-?vl|"
    r"gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-5|gpt-6|(^|/)o[134]($|-)|chatgpt-4o|"
    r"claude-(3|opus|sonnet|haiku|\d)|gemini|gemma-?3|gemma3|grok-4|grok-\d+-vision|"
    r"llama-?4|llama-3\.2-\d+b-vision|mistral-(small|medium)-(2503|2505|3|latest)|mistral-medium|"
    r"(^|[-_/])kimi-(k2\.5|vl)|glm-4(\.\d)?v|internvl|phi-?4-multimodal|granite-vision|deepseek-flash", re.I)


def guess_vision(model_id: str) -> bool:
    return bool(_VISION_RE.search(model_id))


# ---- reasoning / thinking by name ----
_REASONING_RE = re.compile(
    r"(^|[-_/.:])(o[1-9])($|[-_.])|gpt-5|gpt-6|gpt-oss|reason|thinking|deepseek-r1|(^|[-_/])r1($|[-_])|qwq|qwen3|"
    r"magistral|grok-(3-mini|4)|deepseek-v4|deepseek-reasoner|phi-4-reasoning|sonar-reasoning|kimi-k2-thinking|"
    r"glm-4\.[5-9]|minimax-m|muse-spark|nemotron.*reason", re.I)
_NO_REASONING_RE = re.compile(r"non-reasoning|gpt-5(\.\d)?-chat|instruct-2507", re.I)


def guess_reasoning(model_id: str) -> bool:
    return bool(_REASONING_RE.search(model_id)) and not _NO_REASONING_RE.search(model_id)


# ---- preview / experimental ----
_PREVIEW_RE = re.compile(r"preview|(^|[-_.])(exp|experimental|beta|alpha)($|[-_.\d])", re.I)


def is_preview(model_id: str) -> bool:
    return bool(_PREVIEW_RE.search(model_id))


def _natural(s: str):
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", s.lower())]


def sort_key(m):
    """Stable before preview; newest first (by `created`, else by version numbers in the name); then name."""
    created = m.created or 0
    nat = _natural(m.id)
    # invert numbers so higher versions sort first
    inv = [(a, -b, c) for a, b, c in nat]
    return (m.preview, -created, inv)
