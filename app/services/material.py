import os
import random
import threading
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils
from app.services import semantic_video

_requested_count = 0
_requested_count_lock = threading.Lock()


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _requested_count
    with _requested_count_lock:
        _requested_count += 1
        return api_keys[_requested_count % len(api_keys)]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)),
    reraise=True,
)
def _http_get(url, **kwargs):
    return requests.get(url, **kwargs)


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL with occasional page rotation for fresh clips
    page = random.choice([1, 1, 2])
    params = {"query": search_term, "per_page": 20, "page": page, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos (pexels p.{page}): {query_url}, with proxies: {config.proxy}")

    try:
        r = _http_get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    
                    # Capture image data for similarity comparison
                    if "image" in v:
                        item.thumbnail_url = v["image"]
                    
                    if "video_pictures" in v:
                        item.preview_images = [pic["picture"] for pic in v["video_pictures"]]
                    
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL with occasional page rotation for fresh clips
    page = random.choice([1, 1, 2])
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "page": page,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos (pixabay p.{page}): {query_url}, with proxies: {config.proxy}")

    try:
        r = _http_get(
            query_url, proxies=config.proxy, timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    if "thumbnail" in video:
                        item.thumbnail_url = video["thumbnail"]
                    elif "picture_id" in v:
                        item.thumbnail_url = f"https://i.vimeocdn.com/video/{v['picture_id']}_640x360.jpg"
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_combined(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """Search across both Pexels and Pixabay providers for maximum footage variety."""
    items = []
    # 1. Search Pexels
    try:
        if config.app.get("pexels_api_keys"):
            pex_items = search_videos_pexels(search_term, minimum_duration, video_aspect)
            items.extend(pex_items)
            logger.info(f"Pexels found {len(pex_items)} clips for '{search_term}'")
    except Exception as e:
        logger.warning(f"Pexels search failed for '{search_term}': {e}")

    # 2. Search Pixabay
    try:
        if config.app.get("pixabay_api_keys"):
            pix_items = search_videos_pixabay(search_term, minimum_duration, video_aspect)
            items.extend(pix_items)
            logger.info(f"Pixabay found {len(pix_items)} clips for '{search_term}'")
    except Exception as e:
        logger.warning(f"Pixabay search failed for '{search_term}': {e}")

    return items


def search_images_pexels(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """Search stock photos from Pexels."""
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    page = random.choice([1, 1, 2])
    params = {"query": search_term, "per_page": 20, "page": page, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/v1/search?{urlencode(params)}"
    logger.info(f"searching images (pexels p.{page}): {query_url}")
    try:
        r = _http_get(query_url, headers=headers, proxies=config.proxy, timeout=(15, 30))
        response = r.json()
        items = []
        photos = response.get("photos", [])
        for p in photos:
            src = p.get("src", {})
            img_url = src.get("large2x") or src.get("large") or src.get("original")
            if img_url:
                item = MaterialInfo()
                item.provider = "pexels_image"
                item.url = img_url
                item.duration = 1.3  # Max 1.3s per user requirement
                item.thumbnail_url = src.get("tiny") or img_url
                item.search_term = search_term
                items.append(item)
        return items
    except Exception as e:
        logger.warning(f"search images pexels failed for '{search_term}': {e}")
        return []


def search_images_pixabay(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """Search stock photos from Pixabay."""
    aspect = VideoAspect(video_aspect)
    orientation = "horizontal" if aspect.name == "landscape" else "vertical"
    api_key = get_api_key("pixabay_api_keys")
    page = random.choice([1, 1, 2])
    params = {
        "key": api_key,
        "q": search_term,
        "image_type": "photo",
        "orientation": orientation,
        "per_page": 30,
        "page": page,
    }
    query_url = f"https://pixabay.com/api/?{urlencode(params)}"
    logger.info(f"searching images (pixabay p.{page}): {query_url}")
    try:
        r = _http_get(query_url, proxies=config.proxy, timeout=(15, 30))
        response = r.json()
        items = []
        hits = response.get("hits", [])
        for h in hits:
            img_url = h.get("largeImageURL") or h.get("webformatURL")
            if img_url:
                item = MaterialInfo()
                item.provider = "pixabay_image"
                item.url = img_url
                item.duration = 1.3  # Max 1.3s per user requirement
                item.thumbnail_url = h.get("previewURL") or img_url
                item.search_term = search_term
                items.append(item)
        return items
    except Exception as e:
        logger.warning(f"search images pixabay failed for '{search_term}': {e}")
        return []


def search_images_combined(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """Search photos across both Pexels and Pixabay providers."""
    items = []
    if config.app.get("pexels_api_keys"):
        items.extend(search_images_pexels(search_term, video_aspect))
    if config.app.get("pixabay_api_keys"):
        items.extend(search_images_pixabay(search_term, video_aspect))
    random.shuffle(items)
    return items


def save_image_as_clip(
    image_url: str,
    save_dir: str = "",
    effect_type: str = "zoom_in",
    duration: float = 1.3,
    video_aspect: VideoAspect = VideoAspect.portrait,
    search_term: str = "",
) -> str:
    """Download stock photo and convert it using FFmpeg into a 1.3s MP4 clip with Ken Burns slow zoom-in or zoom-out."""
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")
    os.makedirs(save_dir, exist_ok=True)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    duration = min(duration, 1.3)  # Strictly maximum 1.3 seconds per user requirement
    frames = int(round(duration * 30))
    if frames < 15:
        frames = 39

    url_hash = utils.md5(image_url.split("?")[0])
    img_temp = os.path.join(save_dir, f"temp-img-{url_hash}.jpg")
    clip_output = os.path.join(save_dir, f"imgclip-{url_hash}-{effect_type}-{video_width}x{video_height}.mp4")

    if os.path.exists(clip_output) and os.path.getsize(clip_output) > 0:
        if search_term and not semantic_video.load_video_metadata(clip_output):
            semantic_video.save_video_metadata(clip_output, search_term, {"is_image": True, "effect": effect_type, "duration": duration})
        return clip_output

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        res = _http_get(image_url, headers=headers, proxies=config.proxy, timeout=(20, 60))
        with open(img_temp, "wb") as f:
            f.write(res.content)

        w, h = video_width, video_height
        if effect_type == "zoom_out":
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},zoompan=z='if(lte(on,-1),1.10,max(1.0,1.10-0.0025*on))':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30"
        else:
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},zoompan=z='min(zoom+0.002,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30"

        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_temp,
            "-vf", vf, "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "faster",
            clip_output
        ]
        import subprocess
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        if os.path.exists(clip_output) and os.path.getsize(clip_output) > 0:
            if search_term:
                semantic_video.save_video_metadata(clip_output, search_term, {"is_image": True, "effect": effect_type, "duration": duration})
            return clip_output
    except Exception as e:
        logger.warning(f"Error creating photo zoom clip from {image_url}: {e}")
    finally:
        if os.path.exists(img_temp):
            try:
                os.remove(img_temp)
            except Exception:
                pass
    return ""


def save_video(
    video_url: str,
    save_dir: str = "",
    search_term: str = "",
    thumbnail_url: str = "",
    preview_images: List[str] = None,
) -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        # Save metadata if search_term is provided and metadata doesn't exist
        if search_term and not semantic_video.load_video_metadata(video_path):
            additional_info = {}
            if thumbnail_url:
                additional_info["thumbnail_url"] = thumbnail_url
            if preview_images:
                additional_info["preview_images"] = preview_images
            semantic_video.save_video_metadata(video_path, search_term, additional_info)
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            _http_get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            clip.close()
            if duration > 0 and fps > 0:
                # Save metadata with search term and image data
                if search_term:
                    additional_info = {}
                    if thumbnail_url:
                        additional_info["thumbnail_url"] = thumbnail_url
                    if preview_images:
                        additional_info["preview_images"] = preview_images
                    semantic_video.save_video_metadata(video_path, search_term, additional_info)
                return video_path
        except Exception as e:
            try:
                os.remove(video_path)
            except Exception:
                pass
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
    return ""


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    enable_images: bool = True,
    image_ratio: float = 0.20,
    image_clip_duration: float = 1.3,
) -> List[str]:
    # Group videos by search term for balanced sampling
    videos_by_term = {}
    found_duration = 0.0
    search_videos = search_videos_pexels
    if source in ["all", "both", "multi", "combined", "pexels,pixabay"]:
        search_videos = search_videos_combined
    elif source == "pixabay":
        search_videos = search_videos_pixabay
    elif source == "pexels":
        if config.app.get("pixabay_api_keys") and config.app.get("video_source") == "all":
            search_videos = search_videos_combined
        else:
            search_videos = search_videos_pexels
    else:
        if config.app.get("pexels_api_keys") and config.app.get("pixabay_api_keys"):
            search_videos = search_videos_combined
        elif config.app.get("pixabay_api_keys"):
            search_videos = search_videos_pixabay
        else:
            search_videos = search_videos_pexels

    # Global URL tracking to prevent duplicates across all search terms
    global_video_urls = set()
    
    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        # Filter out duplicates and associate with search term
        unique_videos = []
        duplicates_removed = 0
        
        for item in video_items:
            # Check for URL duplicates across all search terms
            if item.url not in global_video_urls:
                item.search_term = search_term
                unique_videos.append(item)
                global_video_urls.add(item.url)
                found_duration += item.duration
            else:
                duplicates_removed += 1
        
        if duplicates_removed > 0:
            logger.info(f"removed {duplicates_removed} duplicate URLs for '{search_term}'")
        
        if unique_videos:
            videos_by_term[search_term] = unique_videos

    logger.info(
        f"found videos from {len(videos_by_term)} search terms, total duration: {found_duration} seconds, required: {audio_duration} seconds"
    )
    logger.info(f"total unique video URLs: {len(global_video_urls)}")

    # Create balanced selection from all search terms
    valid_video_items = []
    valid_video_urls = set()
    
    # Round-robin selection from each search term to ensure diversity
    max_videos_per_term = max(2, int((audio_duration * 1.35) / max_clip_duration / len(videos_by_term)) + 1) if videos_by_term else 2
    logger.info(f"targeting max {max_videos_per_term} videos per search term for balanced selection")
    
    # Track selection statistics
    selection_stats = {}
    
    for search_term, videos in videos_by_term.items():
        # ALWAYS shuffle videos within each search term for scene variety
        random.shuffle(videos)
        
        # Take up to max_videos_per_term from this search term
        count = 0
        for item in videos:
            if item.url not in valid_video_urls and count < max_videos_per_term:
                valid_video_items.append(item)
                valid_video_urls.add(item.url)
                count += 1
        
        selection_stats[search_term] = count
        logger.info(f"selected {count} videos from '{search_term}' ({count}/{len(videos)} available)")
    
    # Final shuffle of the balanced selection to blend terms and providers
    random.shuffle(valid_video_items)
    
    logger.info(f"selected {len(valid_video_items)} videos for download with balanced representation")
    
    # Log diversity metrics
    logger.info("🎯 Diversity metrics:")
    logger.info(f"   📊 Search terms represented: {len(selection_stats)}/{len(search_terms)}")
    for term, count in selection_stats.items():
        percentage = (count / len(valid_video_items)) * 100 if valid_video_items else 0
        logger.info(f"   📹 '{term}': {count} videos ({percentage:.1f}%)")

    video_paths = []
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    total_duration = 0.0
    downloaded_urls = set()  # Track downloaded URLs to prevent runtime duplicates
    target_buffer_duration = audio_duration * 1.35
    
    for item in valid_video_items:
        try:
            # Double-check for URL duplicates at download time
            if item.url in downloaded_urls:
                logger.warning(f"skipping duplicate URL: {item.url}")
                continue
                
            logger.info(f"downloading video: {item.url}")
            # Use the search term associated with this specific video item
            item_search_term = getattr(item, 'search_term', 'unknown')
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory, search_term=item_search_term, thumbnail_url=item.thumbnail_url, preview_images=item.preview_images
            )
            if saved_video_path:
                logger.info(f"video saved: {saved_video_path} (search_term: '{item_search_term}')")
                video_paths.append(saved_video_path)
                downloaded_urls.add(item.url)
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration >= target_buffer_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration:.1f} seconds (target: {audio_duration:.1f}s + buffer), ready."
                    )
                    break
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
    
    # Final diversity report
    logger.success(f"downloaded {len(video_paths)} videos")
    logger.info(f"🎯 Final diversity: {len(downloaded_urls)} unique URLs downloaded")

    # Image Integration: strictly 80% videos : 20% photos ratio, max 1.3s duration per photo with slow Ken Burns zoom-in / zoom-out
    if enable_images and image_ratio > 0 and video_paths:
        num_videos = len(video_paths)
        # 80% video : 20% photo proportion means 1 photo for every 4 videos:
        target_photo_count = max(2, int(round(num_videos * (image_ratio / (1.0 - image_ratio)))))
        logger.info(
            f"📸 Image integration active: targeting {target_photo_count} photos for {num_videos} videos "
            f"({image_ratio*100:.0f}% photo proportion, max {image_clip_duration:.1f}s per photo scene with Ken Burns zoom)"
        )

        all_photo_items = []
        for term in search_terms:
            items = search_images_combined(search_term=term, video_aspect=video_aspect)
            all_photo_items.extend(items)

        unique_photos = []
        seen_photo_urls = set()
        for p_item in all_photo_items:
            if p_item.url not in seen_photo_urls:
                seen_photo_urls.add(p_item.url)
                unique_photos.append(p_item)

        random.shuffle(unique_photos)
        logger.info(f"📸 Found {len(unique_photos)} candidate photos across Pexels & Pixabay")

        photo_clips = []
        for idx, p_item in enumerate(unique_photos):
            if len(photo_clips) >= target_photo_count:
                break
            effect = "zoom_in" if (idx % 2 == 0) else "zoom_out"
            clip_path = save_image_as_clip(
                image_url=p_item.url,
                save_dir=material_directory,
                effect_type=effect,
                duration=image_clip_duration,
                video_aspect=video_aspect,
                search_term=getattr(p_item, "search_term", ""),
            )
            if clip_path and os.path.exists(clip_path):
                photo_clips.append(clip_path)
                logger.info(f"📸 [{len(photo_clips)}/{target_photo_count}] Created photo scene ({effect}, {image_clip_duration:.1f}s): {clip_path}")

        logger.success(f"📸 Successfully prepared {len(photo_clips)} photo scenes (max {image_clip_duration}s, zoom-in/out)")
        video_paths.extend(photo_clips)

    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
