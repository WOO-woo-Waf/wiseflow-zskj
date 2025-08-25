import os
from openai import OpenAI
from openai import RateLimitError
import time
from pathlib import Path
from dotenv import load_dotenv

# 找到上层目录（例如上一级或两级，按实际调整）
ROOT = Path(__file__).resolve().parents[2]  
load_dotenv(ROOT / ".env", override=True)

base_url = os.environ.get('LLM_API_BASE', "")
token = os.environ.get('LLM_API_KEY', "")



if not base_url and not token:
    raise ValueError("LLM_API_BASE or LLM_API_KEY must be set")
elif base_url and not token:
    client = OpenAI(base_url=base_url)
elif not base_url and token:
    client = OpenAI(api_key=token)
else:
    client = OpenAI(api_key=token, base_url=base_url)

# 放在 openai_llm 文件顶部或函数内均可
def _read_usage_total(usage) -> int:
    """
    兼容 OpenAI SDK 的 dict 或对象（CompletionUsage）两种形态
    返回 total_tokens；若为空则用 prompt+completion 求和
    """
    if not usage:
        return 0

    def _read(name: str) -> int:
        try:
            # dict 形态
            if isinstance(usage, dict):
                return int(usage.get(name, 0) or 0)
            # 对象形态
            return int(getattr(usage, name, 0) or 0)
        except Exception:
            return 0

    total = _read("total_tokens")
    if total:
        return total
    return _read("prompt_tokens") + _read("completion_tokens")



def log_tokens(model: str, purpose: str, total_tokens: int):
    """
    写一条消费记录到 PB.tokens_consume
    """
    from insights.get_info import pb  
    body = {
        "model": model,
        "purpose": purpose,
        "total_tokens": int(total_tokens or 0),
    }
    try:
        rec_id = pb.add(collection_name="tokens_consume", body=body)
        return rec_id
    except Exception as e:
        print(f"[tokens_consume] write failed: {e}")
        return None


def openai_llm(messages: list, model: str, logger=None, **kwargs) -> str:
    if logger:
        logger.debug(f'messages:\n {messages}')
        logger.debug(f'model: {model}')
        logger.debug(f'kwargs:\n {kwargs}')

    try:
        response = client.chat.completions.create(messages=messages, model=model, **kwargs)
    except RateLimitError as e:
        logger.warning(f'{e}\nRetrying in 60 second...')
        time.sleep(60)
        response = client.chat.completions.create(messages=messages, model=model, **kwargs)
        if 'choices' not in response:
            logger.warning(f'openai_llm warning: {response}')
            return ""
    except Exception as e:
        if logger:
            logger.error(f'openai_llm error: {e}')
        return ''

    if logger:
        logger.debug(f'result:\n {response.choices[0]}')
        logger.debug(f'usage:\n {response.usage}')
    
    usage = getattr(response, "usage", None)
    total = _read_usage_total(usage)
    log_tokens(model=model, purpose="文本摘要/处理", total_tokens=total)


    return response.choices[0].message.content
