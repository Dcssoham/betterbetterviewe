from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import re
import json
import logging

app = Flask(__name__)

# Global variables for pagination
VIDEOS_PER_PAGE = 20

# Set up logging
logging.basicConfig(level=logging.DEBUG)  # Logs to console

@app.route('/', methods=['GET', 'POST'])
def index():
    results = []
    search_term = request.form.get('search_term', '')
    filter_type = request.form.get('filter_type', 'relevance')
    
    if request.method == 'POST' and search_term:
        results = fetch_videos(search_term, filter_type, page=1)
        logging.debug(f"Initial search results for term '{search_term}' and filter '{filter_type}': {len(results)} items")
    
    return render_template('index.html', results=results, search_term=search_term, 
                          filter_type=filter_type, current_page=1)

@app.route('/load_more', methods=['POST'])
def load_more():
    search_term = request.json.get('search_term', '')
    filter_type = request.json.get('filter_type', 'relevance')
    page = request.json.get('page', 1)
    
    if search_term:
        results = fetch_videos(search_term, filter_type, page)
        logging.debug(f"Load more results for term '{search_term}', filter '{filter_type}', page {page}: {len(results)} items")
        return jsonify({'results': results})
    return jsonify({'results': []})

@app.route('/get_video_source', methods=['POST'])
def get_video_source():
    video_url = request.json.get('video_url', '')
    if not video_url:
        logging.error("No URL provided in get_video_source")
        return jsonify({'error': 'No URL provided'}), 400
    
    video_source = fetch_video_source(video_url)
    if video_source:
        logging.debug(f"Video source fetched successfully for URL: {video_url}")
        return jsonify({'video_source': video_source})
    else:
        logging.error(f"Could not find video source for URL: {video_url}")
        return jsonify({'error': 'Could not find video source'}), 404

def fetch_videos(search_term, filter_type='relevance', page=1):
    formatted_search = search_term.replace(' ', '+')
    base_url = "https://www.pornhub.com/video/search?search="
    filter_params = ""
    
    if filter_type == 'most_viewed':
        filter_params = "&o=mv"
    elif filter_type == 'top_rated':
        filter_params = "&o=tr"
    elif filter_type == 'newest':
        filter_params = "&o=cm"
    elif filter_type == 'longest':
        filter_params = "&o=lg"
    
    page_param = f"&page={page}"
    url = f"{base_url}{formatted_search}{filter_params}{page_param}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            results = parse_videos(response.text)
            logging.debug(f"Parsed {len(results)} videos from page {page}")
            return results[:VIDEOS_PER_PAGE]  # Limit to per-page count
        else:
            logging.error(f"Failed to fetch page {page}: Status code {response.status_code}")
            return []
    except Exception as e:
        logging.error(f"Error in fetch_videos for page {page}: {str(e)}")
        return []

def parse_videos(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    video_elements = soup.select('.videoBox')
    
    results = []
    seen_video_ids = set()  # Avoid duplicates
    for video in video_elements:
        try:
            link_element = video.select_one('a')
            img_element = video.select_one('img')
            
            if link_element and img_element:
                video_url = "https://www.pornhub.com" + link_element['href'] if link_element.has_attr('href') else ""
                video_id = link_element['href'].split('=')[-1] if '=' in link_element['href'] else ""
                
                if video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video_id)
                
                title = img_element['alt'] if img_element.has_attr('alt') else "No title"
                thumbnail = img_element.get('data-src') or img_element.get('src') or ""
                duration = video.select_one('.duration').text.strip() if video.select_one('.duration') else "Unknown"
                views = video.select_one('.views').text.strip() if video.select_one('.views') else "Unknown"
                rating = video.select_one('.rating-container .value').text.strip() if video.select_one('.rating-container .value') else "N/A"
                is_hd = True if video.select_one('.hd-thumbnail') else False
                
                results.append({
                    "title": title,
                    "thumbnail": thumbnail,
                    "video_url": video_url,
                    "video_id": video_id,
                    "duration": duration,
                    "views": views,
                    "rating": rating,
                    "is_hd": is_hd
                })
        except Exception as e:
            logging.debug(f"Skipped video due to parsing error: {str(e)}")
            continue
    return results

def fetch_video_source(video_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        response = requests.get(video_url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            script_tags = soup.find_all("script")
            for script in script_tags:
                if script.string and "flashvars" in script.string:
                    match = re.search(r'"quality_[0-9]+p":"([^"]+)"', script.string)
                    if match:
                        return match.group(1).replace('\\', '')
            video_tags = soup.find_all("video")
            for video in video_tags:
                if video.get('src') and 'mp4' in video.get('src'):
                    return video.get('src')
                for source in video.find_all("source"):
                    if source.get('src') and 'mp4' in source.get('src'):
                        return source.get('src')
            video_data = re.search(r'var flashvars_\d+ = ({.*?});', response.text)
            if video_data:
                data = json.loads(video_data.group(1))
                for definition in data.get('mediaDefinitions', []):
                    if 'mp4' in definition.get('videoUrl', ''):
                        return definition.get('videoUrl')
        return None
    except Exception as e:
        logging.error(f"Error in fetch_video_source: {str(e)}")
        return None

if __name__ == '__main__':
    app.run(debug=True)
