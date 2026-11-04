from workbench.config import setting

def error_message(exc):
    # Do not expose provider response bodies or credentials in the UI / persistent log.
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in (401, 403):
        return "模型认证或访问失败，请检查密钥及模型权限。"
    if code == 429:
        return "模型额度不足或请求过于频繁，请联系管理员检查后台配置和额度。"
    if isinstance(exc, ValueError):
        return "处理未完成：配置、文档或模型返回内容未通过校验，请检查设置后重试。"
    return "模型连接或处理失败，可能是网络、服务暂时不可用或返回内容不完整。请稍后重试。"


class AI:
    def __init__(self, store, provider, model, key):
        self.store, self.provider, self.model, self.key = store, provider, model.strip(), key.strip()
        if provider not in ("openai", "gemini"):
            raise ValueError("AI_PROVIDER 仅支持 openai 或 gemini。")
        if not self.key or not self.model:
            raise ValueError("请先配置模型名称和 API 密钥。")

    def generate(self, system, prompt, schema, images=None):
        self.store.reserve_call()
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
                    response_mime_type="application/json", response_schema=schema))
            return schema.model_validate_json(result.text)


