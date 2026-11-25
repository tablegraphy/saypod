"""놓침 감시: 두 프로그램의 RSS 최신 방송이 라이브 사이트에 있는지 본다.
없으면(공개된 지 4분 넘게) 사이트 갱신을 다시 돌리고, 그래도 안 되면 실패로 끝나 깃허브가 메일로 알려 준다.
표준 라이브러리만 쓴다. 환경변수 DRY=1 이면 갱신을 돌리지 않고 결과만 출력한다."""
import json, os, subprocess, sys, time, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

SITE = "https://saypod.saysiot.com/"
GRACE = 4 * 60      # 공개 직후 4분은 정상 갱신에 맡긴다
RETRIES = 4         # 갱신을 다시 돌린 뒤 확인하는 횟수
WAIT = 90           # 확인 사이 간격(초)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dtn-watchdog", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=30).read()


def newest(rss):
    ch = ET.fromstring(get(rss)).find("channel")
    best = None
    for it in ch.findall("item"):
        t = parsedate_to_datetime(it.findtext("pubDate"))
        if best is None or t > best[0]:
            best = (t, (it.findtext("title") or "").strip())
    return best


def missing():
    """사이트에 없는 최신 방송 목록을 돌려준다."""
    page = get(SITE + "?w=%d" % time.time()).decode("utf-8", "replace")
    out = []
    for ch in json.load(open("channels.json", encoding="utf-8"))["channels"]:
        t, title = newest(ch["rss"])
        age = (datetime.now(timezone.utc) - t).total_seconds()
        needle = json.dumps(title, ensure_ascii=False)[1:-1]
        ok = needle in page
        print(f"[{ch['id']}] 최신 '{title}' 공개 {int(age // 60)}분 전, 사이트에 {'있음' if ok else '없음'}")
        if not ok and age > GRACE:
            out.append(f"{ch['id']}: {title}")
    return out


def main():
    lost = missing()
    if not lost:
        print("정상")
        return 0
    print("놓친 방송:", lost)
    if os.environ.get("DRY") == "1":
        return 1
    for i in range(RETRIES):
        subprocess.run(["gh", "workflow", "run", "update-site.yml", "--repo", os.environ["GITHUB_REPOSITORY"]], check=False)
        time.sleep(WAIT * 2)
        lost = missing()
        if not lost:
            print("다시 올려서 정상으로 돌아옴")
            return 0
    print("다시 올려도 반영되지 않음:", lost)
    return 1


if __name__ == "__main__":
    sys.exit(main())
