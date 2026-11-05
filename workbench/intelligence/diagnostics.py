"""Explicit, fixed-input Gemini probes. Never access uploaded files or persist results."""
import re
from urllib.parse import quote

import httpx

from workbench.intelligence.models import Report


def redact(value, key):
    text = str(value).replace(key, '[REDACTED]') if key else str(value)
    text = re.sub(r'https?://\S+', '[URL]', text)
    text = re.sub(r'AIza[\w-]+|sb_secret_[\w-]+|sk-[\w-]+', '[REDACTED]', text)
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    return text[:500]


def probe_gemini(store, model, key, transport=None):
    model, key = model.strip(), key.strip()
    if not model or not key:
        return [{'step': '配置', 'ok': False, 'detail': '后台缺少模型名称或密钥。'}]
    results = []
    with httpx.Client(timeout=httpx.Timeout(30, connect=8), transport=transport) as client:
        for structured in (False, True):
            step = '2. 完整报告格式测试' if structured else '1. 最小纯文字测试'
            prompt = ('这是固定连接测试，没有业务文档。输出报告 JSON：所有字符串填写未说明，requirements 填空数组。'
                      if structured else '这是固定连接测试。请只回复 OK。')
            payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}]}
            if structured:
                payload['generationConfig'] = {'responseMimeType': 'application/json',
                                               'responseJsonSchema': Report.model_json_schema()}
            store.reserve_call()
            try:
                response = client.post(
                    'https://generativelanguage.googleapis.com/v1beta/models/' + quote(model, safe='') + ':generateContent',
                    headers={'x-goog-api-key': key}, json=payload)
            except httpx.HTTPError:
                results.append({'step': step, 'ok': False, 'detail': '连接失败或超时，未取得 HTTP 响应。'})
                break
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.is_error:
                error = body.get('error', {}) if isinstance(body, dict) else {}
                error = error if isinstance(error, dict) else {}
                results.append({'step': step, 'ok': False, 'detail':
                    f"HTTP {response.status_code} | " + redact(error.get('status', ''), key) + ' | ' +
                    redact(error.get('message', '服务未返回可读取的错误说明。'), key)})
                break
            try:
                parts = body['candidates'][0]['content']['parts']
                text = ''.join(part.get('text', '') for part in parts if not part.get('thought'))
                if not text.strip(): raise ValueError('empty')
                if structured: Report.model_validate_json(text)
            except (KeyError, IndexError, TypeError, ValueError):
                results.append({'step': step, 'ok': False, 'detail':
                    f'HTTP {response.status_code}，但返回内容为空、被拦截或未通过格式校验。'})
                break
            results.append({'step': step, 'ok': True, 'detail': f'HTTP {response.status_code}，测试通过。'})
    return results
