from workbench.config import setting

class ModelError(Exception):
    """A safe diagnostic; never includes provider messages or document text."""


def error_message(exc):
    if isinstance(exc, ModelError):
        return str(exc)
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    # Inspect only structured, allowlisted reasons; never render response bodies.
    details = getattr(exc, "details", None) or getattr(exc, "body", None)
    if isinstance(details, dict):
        error = details.get("error", details)
        if isinstance(error, dict):
            for item in error.get("details", []) or []:
                if isinstance(item, dict) and item.get("reason") in {"API_KEY_INVALID", "API_KEY_EXPIRED"}:
                    return "模型密钥无效或已失效，请管理员更新后台 API Key。（AI-KEY）"
            # Match known causes internally, without displaying any provider text.
            message = str(error.get("message", "")).lower()
            status = error.get("status", "")
            if code == 400:
                if any(x in message for x in ("user location is not supported", "free tier is not available in your country", "unsupported location")):
                    return "模型服务明确拒绝了当前账号或运行平台的地区，请检查模型平台的地区支持情况。（AI-REGION）"
                if status == "FAILED_PRECONDITION":
                    return "模型账户未满足调用前提，请检查该账号和模型的免费层资格、地区及服务启用状态。（AI-PRECONDITION）"
                if any(x in message for x in ("api key not valid", "api key expired")):
                    return "模型密钥无效或已失效，请管理员更新后台 API Key。（AI-KEY）"
                if any(x in message for x in ("response_schema", "responseschema", "response_json_schema", "responsejsonschema", "additionalproperties", "json_schema")):
                    return "模型拒绝了结构化报告格式，需检查所选模型的结构化输出兼容性。（AI-SCHEMA）"
    messages = {
        400: "模型拒绝了请求，请检查模型是否支持当前参数和结构化输出；也可能是账号地区或密钥限制。（AI-400）",
        401: "模型认证失败，请管理员检查 AI_PROVIDER 与对应 API Key 是否匹配。（AI-401）",
        402: "模型账户余额或计费条件不满足，请检查该模型是否有可用免费额度。（AI-402）",
        403: "模型访问被拒绝，请检查密钥权限、API 是否启用及账号或地区限制。（AI-403）",
        404: "模型或接口不存在，请管理员核对后台 MODEL 名称及账号是否可用。（AI-404）",
        408: "模型请求超时，请稍后重试。（AI-TIMEOUT）",
        413: "模型请求内容过大，请减少本次文档或图片数量。（AI-413）",
        429: "模型额度已用尽或调用过于频繁，请在模型平台查看免费额度与调用限制；稍后重试不一定能恢复。（AI-429）",
    }
    if code in messages:
        return messages[code]
    if code is not None and 500 <= code <= 599:
        return "模型服务暂时不可用，请稍后重试。（AI-SERVER）"
    import httpx
    from pydantic import ValidationError
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)) or type(exc).__name__ == "APITimeoutError":
        return "等待模型响应超时，请稍后重试。（AI-TIMEOUT）"
    if isinstance(exc, (httpx.TransportError, ConnectionError)) or type(exc).__name__ == "APIConnectionError":
        return "运行平台无法连接模型服务，请检查服务可用性和网络。（AI-NETWORK）"
    if isinstance(exc, (ValidationError, ValueError)):
        return "模型返回内容为空、不完整或不符合报告格式，请重试；持续出现时需检查模型兼容性。（AI-FORMAT）"
    return "模型处理发生未分类异常，需要进一步检查调用兼容性。（AI-UNKNOWN）"


class AI:
    def __init__(self, store, provider, model, key):
        self.store, self.provider, self.model, self.key = store, provider, model.strip(), key.strip()
        if provider not in ("openai", "gemini"):
            raise ValueError("AI_PROVIDER 仅支持 openai 或 gemini。")
        if not self.key or not self.model:
            raise ValueError("请先配置模型名称和 API 密钥。")

    def generate(self, system, prompt, schema, images=None):
        self.store.reserve_call()
        try:
            return self._generate(system, prompt, schema, images)
        except Exception as exc:
            raise ModelError(error_message(exc)) from None

    def _generate(self, system, prompt, schema, images=None):
        if self.provider == "openai":
            from openai import OpenAI
            content = [{"type":"input_text", "text":prompt}]
            if images:
                content += [{"type":"input_image", "image_url":f"data:{im['mime']};base64,{im['data']}"} for im in images]
            with OpenAI(api_key=self.key, timeout=120, max_retries=0) as client:
                result = client.responses.parse(model=self.model, instructions=system,
                                                input=[{"role":"user", "content":content}], text_format=schema)
                if result.output_parsed is None:
                    raise ValueError("模型未返回完整结果。")
                return result.output_parsed
        from google import genai
        from google.genai import types
        import base64
        content = [types.Part.from_text(text=prompt)]
        if images:
            content += [types.Part.from_bytes(data=base64.b64decode(im["data"]), mime_type=im["mime"]) for im in images]
        with genai.Client(api_key=self.key, http_options=types.HttpOptions(timeout=120000)) as client:
            result = client.models.generate_content(model=self.model, contents=content,
                config=types.GenerateContentConfig(system_instruction=system,
                    response_mime_type="application/json", response_json_schema=schema.model_json_schema()))
            if not result.text:
                raise ValueError("模型未返回可解析内容。")
            return schema.model_validate_json(result.text)


