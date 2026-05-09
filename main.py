import urllib.parse
import re
from playwright.sync_api import sync_playwright
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 频道配置 ====================
CHANNELS = [
    ("cctv1",  "CCTV-1",  "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=11200132825562653886"),
    ("cctv2",  "CCTV-2",  "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=12030532124776958103"),
    ("cctv4",  "CCTV-4",  "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=10620168294224708952"),
    ("cctv7",  "CCTV-7",  "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=8516529981177953694"),
    ("cctv9",  "CCTV-9",  "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=7252237247689203957"),
    ("cctv10", "CCTV-10", "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=14589146016461298119"),
    ("cctv12", "CCTV-12", "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=13180385922471124325"),
    ("cctv13", "CCTV-13", "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=16265686808730585228"),
    ("cctv17", "CCTV-17", "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=4496917190172866934"),
    ("cctv4k", "CCTV-4K", "https://m-live.cctvnews.cctv.com/live/landscape.html?liveRoomNumber=2127841942201075403"),
]

# 线程锁
lock = threading.Lock()

def safe_print(msg):
    with lock:
        print(msg)


def extract_resolution_from_url(url):
    """从URL中提取清晰度信息"""
    url_lower = url.lower()

    # 4K
    if any(x in url_lower for x in ['4k', '2160p', '2160', 'uhd']):
        return 2160, "4K"
    # 1080p
    if any(x in url_lower for x in ['1080p', '1080', 'fhd', '1920x1080']):
        return 1080, "1080p"
    # 720p
    if any(x in url_lower for x in ['720p', '720', 'hd', '1280x720']):
        return 720, "720p"
    # 480p
    if any(x in url_lower for x in ['480p', '480', 'sd', '854x480', '640x480']):
        return 480, "480p"
    # 360p
    if any(x in url_lower for x in ['360p', '360', '640x360']):
        return 360, "360p"
    # 270p/240p
    if any(x in url_lower for x in ['270p', '270', '240p', '240', '480x270']):
        return 270, "270p"

    # 从路径数字提取
    patterns = [r'[/._-](\d{3,4})p[/._-]?', r'[/._-](\d{3,4})[/._-]?', r'_(\d{3,4})_', r'[/](\d{3,4})[/]']
    for pattern in patterns:
        match = re.search(pattern, url_lower)
        if match:
            res_val = int(match.group(1))
            if res_val >= 2000: return 1080, "1080p"
            elif res_val >= 1000: return 720, "720p"
            elif res_val >= 600: return 480, "480p"
            elif res_val >= 400: return 360, "360p"
            else: return res_val, f"{res_val}p"

    return 1080, "1080p"


def extract_channel(name, display_name, url, max_wait=30):
    """抓取单个频道 m3u8"""
    m3u8_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            viewport={"width": 360, "height": 661},
            is_mobile=True
        )
        page = context.new_page()

        def handle_request(request):
            if ".m3u8" in request.url:
                safe_print(f"🔥 [{name}] 捕获 m3u8: {request.url}")
                m3u8_urls.add(request.url)

        page.on("request", handle_request)

        safe_print(f"[{name}] 正在访问页面...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            safe_print(f"❌ [{name}] 页面加载失败: {e}")
            browser.close()
            return name, display_name, []

        # 点击播放
        selectors = ["button.custom-prism-play-control", "#player button", "video"]
        clicked = False
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=8000)
                page.click(sel)
                safe_print(f"[{name}] 点击成功: {sel}")
                clicked = True
                break
            except:
                continue

        if not clicked:
            try:
                page.evaluate("const v = document.querySelector('video'); if (v) v.play();")
            except:
                pass

        # 等待 m3u8
        safe_print(f"[{name}] 等待 m3u8 请求... (最多 {max_wait}s)")
        start_time = time.time()
        while not m3u8_urls and time.time() - start_time < max_wait:
            time.sleep(0.5)

        browser.close()

    # 清理 URL
    results = []
    for m3u8 in m3u8_urls:
        new_m3u8 = urllib.parse.unquote(m3u8)
        # 清理多余参数
        new_m3u8 = re.sub(r'.*?(https://live-play-hls\.cctvnews\.cctv\.com.*?)(?:&stack.*)?$', r'\1', new_m3u8)
        results.append(new_m3u8)

    safe_print(f"✅ [{name}] 完成，找到 {len(results)} 个直播源")
    return name, display_name, results


def generate_m3u(results, filename="cctv_live.m3u"):
    """生成 M3U 文件 - 修复：每个URL单独一行，相同频道相同tvg-id/tvg-name"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("# Generated by CCTV Live Scraper\n\n")

        success_count = 0
        total_sources = 0

        # 按频道名称排序
        sorted_results = sorted(results, key=lambda x: x[0])

        for name, display_name, urls in sorted_results:
            if not urls:
                continue

            success_count += 1

            # 去重并按清晰度排序（高清晰度在前）
            unique_sources = []
            seen_urls = set()
            for url in urls:
                # 规范化URL用于去重
                norm_url = re.sub(r'\?auth_key=[^&]*', '', url)
                if norm_url not in seen_urls:
                    seen_urls.add(norm_url)
                    res_val, res_label = extract_resolution_from_url(url)
                    unique_sources.append((res_val, res_label, url))

            # 按清晰度降序排列
            unique_sources.sort(key=lambda x: x[0], reverse=True)

            for res_val, res_label, url in unique_sources:
                # 关键：所有源使用相同的 tvg-id 和 tvg-name，让播放器识别为同一频道的多个源
                f.write(f'#EXTINF:-1 tvg-id="{name}" tvg-name="{display_name}" group-title="CCTV",{display_name} ({res_label})\n')
                f.write(f"{url}\n\n")
                total_sources += 1

        f.write(f"# Total channels: {success_count}\n")
        f.write(f"# Total sources: {total_sources}\n")

    print(f"\n🎉 M3U 文件生成完成！共 {success_count} 个频道，{total_sources} 个源")
    print(f"📁 文件保存为: {filename}")


def run_all_channels(max_workers=5, max_wait=30):
    """主函数"""
    all_results = []
    total = len(CHANNELS)

    print(f"\n🚀 启动抓取，共 {total} 个频道，最大并发 {max_workers} 个线程...\n")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_channel, name, disp_name, url, max_wait): name 
            for name, disp_name, url in CHANNELS
        }

        for future in as_completed(futures):
            try:
                name, display_name, urls = future.result()
                all_results.append((name, display_name, urls))
            except Exception as e:
                safe_print(f"❌ 线程异常: {e}")

    # 生成 M3U 文件
    generate_m3u(all_results)

    # 控制台打印结果
    print("\n" + "=" * 70)
    print("📊 抓取结果汇总")
    print("=" * 70)
    for name, display_name, urls in sorted(all_results, key=lambda x: x[0]):
        status = "✅" if urls else "❌"
        print(f"{status} {display_name:12} → {len(urls)} 个直播源")
        if urls:
            for url in urls:
                _, label = extract_resolution_from_url(url)
                print(f"   [{label}] {url[:80]}...")

    return all_results


if __name__ == "__main__":
    MAX_WORKERS = 5      # 建议不要超过 5
    MAX_WAIT = 30        # 每个频道最大等待秒数

    results = run_all_channels(max_workers=MAX_WORKERS, max_wait=MAX_WAIT)
