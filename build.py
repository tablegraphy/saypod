"""channels.json 의 RSS를 읽어 에피소드 목록을 만들고 template.html 에 넣어 듣는사이.html 을 만든다.

실행: uv run python -I build.py   (또는 python3 -I build.py)
- RSS를 못 받으면 rss_cache/ 에 저장해 둔 이전 파일을 쓴다.
- 표지 이미지는 160px로 줄여 페이지에 직접 넣는다(발행된 페이지는 바깥 이미지를 못 불러온다).
- 두 가지를 만든다: 듣는사이.html(claude.ai 시제품), site/index.html(자체 사이트, 음원 직접 재생).
- 깃허브 자동 갱신용: python build.py --site-only --out _site  (시제품 파일은 만들지 않고 지정한 폴더에 index.html만 만든다).
- 표지는 cache/cover_<채널id>.json 에 한 번 저장해 두고 재사용한다(깃허브 서버에는 sips가 없다).
"""
import base64, datetime, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request
import xml.etree.ElementTree as ET
KST = datetime.timezone(datetime.timedelta(hours=9))   # 한국 표준시(서머타임 없음)
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
CACHE = os.path.join(HERE, "rss_cache")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dtn-build"})
    return urllib.request.urlopen(req, timeout=30).read()


def get_rss(ch):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, ch["id"] + ".xml")
    try:
        data = fetch(ch["rss"])
        open(path, "wb").write(data)
    except Exception as e:
        if not os.path.exists(path):
            raise
        print(f"[{ch['id']}] RSS를 못 받아 저장해 둔 파일을 씁니다: {e}", file=sys.stderr)
        data = open(path, "rb").read()
    return ET.fromstring(data).find("channel")


def seconds(s):
    if not s:
        return 0
    p = [int(x) for x in s.split(":")]
    t = 0
    for x in p:
        t = t * 60 + x
    return t


def ep_number(it, title):
    n = it.findtext("itunes:episode", namespaces=NS)
    if n and n.isdigit():
        return int(n)
    m = re.search(r"(?:Ep\s*|\[)(\d+)", title, re.I)
    return int(m.group(1)) if m else 0


def cover_jpeg_bytes(url, size=160, quality=70):
    """주소의 이미지를 받아 긴 변이 size 인 JPEG 바이트로 줄인다. 실패하면 빈 바이트."""
    if not url:
        return b""
    try:
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "src.img"), os.path.join(d, "out.jpg")
            open(src, "wb").write(fetch(url))
            if shutil.which("sips"):   # 맥
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality),
                                "-Z", str(size), src, "--out", dst],
                               check=True, capture_output=True)
            else:                      # 깃허브 서버(리눅스): Pillow
                from PIL import Image
                im = Image.open(src).convert("RGB")
                im.thumbnail((size, size))
                im.save(dst, "JPEG", quality=quality)
            return open(dst, "rb").read()
    except Exception as e:
        print(f"표지 이미지를 만들지 못했습니다: {e}", file=sys.stderr)
        return b""


def cover_data_uri(url, size=160):
    b = cover_jpeg_bytes(url, size, 70)
    return "data:image/jpeg;base64," + base64.b64encode(b).decode() if b else ""


def cover_big_cached(ch_id, url, size=720):
    """스토리 공유 이미지용 선명한 표지(720px JPEG 파일). 사이트 안(같은 주소)에 두고 공유할 때 읽는다.
    표지 주소가 그대로면 저장해 둔 파일(cache/cover720_<채널>.jpg)을 쓰고, 바뀌었으면 새로 만든다. 못 만들면 이전 파일을 그대로 쓴다."""
    jpg = os.path.join(HERE, "cache", "cover%d_%s.jpg" % (size, ch_id))
    meta = jpg[:-4] + ".json"
    saved = json.load(open(meta, encoding="utf-8")) if os.path.exists(meta) else {}
    if os.path.exists(jpg) and saved.get("url") == url:
        return jpg
    b = cover_jpeg_bytes(url, size, 85)
    if b:
        os.makedirs(os.path.dirname(jpg), exist_ok=True)
        open(jpg, "wb").write(b)
        json.dump({"url": url}, open(meta, "w", encoding="utf-8"))
        return jpg
    return jpg if os.path.exists(jpg) else ""


def cover_cached(ch_id, url):
    """표지 주소가 그대로면 저장해 둔 이미지를 쓰고, 바뀌었으면 새로 만들어(sips 필요) 저장한다."""
    path = os.path.join(HERE, "cache", "cover_%s.json" % ch_id)
    saved = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    if saved.get("data") and saved.get("url") == url:
        return saved["data"]
    data = cover_data_uri(url)
    if data:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump({"url": url, "data": data}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        return data
    return saved.get("data", "")   # 새로 못 만들면 이전 표지를 그대로 쓴다


def thumb_cached(url):
    """RSS 에피소드 이미지를 160px로 줄여 저장해 두고 재사용한다(주소가 같으면 다시 만들지 않음)."""
    import hashlib
    path = os.path.join(HERE, "cache", "thumb_%s.json" % hashlib.sha1(url.encode()).hexdigest()[:12])
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8")).get("data", "")
    data = cover_data_uri(url)
    if data:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump({"url": url, "data": data}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return data


YT_NS = {"a": "http://www.w3.org/2005/Atom", "y": "http://www.youtube.com/xml/schemas/2015"}


def title_number(title):
    m = re.search(r"(?:Ep\s*|\[)(\d+)", title, re.I)
    return int(m.group(1)) if m else None


def youtube_feed(ch):
    """유튜브 재생목록의 공개 피드(최신 15편)를 [(영상id, 제목, 날짜)]로 돌려준다."""
    pl = ch.get("youtubePlaylist")
    if not pl:
        return []
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"yt_{ch['id']}.xml")
    try:
        data = fetch(f"https://www.youtube.com/feeds/videos.xml?playlist_id={pl}")
        open(path, "wb").write(data)
    except Exception as e:
        if not os.path.exists(path):
            print(f"[{ch['id']}] 유튜브 재생목록을 못 읽었습니다: {e}", file=sys.stderr)
            return []
        print(f"[{ch['id']}] 유튜브 피드를 못 받아 저장해 둔 파일을 씁니다: {e}", file=sys.stderr)
        data = open(path, "rb").read()
    return [(e.findtext("y:videoId", namespaces=YT_NS), (e.findtext("a:title", namespaces=YT_NS) or "").strip(),
             (e.findtext("a:published", namespaces=YT_NS) or "")[:10])
            for e in ET.fromstring(data).findall("a:entry", YT_NS)]


def link_youtube(ch, eps):
    by_title = {e["title"]: e for e in eps}
    auto = []
    for vid, vt, vd in youtube_feed(ch):
        e = by_title.get(vt)
        if e is None:
            n = title_number(vt)
            cands = [x for x in eps if n is not None and x["n"] == n and vd and
                     abs((datetime.date.fromisoformat(x["date"]) - datetime.date.fromisoformat(vd)).days) <= 3]
            e = cands[0] if len(cands) == 1 else None
        if e is None:
            print(f"[{ch['id']}] 유튜브 영상을 에피소드와 맞추지 못했습니다: {vt}", file=sys.stderr)
            continue
        if "youtube" in e.get("links", {}):
            continue  # 직접 적은 주소가 우선
        e.setdefault("links", {})["youtube"] = f"https://youtu.be/{vid}"
        auto.append(e["n"])
    if auto:
        print(f"[{ch['id']}] 유튜브 영상 자동 연결: {sorted(auto)}")


def build_channel(ch):
    r = get_rss(ch)
    img = r.find("itunes:image", NS)
    eps, seen = [], set()
    for it in r.findall("item"):
        title = (it.findtext("title") or "").strip()
        n = ep_number(it, title)
        if n in seen:
            raise SystemExit(f"[{ch['id']}] 에피소드 번호 {n} 이 겹칩니다: {title}")
        seen.add(n)
        e = {
            "n": n,
            "title": title,
            "date": parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).strftime("%Y-%m-%d"),   # RSS 시각은 GMT → 한국시간 날짜
            "sec": seconds(it.findtext("itunes:duration", namespaces=NS)),
            "audio": (it.find("enclosure").get("url") if it.find("enclosure") is not None else ""),
            "_img": (it.find("itunes:image", NS).get("href") if it.find("itunes:image", NS) is not None else ""),
        }
        extra = {k: v for k, v in ch.get("episodeLinks", {}).get(str(n), {}).items() if v}
        if extra:
            e["links"] = extra
        eps.append(e)
    unknown = set(ch.get("episodeLinks", {})) - {str(e["n"]) for e in eps}
    assert not unknown, f"[{ch['id']}] episodeLinks에 없는 에피소드 번호: {unknown}"
    link_youtube(ch, eps)
    ch_img = img.get("href") if img is not None else ""
    for e in eps:   # 방송 이미지는 RSS의 것. 채널 대표 이미지와 같으면 채널 표지를 그대로 쓴다.
        u = e.pop("_img", "")
        if u and u != ch_img:
            t = thumb_cached(u)
            if t:
                e["thumb"] = t
    eps.sort(key=lambda e: e["date"] + "%05d" % e["n"], reverse=True)
    links = {k: v for k, v in ch.get("links", {}).items() if v}
    return {
        "id": ch["id"], "name": ch["name"], "tagline": ch.get("tagline", ""), "home": ch.get("home") or {},   # 홈 패널용(배경색·진행자 줄)
        "links": links,
        "cover": cover_cached(ch["id"], img.get("href") if img is not None else ""),
        "_big": cover_big_cached(ch["id"], img.get("href") if img is not None else ""),   # 파일 경로, 화면 데이터에서는 빼고 site/cover-<id>.jpg 로 복사
        "episodes": eps,
    }


SITE_HEAD = (
    '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '<meta name="referrer" content="no-referrer">\n'
    '<meta name="apple-mobile-web-app-title" content="듣는 사이">\n'
    '<meta name="theme-color" content="#FAFAF9">\n'
    # 링크 미리보기(카카오톡·슬랙·인스타 DM 등에 주소를 붙였을 때 뜨는 제목·설명·그림). 그림은 og-image.jpg(1200x630)
    '<meta name="description" content="함께 듣고, 서로 이어지는">\n'
    '<meta property="og:type" content="website">\n'
    '<meta property="og:site_name" content="듣는 사이">\n'
    '<meta property="og:title" content="듣는 사이">\n'
    '<meta property="og:description" content="함께 듣고, 서로 이어지는">\n'
    '<meta property="og:url" content="https://saypod.saysiot.com/">\n'
    '<meta property="og:image" content="https://saypod.saysiot.com/og-image.jpg">\n'
    '<meta property="og:image:width" content="1200">\n'
    '<meta property="og:image:height" content="630">\n'
    '<meta name="twitter:card" content="summary_large_image">\n'
    '<link rel="apple-touch-icon" href="icon-180.png">\n'
    '<link rel="icon" href="icon-180.png">\n'
    '<style>:root{color-scheme:light;padding-top:var(--st,env(safe-area-inset-top,0px));padding-bottom:env(safe-area-inset-bottom,0px)}'
    'body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>\n'
)


def dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main():
    cfg = json.load(open(os.path.join(HERE, "channels.json"), encoding="utf-8"))
    ids = [c["id"] for c in cfg["channels"]]
    assert len(ids) == len(set(ids)), "채널 id가 겹칩니다"
    for i in ids:
        assert re.fullmatch(r"[a-z0-9]+", i), f"id는 영문 소문자와 숫자만: {i}"
    site_only = "--site-only" in sys.argv
    out_dir = os.path.join(HERE, "site")
    if "--out" in sys.argv:
        out_dir = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
    channels = [build_channel(c) for c in cfg["channels"]]
    for c in channels:   # 비어 있는 결과를 올리지 않도록(RSS 오류 등) 멈춘다
        assert c["episodes"], "[%s] 에피소드가 하나도 없습니다" % c["id"]
    big = {}
    for c in channels:   # 스토리 공유용 선명한 표지: 화면 데이터에는 파일 이름만 넣고, 파일은 사이트 폴더에 둔다
        path = c.pop("_big", "")
        if path:
            big[c["id"]] = path
            c["coverBig"] = "cover-%s.jpg" % c["id"]
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    assert "/*__DATA__*/null" in tpl

    # 1) claude.ai 시제품: 음원 주소는 넣지 않는다(바깥 음원은 막혀 있음)
    art = {"channels": [dict(c, episodes=[{k: v for k, v in e.items() if k not in ("audio", "thumb")} for e in c["episodes"]]) for c in channels]}
    out = tpl.replace("/*__DATA__*/null", dump(art))
    if not site_only:
        open(os.path.join(HERE, "듣는사이.html"), "w", encoding="utf-8").write(out)

    # 2) 자체 사이트(site/index.html): 음원 주소를 넣고 사이트 안 재생을 켠다
    cfg_path = os.path.join(HERE, "config.json")
    sbcfg = json.load(open(cfg_path, encoding="utf-8")).get("supabase") if os.path.exists(cfg_path) else None
    site_data = {"site": True, "channels": channels}
    priv_path = os.path.join(HERE, "privacy.json")
    if os.path.exists(priv_path):
        site_data["privacy"] = json.load(open(priv_path, encoding="utf-8"))
    head = SITE_HEAD
    if sbcfg:
        site_data["supabase"] = {"url": sbcfg["url"], "key": sbcfg["key"]}
        head += ('<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@%s/dist/umd/supabase.js" integrity="%s" crossorigin="anonymous"></script>\n'
                 % (sbcfg["jsVersion"], sbcfg["jsSri"]))
    site = tpl.replace("/*__DATA__*/null", dump(site_data))
    os.makedirs(out_dir, exist_ok=True)
    for cid, path in big.items():
        shutil.copyfile(path, os.path.join(out_dir, "cover-%s.jpg" % cid))
    og = os.path.join(HERE, "og-image.jpg")   # 링크 미리보기 그림
    if os.path.exists(og):
        shutil.copyfile(og, os.path.join(out_dir, "og-image.jpg"))
    page = head + site + "\n</html>\n"
    # 새 버전 알림용 버전표: 화면 내용의 해시를 화면(BUILD_ID)과 version.txt 에 같이 적는다(화면이 달라지면 값도 달라짐)
    build_id = hashlib.sha1(page.encode("utf-8")).hexdigest()[:10]
    page = page.replace("__BUILD_ID__", build_id)
    open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(page)
    open(os.path.join(out_dir, "version.txt"), "w", encoding="utf-8").write(build_id + "\n")

    for c in channels:
        print(f"{c['name']}: 에피소드 {len(c['episodes'])}개, 표지 {'있음' if c['cover'] else '없음'}")
    print(f"듣는사이.html {len(out.encode('utf-8')) // 1024}KB{'(만들지 않음)' if site_only else ''}, {os.path.join(out_dir, 'index.html')} {(len(head + site) + 9) // 1024}KB")


if __name__ == "__main__":
    main()
