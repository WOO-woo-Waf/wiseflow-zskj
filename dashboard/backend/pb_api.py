import os
from pocketbase import PocketBase  # Client also works the same
from pocketbase.client import FileUpload
from typing import BinaryIO, Optional, List, Dict
import requests
from pathlib import Path
from dotenv import load_dotenv

# 找到上层目录（例如上一级或两级，按实际调整）
ROOT = Path(__file__).resolve().parents[2]  
load_dotenv(ROOT / ".env", override=True)



class PbTalker:
    def __init__(self, logger) -> None:
        # 1. base initialization
        url = os.environ.get('PB_API_BASE', "http://127.0.0.1:8090")
        self.logger = logger
        self.logger.debug(f"initializing pocketbase client: {url}")
        self.client = PocketBase(url)
        auth = os.environ.get('PB_API_AUTH', '')
        if not auth or "|" not in auth:
            self.logger.warning("invalid email|password found, will handle with not auth, make sure you have set the collection rule by anyone")
        else:
            email, password = auth.split('|')
            self.logger.info(f"{email}|{password}")
            try:
                admin_data = self.admin_login_legacy(email, password)
                if admin_data:
                    self.logger.info(f"pocketbase ready authenticated as admin - {email}")
            except:
                user_data = self.client.collection("users").auth_with_password(email, password)
                if user_data:
                    self.logger.info(f"pocketbase ready authenticated as user - {email}")
                else:
                    raise Exception("pocketbase auth failed")

    def admin_login_legacy(self, email: str, password: str):
        """
        强制使用旧端点 /api/admins/auth-with-password 登录。
        成功后把 token 写入 self.client.auth_store，后续 SDK 调用自动带鉴权。
        """
        base = getattr(self.client, "base_url", "http://127.0.0.1:8090").rstrip("/")
        url = f"{base}/api/admins/auth-with-password"

        r = requests.post(url, json={"identity": email, "password": password}, timeout=10)
        # 旧端点存在但密码错会给 400/401/403；不存在（你其实是新版本 PB）会是 404
        r.raise_for_status()
        data = r.json()  # 形如 {"token": "...","admin": {...}}
        self.client.auth_store.save(data.get("token"), data.get("admin"))
        self.logger.info(f"pocketbase legacy-admin authenticated - {email}")
        return data

    def read(self, collection_name: str, fields: Optional[List[str]] = None, filter: str = '', skiptotal: bool = True) -> list:
        results = []
        for i in range(1, 10):
            try:
                res = self.client.collection(collection_name).get_list(i, 500,
                                                                       {"filter": filter,
                                                                        "fields": ','.join(fields) if fields else '',
                                                                        "skiptotal": skiptotal})

            except Exception as e:
                self.logger.error(f"pocketbase get list failed: {e}")
                continue
            if not res.items:
                break
            for _res in res.items:
                attributes = vars(_res)
                results.append(attributes)
        return results

    def add(self, collection_name: str, body: Dict) -> str:
        try:
            res = self.client.collection(collection_name).create(body)
        except Exception as e:
            self.logger.error(f"pocketbase create failed: {e}")
            return ''
        return res.id

    def update(self, collection_name: str, id: str, body: Dict) -> str:
        try:
            res = self.client.collection(collection_name).update(id, body)
        except Exception as e:
            self.logger.error(f"pocketbase update failed: {e}")
            return ''
        return res.id

    def delete(self, collection_name: str, id: str) -> bool:
        try:
            res = self.client.collection(collection_name).delete(id)
        except Exception as e:
            self.logger.error(f"pocketbase update failed: {e}")
            return False
        if res:
            return True
        return False

    def upload(self, collection_name: str, id: str, key: str, file_name: str, file: BinaryIO) -> str:
        try:
            res = self.client.collection(collection_name).update(id, {key: FileUpload((file_name, file))})
        except Exception as e:
            self.logger.error(f"pocketbase update failed: {e}")
            return ''
        return res.id

    def view(self, collection_name: str, item_id: str, fields: Optional[List[str]] = None) -> Dict:
        try:
            res = self.client.collection(collection_name).get_one(item_id, {"fields": ','.join(fields) if fields else ''})
            return vars(res)
        except Exception as e:
            self.logger.error(f"pocketbase view item failed: {e}")
            return {}
