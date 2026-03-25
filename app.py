# app.py (FIXED - Bulletproof video stream extraction)
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import json
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random

app = Flask(__name__)

VIDEOS_PER_PAGE = 40

logging.basicConfig(level=logging.DEBUG)

# Rotating User-Agents for better evasion
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
]

SEARCH_HEADERS = {
    'User-Agent': USER_AGENTS[0],
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Viewport-Width': '1920',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1'
}

VIDEO_HEADERS = {
    'User-Agent': USER_AGENTS[0],
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.pornhub.com/',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Viewport-Width': '1920',
    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"'
}

session = requests.Session()
retry_strategy = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504, 403])
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

def get_random_headers(base_headers):
    headers = base_headers.copy()
    headers['User-Agent'] = random.choice(USER_AGENTS)
    return headers

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
        return jsonify({'error': 'Video stream not found. Try another video or refresh.'})
    return jsonify({'stream_url': stream_url})

def fetch_videos(search_term, filter_type, page, seen_ids):
    search_term = search_term.replace(' ', '+')
    base_url = "https://www.pornhub.com/video/search?search="
    filter_map = {
        'most_viewed': '&o=mv',
        'top_rated': '&o=tr',
        'newest': '&o=cm',
        'longest': '&o=lg',
        'relevance': ''
    }
    filter_param = filter_map.get(filter_type, '')
    url = f"{base_url}{search_term}{filter_param}&page={page}"

    try:
        headers = get_random_headers(SEARCH_HEADERS)
        r = session.get(url, headers=headers, timeout=30)
        logging.debug(f"Search status: {r.status_code} for {url}")
        if r.status_code != 200:
            time.sleep(2)  # Rate limit backoff
            return []

        return parse_videos(r.text, seen_ids)[:VIDEOS_PER_PAGE]

    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return []

def parse_videos(html, seen_ids):
    soup = BeautifulSoup(html, 'html.parser')
    
    # Enhanced selectors with more fallbacks
    boxes = (
        soup.select('.pcVideoListItem') or
        soup.select('.videoBox') or
        soup.select('.thumbBox') or
        soup.select('[data-video-vkey]') or
        soup.find_all('div', class_=re.compile(r'(pcVideoListItem|videoBox|thumb.*|video.*list.*item)', re.I))
    )

    results = []
    local_seen = set(seen_ids)

    for box in boxes[:120]:  # Increased cap
        try:
            # More robust link extraction
            link = (
                box.select_one('a[href*="viewkey="], a[href*="view_video"]') or
                box.find('a', href=re.compile(r'viewkey=([^&?/]+)', re.I)) or
                box.find_parent('a', href=re.compile(r'viewkey=([^&?/]+)', re.I))
            )
            if not link or not link.get('href'):
                continue

            match = re.search(r'viewkey=([^&?/]+)', link['href'])
            if not match:
                continue

            video_id = match.group(1)

            if video_id in local_seen:
                continue
            local_seen.add(video_id)

            # Title from various sources
            title_el = box.select_one('p.title a, .title a, img[alt]')
            title = (title_el.get('title') or title_el.get_text(strip=True) or title_el.get('alt', 'No title'))[:120]

            img = box.select_one('img[data-src], img[data-srcset], img[src], img')
            thumb = (
                img.get('data-src') or
                img.get('data-lazy-src') or
                img.get('data-srcset', '').split(',')[0].split(' ')[0] or
                img.get('src', '')
            ) if img else ''

            duration_el = box.select_one('.duration, .videoDuration, time, [class*="duration"]')
            duration = duration_el.get_text(strip=True) if duration_el else ''

            views_el = box.select_one('.views, .videoViews, [class*="views"]')
            views = views_el.get_text(strip=True) if views_el else ''

            rating_el = box.select_one('.rating, [class*="rating"], [class*="score"]')
            rating = rating_el.get_text(strip=True) if rating_el else ''

            results.append({
                'video_id': video_id,
                'video_url': f"https://www.pornhub.com/view_video.php?viewkey={video_id}",
                'title': title,
                'thumbnail': thumb,
                'duration': duration,
                'views': views,
                'rating': rating
            })

        except Exception as e:
            logging.debug(f"Parse skip: {e}")
            continue

    return results

def fetch_video_stream(video_id):
    url = f"https://www.pornhub.com/view_video.php?viewkey={video_id}"
    try:
        headers = get_random_headers(VIDEO_HEADERS)
        r = session.get(url, headers=headers, timeout=30)
        logging.debug(f"Video page status: {r.status_code}")
        if r.status_code != 200:
            logging.error(f"Video page failed: {r.status_code}")
            return None

        html = r.text
        soup = BeautifulSoup(html, 'html.parser')
        scripts = soup.find_all('script')

        media_defs = None

        # Primary: Search in script tags for mediaDefinition
        for script in scripts:
            if not script.string or 'mediaDefinition' not in script.string:
                continue

            # Multiple robust patterns
            patterns = [
                r'"mediaDefinition"\s*:\s*(\[[\s\S]*?\])\s*[,\]\}\n]",
                r'mediaDefinition\s*:\s*(\[[\s\S]*?\])\s*[,\]\}\n"]',
                r'"mediaDefinition":\s*(\[[\s\S]*?\])\s*(?:,|\]|})',
                r'mediaDefinition:\s*(\[[\s\S]*?\])\s*(?:,|\]|})',
                r'playerConfig[^}]*?"mediaDefinition"[^}]*?(\[[\s\S]*?\])',
            ]
            for pat in patterns:
                match = re.search(pat, script.string, re.DOTALL | re.IGNORECASE)
                if match:
                    json_str = match.group(1).strip()
                    # Cleanup escaped chars and trailing commas
                    json_str = re.sub(r'\\u0026', '&', json_str)
                    json_str = re.sub(r',\s*]', ']', json_str)
                    json_str = re.sub(r',\s*}', '}', json_str)
                    try:
                        media_defs = json.loads(json_str)
                        logging.debug(f"Extracted media_defs with {len(media_defs)} qualities")
                        break
                    except json.JSONDecodeError as je:
                        logging.debug(f"JSON decode fail: {je}, trying next")
                        continue
            if media_defs:
                break

        # Fallback: Full page search
        if not media_defs:
            patterns = [
                r'"mediaDefinition"\s*:\s*(\[[\s\S]{100,50000}\])\s*(?:,|\]|})',
                r'window\.[^=]*=\s*\{[^}]*"mediaDefinition"[^}]*(\[[^\]]*\])'
            ]
            for pat in patterns:
                match = re.search(pat, html, re.DOTALL | re.IGNORECASE)
                if match:
                    try:
                        media_defs = json.loads(match.group(1))
                        break
                    except:
                        pass

        if not media_defs or not isinstance(media_defs, list):
            logging.error("No valid mediaDefinition found")
            return None

        # Prioritize HLS (highest quality supported)
        hls_videos = [d for d in media_defs 
                      if isinstance(d, dict) and 
                      d.get('format') in ['hls', 'hls-vod'] and 
                      d.get('videoUrl') and 
                      d.get('quality')]
        if hls_videos:
            best = max(hls_videos, key=lambda x: int(x.get('quality', 0)))
            stream_url = best.get('videoUrl')
            if stream_url.startswith('//'):
                stream_url = 'https:' + stream_url
            elif stream_url.startswith('/'):
                stream_url = 'https://www.pornhub.com' + stream_url
            logging.debug(f"Selected HLS: {best.get('quality')}p")
            return stream_url

        # Fallback to MP4
        mp4_videos = [d for d in media_defs 
                      if isinstance(d, dict) and 
                      d.get('format') == 'mp4' and 
                      d.get('videoUrl') and 
                      d.get('quality')]
        if mp4_videos:
            best = max(mp4_videos, key=lambda x: int(x.get('quality', 0)))
            stream_url = best.get('videoUrl')
            if stream_url.startswith('//'):
                stream_url = 'https:' + stream_url
            elif stream_url.startswith('/'):
                stream_url = 'https://www.pornhub.com' + stream_url
            logging.debug(f"Selected MP4: {best.get('quality')}p")
            return stream_url

        logging.error("No suitable streams found in media_defs")
        return None

    except Exception as e:
        logging.error(f"Full stream error for {video_id}: {str(e)[:200]}")
        return None

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)
