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
    
class ImmichHelper:
    DEFAULT_CONFIG = {
        'immich': {
            'rotation': 0,
            'enhanced': 1.0,
            'contrast': 1.0,
        }
    }

    def __init__(self, config_path: str, image_path: str, server_url: str, api_key: Optional[str] = None):
        self.config_path = Path(config_path)
        self.image_path = Path(image_path)
        self.server_url = server_url
        self.api_key = api_key
        self.config = self._load_or_create_config()
        
        if not self.api_key:
            raise ValueError("Immich API key not provided")
        
        # Create groups directory for tracking files
        self.groups_path = self.image_path / "groups"
        self.groups_path.mkdir(parents=True, exist_ok=True)
        self.image_path.mkdir(parents=True, exist_ok=True)

    def _load_or_create_config(self) -> dict:
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    return {**self.DEFAULT_CONFIG, **json.load(f)}
            except json.JSONDecodeError:
                return self.DEFAULT_CONFIG
        else:
            self._save_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG

    def _save_config(self, config: dict):
        """Save config to file, creating parent directories if needed"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=4)

    def _get_headers(self):
        return {
            'x-api-key': self.api_key,
            'Accept': 'application/json'
        }

    def _get_album_assets(self, album_id: str) -> List[dict]:
        """Get assets from specified album"""
        url = f"{self.server_url}/api/albums/{album_id}"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        
        album_data = response.json()
        if 'assets' not in album_data or not album_data['assets']:
            raise ValueError("No assets found in album")
            
        return album_data['assets']

    def _download_asset(self, asset_id: str) -> bytes:
        """Download asset from Immich server"""
        url = f"{self.server_url}/api/assets/{asset_id}/original"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.content

    def _get_group_tracking_file(self, group_id: str) -> Path:
        """Get the tracking file path for a specific group"""
        return self.groups_path / f"{group_id}_tracking.txt"

    def _get_tracked_ids_for_group(self, group_id: str) -> List[str]:
        """Get tracked image IDs for a specific group"""
        tracking_file = self._get_group_tracking_file(group_id)
        if not tracking_file.exists():
            return []
        with open(tracking_file, 'r') as f:
            return [line.strip() for line in f if line.strip()]

    def _add_to_group_tracking(self, group_id: str, image_id: str):
        """Add an image ID to a group's tracking file"""
        tracking_file = self._get_group_tracking_file(group_id)
        with open(tracking_file, 'a') as f:
            f.write(f"{image_id}\n")

    def _reset_group_tracking(self, group_id: str):
        """Reset tracking for a specific group"""
        tracking_file = self._get_group_tracking_file(group_id)
        with open(tracking_file, 'w') as f:
            f.write('')

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

    def get_random_image(self, album_id: str, width: Optional[int] = None, height: Optional[int] = None,
                      scale_mode: ImmichScaleMode = ImmichScaleMode.PAD, group_id: Optional[str] = None) -> Tuple[str, bytes]:
        """Get random image, optionally tracking per group"""
        # Get all available assets from album
        assets = self._get_album_assets(album_id)
        if not assets:
            raise ValueError("No images available in the album")
        
        # Handle group tracking if group_id is provided
        if group_id:
            tracked_ids = self._get_tracked_ids_for_group(group_id)
            untracked_assets = [asset for asset in assets if asset['id'] not in tracked_ids]
            
            if not untracked_assets:
                self._reset_group_tracking(group_id)
                untracked_assets = assets
        else:
            untracked_assets = assets
        
        # Select random untracked asset
        chosen_asset = random.choice(untracked_assets)
        image_id = chosen_asset['id']
        
        try:
            # Process image
            image_data = self._process_image(image_id, width, height, scale_mode)
            
            # Track the image if we're using group tracking
            if group_id:
                self._add_to_group_tracking(group_id, image_id)
                
            return image_id, image_data
            
        except Exception as e:
            print(f"Error processing image {image_id}: {str(e)}")
            raise ValueError(f"Failed to process image: {str(e)}")

    def add_image(self, image_id: str, image_data: bytes):
        """Add new image to cache only"""
        try:
            # Convert bytes directly to Image
            img = Image.open(io.BytesIO(image_data))
            img = img.convert('RGB')
            
            save_path = self.image_path / f"{image_id}.png"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(save_path, 'PNG')
        except Exception as e:
            print(f"Image processing error: {str(e)}")  # Add debug print
            raise ValueError(f"Failed to process image: {str(e)}")

    def reset(self):
        """Not used anymore - group tracking is handled separately"""
        pass

    def update_config(self, new_config: Dict):
        self.config['immich'].update(new_config)
        self._save_config(self.config)

    def _process_image(self, image_id: str, width: Optional[int], height: Optional[int], 
                      scale_mode: ImmichScaleMode) -> bytes:
        """Process an image with the given parameters"""
        # Download or get cached image
        image_path = self.image_path / f"{image_id}.png"
        if not image_path.exists():
            image_data = self._download_asset(image_id)
            if not image_data:
                raise ValueError("Failed to download image data")
            self.add_image(image_id, image_data)

        # Process image
        with Image.open(image_path) as img:
            img = img.convert('RGB')
            
            if width and height:
                img = self.scale_img_in_memory(img, width, height, scale_mode)
            
            if self.config['immich']['rotation']:
                img = img.rotate(self.config['immich']['rotation'], expand=True)
            
            # Convert to bytes
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            return img_byte_arr.getvalue()

    def get_tracked_ids(self) -> List[str]:
        """Public method to access tracked IDs - now uses group tracking"""
        return []  # No global tracking anymore, only per-group

    def get_group_tracking_stats(self, group_id: str, album_id: str) -> Tuple[int, int]:
        """Get tracking statistics for a group's album"""
        assets = self._get_album_assets(album_id)
        total_count = len(assets)
        shown_count = len(self._get_tracked_ids_for_group(group_id))
        return total_count, shown_count