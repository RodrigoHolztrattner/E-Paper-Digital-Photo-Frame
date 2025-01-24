import json
import os
import random
import requests
from PIL import Image
import io
from typing import Optional, Tuple, Dict, List
from pathlib import Path
from datetime import datetime
from enum import Enum

class ImmichScaleMode(Enum):
    PAD = "pad"  # Add white padding
    CROP = "crop"  # Crop to fit

class ImmichGroupTracker:
    def __init__(self, group_path: Path):
        self.group_path = group_path
        self.tracking_file = group_path / "tracking.txt"
        self.config_file = group_path / "config.json"
        
        # Create group directory if it doesn't exist
        self.group_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize tracking file if it doesn't exist
        if not self.tracking_file.exists():
            self.reset_tracking()
            
        # Load group config if it exists
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def _save_config(self, config: dict):
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)
            
    def get_tracked_ids(self) -> List[str]:
        if not self.tracking_file.exists():
            return []
        with open(self.tracking_file, 'r') as f:
            return [line.strip() for line in f if line.strip()]
            
    def add_to_tracking(self, image_id: str):
        with open(self.tracking_file, 'a') as f:
            f.write(f"{image_id}\n")
            
    def reset_tracking(self):
        with open(self.tracking_file, 'w') as f:
            f.write('')
            
class ImmichHelper:
    def __init__(self, url: str, image_path: str, api_key: Optional[str] = None, config: Optional[dict] = None):
        self.url = url
        self.base_image_path = Path(image_path)
        self.api_key = api_key or os.getenv('IMMICH_API_KEY')
        self.config = config or {}
        self.group_trackers: Dict[str, ImmichGroupTracker] = {}
        
        if not self.api_key:
            raise ValueError("Immich API key not provided and not found in environment")
        
        self.base_image_path.mkdir(parents=True, exist_ok=True)

    def update_config(self, new_config: Dict):
        self.config.update(new_config)

    def _get_headers(self):
        return {
            'x-api-key': self.api_key,
            'Accept': 'application/json'
        }

    def _get_album_assets(self, album_id: str) -> List[dict]:
        """Get assets from specified album using its ID"""
        url = f"{self.url}/api/albums/{album_id}"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        
        album_data = response.json()
        if 'assets' not in album_data or not album_data['assets']:
            raise ValueError("No assets found in album")
            
        return album_data['assets']

    def _get_group_tracker(self, group_id: str) -> ImmichGroupTracker:  # Update return type
        """Get or create group tracker"""
        if group_id not in self.group_trackers:
            group_path = self.base_image_path / group_id
            self.group_trackers[group_id] = ImmichGroupTracker(group_path)
        return self.group_trackers[group_id]

    def scale_img_in_memory(self, img: Image.Image, target_width: int, target_height: int, 
                        mode: ImmichScaleMode = ImmichScaleMode.PAD) -> Image.Image:
        """Scale image to target size using specified mode"""
        # First scale image maintaining aspect ratio
        width_ratio = target_width / img.width
        height_ratio = target_height / img.height
        
        if mode == ImmichScaleMode.PAD:
            # Use smallest ratio to ensure image fits within target
            scale_factor = min(width_ratio, height_ratio)
        else:  # CROP
            # Use largest ratio to ensure image covers target
            scale_factor = max(width_ratio, height_ratio)
        
        # Resize with calculated scale
        new_width = int(img.width * scale_factor)
        new_height = int(img.height * scale_factor)
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Create output image
        final = Image.new('RGB', (target_width, target_height), (255, 255, 255))
        
        if mode == ImmichScaleMode.PAD:
            # Center the resized image
            x = (target_width - new_width) // 2
            y = (target_height - new_height) // 2
            final.paste(resized, (x, y))
        else:  # CROP
            # Calculate crop coordinates to center
            x = (new_width - target_width) // 2
            y = (new_height - target_height) // 2
            final = resized.crop((x, y, x + target_width, y + target_height))
        
        return final

    def get_random_image(self, group_id: str, album_id: str, width: Optional[int] = None, 
                        height: Optional[int] = None, scale_mode: ImmichScaleMode = ImmichScaleMode.PAD) -> Tuple[str, bytes]:
        """Get random image for specific group and album"""
        tracker = self._get_group_tracker(group_id)
        assets = self._get_album_assets(album_id)  # Now using album_id directly
        
        if not assets:
            raise ValueError("No images available in the album")
        
        tracked_ids = tracker.get_tracked_ids()
        untracked_assets = [asset for asset in assets if asset['id'] not in tracked_ids]
        
        if not untracked_assets:
            tracker.reset_tracking()
            untracked_assets = assets
        
        chosen_asset = random.choice(untracked_assets)
        image_id = chosen_asset['id']
        
        # Download and process image
        image_path = tracker.group_path / f"{image_id}.png"
        if not image_path.exists():
            image_data = self._download_asset(image_id)
            self.add_image(group_id, image_id, image_data)
        
        # Process image
        with Image.open(image_path) as img:
            img = img.convert('RGB')
            
            if width and height:
                img = self.scale_img_in_memory(img, width, height, scale_mode)
            
            if self.config.get('rotation'):
                img = img.rotate(self.config['rotation'], expand=True)
            
            # Convert to bytes
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            # Add to tracking and return
            tracker.add_to_tracking(image_id)
            return image_id, img_byte_arr.getvalue()

    def add_image(self, group_id: str, image_id: str, image_data: bytes):
        """Add new image to group's storage"""
        tracker = self._get_group_tracker(group_id)
        
        img_io = io.BytesIO(image_data)
        try:
            img = Image.open(img_io)
            img = img.convert('RGB')
            
            save_path = tracker.group_path / f"{image_id}.png"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(save_path, 'PNG')
            
        except Exception as e:
            raise ValueError(f"Failed to process image: {str(e)}")

    def reset_group(self, group_id: str, album_name: str):
        """Reset tracking and fetch new images for a group"""
        tracker = self._get_group_tracker(group_id)
        tracker.reset_tracking()
        assets = self._get_album_assets(album_name)
        for asset in assets:
            self.add_image(group_id, asset['id'], self._download_asset(asset['id']))

    def _download_asset(self, asset_id: str) -> bytes:
        """Download asset from Immich server"""
        url = f"{self.url}/api/assets/{asset_id}/original"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.content