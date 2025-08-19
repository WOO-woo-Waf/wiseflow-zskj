# pip install openai
import os
from openai import OpenAI

LLM_API_KEY="sk-Q0ZqPXrpTc3DCjgk1d6e3c3bAcBa4e86A696Ac9c9bCcA591"
LLM_API_BASE="https://one-api.maas.com.cn/v1/"
# 预先在系统里设置环境变量：OPENAI_API_KEY=你的密钥
client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)

# 列出你账号可用的所有模型
models = client.models.list()
print("=== Models you can use ===")
for m in models.data:
    print(m.id)