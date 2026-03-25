# app.py (modified)
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import json
import logging

app = Flask(__name__)

VIDEOS_PER_PAGE = 40

logging.basicConfig(level=logging.DEBUG)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.pornhub.com/',
    'Viewport-Width': '1920'
}


@app.route('/', methods=['GET'])
def index():
    return render_template(
        'index.html',
        results=[],
        search_term='',
        filter_type='relevance',
        current_page=1
    )


@app.route('/load_more', methods=['POST'])
def load_more():
    data = request.get_json()
    search_term = data.get('search_term', '')
    filter_type = data.get('filter_type', 'relevance')
    page = int(data.get('page', 1))
    seen_ids = set(data.get('seen_ids', []))

    if not search_term:
        return jsonify({'results': []})

    results = fetch_videos(search_term, filter_type, page, seen_ids)
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
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []

        return parse_videos(r.text, seen_ids)[:VIDEOS_PER_PAGE]

    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return []


def parse_videos(html, seen_ids):
    soup = BeautifulSoup(html, 'html.parser')
    boxes = soup.select('.videoBox')

    results = []
    local_seen = set()

    for box in boxes:
        try:
            link = box.select_one('a[href*="viewkey"]')
            img = box.select_one('img')

            if not link or not img:
                continue

            match = re.search(r'viewkey=([^&]+)', link['href'])
            if not match:
                continue

            video_id = match.group(1)

            if video_id in seen_ids or video_id in local_seen:
                continue

            local_seen.add(video_id)

            results.append({
                'video_id': video_id,
                'video_url': 'https://www.pornhub.com' + link['href'],  # Keep for fallback
                'title': img.get('alt', 'No title'),
                'thumbnail': img.get('data-src') or img.get('src', ''),
                'duration': box.select_one('.duration').get_text(strip=True) if box.select_one('.duration') else '',
                'views': box.select_one('.views').get_text(strip=True) if box.select_one('.views') else '',
                'rating': box.select_one('.rating-container .value').get_text(strip=True) if box.select_one('.rating-container .value') else ''
            })

        except Exception:
            continue

    return results


def fetch_video_stream(video_id):
    url = f"https://www.pornhub.com/view_video.php?viewkey={video_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        # Parse for mediaDefinition JSON
        html = r.text
        match = re.search(r'"mediaDefinition"\s*:\s*(\[.*?\])\s*,?', html, re.DOTALL | re.IGNORECASE)
        if not match:
            return None

        media_defs = json.loads(match.group(1))

        # Prefer highest quality HLS
        hls_videos = [d for d in media_defs if d.get('format') == 'hls']
        if hls_videos:
            best = max(hls_videos, key=lambda x: x.get('quality', 0))
            return best.get('videoUrl')

        # Fallback to highest MP4
        mp4_videos = [d for d in media_defs if d.get('format') == 'mp4']
        if mp4_videos:
            best = max(mp4_videos, key=lambda x: x.get('quality', 0))
            return best.get('videoUrl')

        return None

    except Exception as e:
        logging.error(f"Stream fetch error for {video_id}: {e}")
        return None


if __name__ == '__main__':
    app.run(debug=True)
