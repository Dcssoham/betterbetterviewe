from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import logging

app = Flask(__name__)

VIDEOS_PER_PAGE = 40

logging.basicConfig(level=logging.DEBUG)


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

    if not search_term:
        return jsonify({'results': []})

    results = fetch_videos(search_term, filter_type, page)
    return jsonify({'results': results})


def fetch_videos(search_term, filter_type, page):
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

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept-Language': 'en-US,en;q=0.9',
        'Viewport-Width': '1920'
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []

        return parse_videos(r.text)[:VIDEOS_PER_PAGE]

    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return []


def parse_videos(html):
    soup = BeautifulSoup(html, 'html.parser')
    boxes = soup.select('.videoBox')

    results = []
    seen = set()

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
            if video_id in seen:
                continue
            seen.add(video_id)

            results.append({
                'video_id': video_id,
                'video_url': 'https://www.pornhub.com' + link['href'],
                'title': img.get('alt', 'No title'),
                'thumbnail': img.get('data-src') or img.get('src', ''),
                'duration': box.select_one('.duration').get_text(strip=True) if box.select_one('.duration') else '',
                'views': box.select_one('.views').get_text(strip=True) if box.select_one('.views') else '',
                'rating': box.select_one('.rating-container .value').get_text(strip=True) if box.select_one('.rating-container .value') else ''
            })

        except Exception:
            continue

    return results


if __name__ == '__main__':
    app.run(debug=True)
