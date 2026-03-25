# app.py (fixed & bulletproof)
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import json
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

VIDEOS_PER_PAGE = 40

logging.basicConfig(level=logging.DEBUG)

# Lite headers for search (matches original success)
SEARCH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Accept-Language': 'en-US,en;q=0.9',
    'Viewport-Width': '1920'
}

# Full headers for video pages (anti-detection)
VIDEO_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.pornhub.com/',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Viewport-Width': '1920',
    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"'
}

session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html', results=[], search_term='', filter_type='relevance', current_page=1)


@app.route('/load_more', methods=['POST'])
def load_more():
    data = request.get_json()
    search_term = data.get('search_term', '').strip()
    filter_type = data.get('filter_type', 'relevance')
    page = int(data.get('page', 1))
    seen_ids = set(data.get('seen_ids', []))

    if not search_term:
        return jsonify({'results': []})

    results = fetch_videos(search_term, filter_type, page, seen_ids)
    logging.debug(f"Loaded {len(results)} videos for page {page}")
    return jsonify({'results': results})


@app.route('/video/<video_id>')
def get_video(video_id):
    stream_url = fetch_video_stream(video_id)
    if not stream_url:
        return jsonify({'error': 'Video stream not found'})
    return jsonify({'stream_url': stream_url})


def fetch_videos(search_term, filter_type, page, seen_ids):
    search_term = search_term.replace(' ', '+')
    base_url = "https://www.pornhub.com/video/search?search="
    filter_map = {
        'most_viewed': '&o=mv',
        'top_rated': '&o=tr',
        'newest': '&o=cm',
        'longest': '&o=lg'
    }
    filter_param = filter_map.get(filter_type, '')
    url = f"{base_url}{search_term}{filter_param}&page={page}"

    try:
        r = session.get(url, headers=SEARCH_HEADERS, timeout=20)
        logging.debug(f"Search status: {r.status_code} for {url}")
        if r.status_code != 200:
            return []

        return parse_videos(r.text, seen_ids)[:VIDEOS_PER_PAGE]

    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return []


def parse_videos(html, seen_ids):
    soup = BeautifulSoup(html, 'html.parser')
    
    # Robust selectors: multiple fallbacks for video boxes
    boxes = (soup.select('.videoBox') or 
             soup.select('.pcVideoListItem') or 
             soup.select('[data-video-vkey]') or 
             soup.find_all('div', class_=re.compile(r'video.*box|thumb')))

    results = []
    local_seen = set()

    for box in boxes[:100]:  # Cap for perf
        try:
            # Flexible link grab
            link = (box.select_one('a[href*="viewkey"], a[href*="view_video"]') or 
                    box.find('a', href=re.compile(r'viewkey=([^&]+)')) or 
                    box.find_parent('a', href=re.compile(r'viewkey=([^&]+)')))
            if not link or not link.get('href'):
                continue

            match = re.search(r'viewkey=([^&?/]+)', link['href'])
            if not match:
                continue

            video_id = match.group(1)

            if video_id in seen_ids or video_id in local_seen:
                continue

            local_seen.add(video_id)

            img = box.select_one('img') or box.find('img')
            duration_el = box.select_one('.duration, .videoDuration, time')
            views_el = box.select_one('.views, .videoViews')
            rating_el = box.select_one('.rating, [class*="rating"]')

            results.append({
                'video_id': video_id,
                'video_url': f"https://www.pornhub.com/view_video.php?viewkey={video_id}",
                'title': (img.get('alt') or img.get('title') or 'No title')[:100],
                'thumbnail': img.get('data-src') or img.get('data-lazy-src') or img.get('src', '') if img else '',
                'duration': duration_el.get_text(strip=True) if duration_el else '',
                'views': views_el.get_text(strip=True) if views_el else '',
                'rating': rating_el.get_text(strip=True) if rating_el else ''
            })

        except Exception as e:
            logging.debug(f"Parse skip: {e}")
            continue

    return results


def fetch_video_stream(video_id):
    url = f"https://www.pornhub.com/view_video.php?viewkey={video_id}"
    try:
        r = session.get(url, headers=VIDEO_HEADERS, timeout=20)
        if r.status_code != 200:
            logging.error(f"Video page {r.status_code}")
            return None

        html = r.text

        # Robust mediaDefinition extraction (multiple patterns)
        patterns = [
            r'"mediaDefinition"\s*:\s*(\[.*?\])\s*(?:,|\}|")',
            r'"mediaDefinition":\s*(\[.*?\])\s*(?:,|\}|")',
            r'mediaDefinition\s*:\s*(\[.*?\])\s*(?:,|\}|")'
        ]
        match = None
        for pat in patterns:
            match = re.search(pat, html, re.DOTALL | re.IGNORECASE)
            if match:
                break

        if not match:
            logging.error("No mediaDefinition found")
            return None

        media_defs = json.loads(match.group(1))

        # HLS priority
        hls_videos = [d for d in media_defs if d.get('format') in ['hls', 'hls-vod']]
        if hls_videos:
            best = max(hls_videos, key=lambda x: int(x.get('quality', 0)))
            return best.get('videoUrl') or best.get('url')

        # MP4 fallback
        mp4_videos = [d for d in media_defs if d.get('format') == 'mp4']
        if mp4_videos:
            best = max(mp4_videos, key=lambda x: int(x.get('quality', 0)))
            return best.get('videoUrl') or best.get('url')

        return None

    except json.JSONDecodeError:
        logging.error("Invalid JSON in mediaDefinition")
    except Exception as e:
        logging.error(f"Stream error {video_id}: {e}")
    return None


if __name__ == '__main__':
    app.run(debug=True, port=5000)
