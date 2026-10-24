"""Instagram API (Instagram 로그인 방식)로 캐러셀 게시."""
import os
import time

import requests

HOST = "https://graph.instagram.com"


class Instagram:
    def __init__(self, version: str):
        self.token = os.environ["IG_ACCESS_TOKEN"]
        self.user_id = os.environ["IG_USER_ID"]
        self.base = f"{HOST}/{version}"

    def _post(self, path, **params):
        params["access_token"] = self.token
        r = requests.post(f"{self.base}/{path}", data=params, timeout=60)
        if not r.ok:
            raise RuntimeError(f"인스타 API 오류 {r.status_code}: {r.text}")
        return r.json()

    def _wait_ready(self, container_id, tries=30):
        for _ in range(tries):
            r = requests.get(
                f"{self.base}/{container_id}",
                params={"fields": "status_code", "access_token": self.token}, timeout=30,
            ).json()
            status = r.get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"컨테이너 처리 실패: {r}")
            time.sleep(5)
        raise TimeoutError("컨테이너 준비 시간 초과")

    def remaining_quota(self):
        r = requests.get(
            f"{self.base}/{self.user_id}/content_publishing_limit",
            params={"fields": "quota_usage,config", "access_token": self.token}, timeout=30,
        ).json()
        return r

    def publish_carousel(self, image_urls: list[str], caption: str) -> str:
        children = []
        for url in image_urls:
            c = self._post(f"{self.user_id}/media", image_url=url, is_carousel_item="true")
            children.append(c["id"])
        for cid in children:
            self._wait_ready(cid)
        parent = self._post(
            f"{self.user_id}/media",
            media_type="CAROUSEL", children=",".join(children), caption=caption,
        )
        self._wait_ready(parent["id"])
        res = self._post(f"{self.user_id}/media_publish", creation_id=parent["id"])
        return res["id"]
