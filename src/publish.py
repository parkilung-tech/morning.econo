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

    def publish_reel(self, video_path: str, caption: str, share_to_feed=False) -> str:
        """영상 파일을 직접 업로드(resumable)해서 릴스로 게시. 영상 공개 주소가 필요 없음."""
        c = self._post(
            f"{self.user_id}/media",
            media_type="REELS", upload_type="resumable", caption=caption,
            share_to_feed="true" if share_to_feed else "false",
        )
        size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            r = requests.post(c["uri"], headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(size),
            }, data=f, timeout=300)
        if not r.ok:
            raise RuntimeError(f"영상 업로드 오류 {r.status_code}: {r.text}")
        self._wait_ready(c["id"], tries=60)  # 영상은 인스타 쪽 처리에 1~3분 걸림
        res = self._post(f"{self.user_id}/media_publish", creation_id=c["id"])
        return res["id"]

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
