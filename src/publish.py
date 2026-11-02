"""Instagram API (Instagram 로그인 방식)로 캐러셀 게시."""
import os
import time
from datetime import datetime, timezone

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

    def _publish(self, creation_id, caption: str) -> str:
        """최종 게시. 인스타가 오류를 돌려줘도 실제로는 올라가는 경우가 있어서,
        오류가 나면 최근 게시물을 확인해 같은 글이 방금 올라갔으면 성공으로 처리."""
        try:
            return self._post(f"{self.user_id}/media_publish", creation_id=creation_id)["id"]
        except RuntimeError as err:
            print(f"게시 요청 오류, 실제로 올라갔는지 확인 중: {err}")
            for _ in range(3):
                time.sleep(20)
                found = self._find_recent(caption)
                if found:
                    print(f"오류 응답이었지만 실제로 게시됨: {found}")
                    return found
            raise

    def _find_recent(self, caption: str, within_min=20):
        """방금(within_min분 이내) 올라간 게시물 중 캡션 앞부분이 같은 것의 id."""
        try:
            r = requests.get(
                f"{self.base}/{self.user_id}/media",
                params={"fields": "id,caption,timestamp", "limit": 5, "access_token": self.token},
                timeout=30,
            ).json()
        except requests.RequestException:
            return None
        head = (caption or "").strip()[:40]
        now = datetime.now(timezone.utc)
        for m in r.get("data", []):
            ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            if (now - ts).total_seconds() > within_min * 60:
                continue
            if (m.get("caption") or "").strip()[:40] == head:
                return m["id"]
        return None

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

    def publish_reel(self, video_url: str, caption: str, share_to_feed=False, thumb_offset_ms=1600) -> str:
        """공개 영상 주소로 릴스 게시 (Instagram 로그인 방식은 video_url이 필수).
        thumb_offset_ms: 표지로 쓸 장면 위치. 훅 질문·답이 다 나온 1.6초 지점."""
        c = self._post(
            f"{self.user_id}/media",
            media_type="REELS", video_url=video_url, caption=caption,
            share_to_feed="true" if share_to_feed else "false",
            thumb_offset=str(thumb_offset_ms),
        )
        self._wait_ready(c["id"], tries=60)  # 영상은 인스타 쪽 처리에 1~3분 걸림
        return self._publish(c["id"], caption)

    def publish_image(self, image_url: str, caption: str) -> str:
        """사진 한 장 게시."""
        c = self._post(f"{self.user_id}/media", image_url=image_url, caption=caption)
        self._wait_ready(c["id"])
        return self._publish(c["id"], caption)

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
        return self._publish(parent["id"], caption)
